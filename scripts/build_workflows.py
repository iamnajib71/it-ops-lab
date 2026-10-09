"""Generate the n8n workflow JSON files in workflows/.

Workflows are kept as Python so prompts, routing policy and SQL live in one
reviewable place. Run:  python scripts/build_workflows.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "workflows"
PG = {"postgres": {"id": "pgItOps", "name": "IT Ops Postgres"}}
GATEWAY_ID = "itopsGateway001"


def node(name, type_, version, params, pos, creds=None, **extra):
    n = {"id": name.lower().replace(" ", "-"), "name": name, "type": type_, "typeVersion": version,
         "position": pos, "parameters": params}
    if creds:
        n["credentials"] = creds
    n.update(extra)
    return n


def code(name, js, pos):
    return node(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip()}, pos)


def sql(name, query, pos, replacements=None, **extra):
    params = {"operation": "executeQuery", "query": query.strip(), "options": {}}
    if replacements:
        params["options"]["queryReplacement"] = replacements
    return node(name, "n8n-nodes-base.postgres", 2.6, params, pos, PG, **extra)


def call_gateway(name, pos):
    return node(name, "n8n-nodes-base.executeWorkflow", 1.2, {
        "workflowId": {"__rl": True, "value": GATEWAY_ID, "mode": "id"},
        "options": {"waitForSubWorkflow": True},
    }, pos)


def chain(*names):
    conns = {}
    for a, b in zip(names, names[1:]):
        conns.setdefault(a, {"main": [[]]})["main"][0].append({"node": b, "type": "main", "index": 0})
    return conns


def workflow(wid, name, nodes, conns, tags=()):
    return {"id": wid, "name": name, "nodes": nodes, "connections": conns, "active": False,
            "settings": {"executionOrder": "v1", "saveManualExecutions": True,
                         "callerPolicy": "workflowsFromSameOwner"},
            "pinData": {}}


# --------------------------------------------------------------------------------------------
# 1. LLM Gateway: routing, budget guard, rate limit, circuit breaker, retries, fallback, telemetry
# --------------------------------------------------------------------------------------------
GATEWAY_STATE_SQL = """
SELECT
  (SELECT coalesce(sum(est_cost_usd),0) FROM llm_calls WHERE created_at >= date_trunc('day', now()))::float AS spend_today,
  (SELECT coalesce(json_object_agg(model, n), '{}') FROM (
     SELECT model, count(*) n FROM llm_calls WHERE created_at > now() - interval '60 seconds' AND attempt > 0 GROUP BY model) r) AS calls_last_min,
  (SELECT coalesce(json_object_agg(model, n), '{}') FROM (
     SELECT model, count(*) n FROM llm_calls WHERE created_at > now() - interval '10 minutes' AND success = false AND attempt > 0 GROUP BY model) f) AS recent_failures,
  (SELECT coalesce(json_object_agg(model, json_build_object('in', usd_per_1k_input, 'out', usd_per_1k_output, 'tier', tier)), '{}') FROM model_prices) AS prices
"""

GATEWAY_JS = r"""
// LLM gateway: one entry point for every model call in the copilot.
// Policy: route by task -> skip models over budget / rate limit / open circuit -> retry transient
// errors -> fall back down the chain -> validate JSON -> return result plus one telemetry row per attempt.
const req = $('When called by another workflow').first().json;
const state = $input.first().json;
const OLLAMA = $env.OLLAMA_URL || 'http://host.docker.internal:11434';

const ROUTES = {
  classify: ['qwen2.5:3b', 'llama3.1:8b'],
  draft_a:  ['qwen2.5:3b', 'llama3.1:8b'],
  draft_b:  ['llama3.1:8b', 'qwen2.5:3b'],
  judge:    ['llama3.1:8b', 'qwen2.5:3b'],
  digest:   ['qwen2.5:3b', 'llama3.1:8b'],
};
const DAILY_CLOUD_BUDGET_USD = 0.50;   // cost autopilot: cloud tier switches off once spent
const RPM_LIMIT = 30;                  // per-model requests per minute
const CIRCUIT_FAILS = 3;               // failures in 10 min that open the circuit
const MAX_TRIES = 2;                   // attempts per model for transient errors

const chainModels = ROUTES[req.task] || ROUTES.classify;
const attempts = [];
let result = null;
let n = 0;

const price = m => state.prices[m] || { in: 0, out: 0, tier: 'local' };
const skip = (model, reason) => attempts.push({ model, attempt: 0, success: false, error: reason,
  latency_ms: 0, prompt_tokens: 0, output_tokens: 0, est_cost_usd: 0 });

for (const model of chainModels) {
  const p = price(model);
  if (p.tier === 'cloud' && $env.CLOUD_TIER !== 'on') { skip(model, 'skipped: cloud tier disabled (local-only mode)'); continue; }
  if (p.tier === 'cloud' && state.spend_today >= DAILY_CLOUD_BUDGET_USD) { skip(model, 'skipped: daily cloud budget reached'); continue; }
  if ((state.recent_failures[model] || 0) >= CIRCUIT_FAILS) { skip(model, 'skipped: circuit open (repeated failures)'); continue; }
  if ((state.calls_last_min[model] || 0) >= RPM_LIMIT) { skip(model, 'skipped: rate limit'); continue; }

  for (let t = 1; t <= MAX_TRIES; t++) {
    n++;
    const started = Date.now();
    const row = { model, attempt: n, success: false, error: null, prompt_tokens: 0, output_tokens: 0, est_cost_usd: 0 };
    try {
      const res = await this.helpers.httpRequest({
        method: 'POST', url: `${OLLAMA}/api/chat`, json: true, timeout: 120000,
        body: {
          model, stream: false, ...(req.json ? { format: 'json' } : {}),
          options: { temperature: req.temperature ?? 0.2, num_predict: req.max_tokens || 500 },
          messages: [{ role: 'system', content: req.system || '' }, { role: 'user', content: req.prompt }],
        },
      });
      if (res.error) throw new Error(res.error);
      const content = (res.message && res.message.content || '').trim();
      row.prompt_tokens = res.prompt_eval_count || 0;
      row.output_tokens = res.eval_count || 0;
      row.est_cost_usd = (row.prompt_tokens * p.in + row.output_tokens * p.out) / 1000;
      let parsed = null;
      if (req.json) {
        try { parsed = JSON.parse(content); } catch (e) { throw new Error('invalid JSON from model'); }
      }
      row.success = true;
      row.latency_ms = Date.now() - started;
      attempts.push(row);
      result = { content, parsed, model };
      break;
    } catch (e) {
      row.latency_ms = Date.now() - started;
      const msg = String(e.message || e).slice(0, 300);
      row.error = msg;
      attempts.push(row);
      // 4xx-style errors (not found, no credits, unauthorised) are permanent: move to the next model.
      if (/40[0-4]|not found|credits|usage|unauthori[sz]ed/i.test(msg)) break;
    }
  }
  if (result) break;
}

const firstModel = attempts.find(a => a.attempt > 0)?.model;
return [{ json: {
  ok: !!result,
  task: req.task,
  ticket_id: req.ticket_id ?? null,
  model: result?.model ?? null,
  content: result?.content ?? null,
  parsed: result?.parsed ?? null,
  fallback_used: !!result && result.model !== chainModels[0],
  attempts,
  total_latency_ms: attempts.reduce((s, a) => s + a.latency_ms, 0),
  est_cost_usd: attempts.reduce((s, a) => s + a.est_cost_usd, 0),
  first_model_tried: firstModel ?? null,
} }];
"""

GATEWAY_LOG_SQL = """
INSERT INTO llm_calls (ticket_id, task, model, attempt, fallback_used, success, error, prompt_tokens, output_tokens, latency_ms, est_cost_usd)
SELECT ($1::jsonb->>'ticket_id')::bigint, $1::jsonb->>'task', a.model, a.attempt, ($1::jsonb->>'fallback_used')::boolean,
       a.success, a.error, a.prompt_tokens, a.output_tokens, a.latency_ms, a.est_cost_usd
FROM jsonb_to_recordset($1::jsonb->'attempts')
  AS a(model text, attempt int, success boolean, error text, prompt_tokens int, output_tokens int, latency_ms int, est_cost_usd numeric)
RETURNING id
"""

gateway = workflow(GATEWAY_ID, "LLM Gateway (routing, fallback, cost guard)", [
    node("When called by another workflow", "n8n-nodes-base.executeWorkflowTrigger", 1.1,
         {"inputSource": "passthrough"}, [0, 0]),
    sql("Gateway state", GATEWAY_STATE_SQL, [220, 0]),
    code("Route and call model", GATEWAY_JS, [440, 0]),
    sql("Log attempts", GATEWAY_LOG_SQL, [660, 0], "={{ JSON.stringify($json) }}"),
    code("Return result", "return [{ json: $('Route and call model').first().json }];", [880, 0]),
], chain("When called by another workflow", "Gateway state", "Route and call model", "Log attempts", "Return result"),
    tags=["it-ops-lab"])


# --------------------------------------------------------------------------------------------
# 2. Ticket intake: PII check -> triage -> hybrid RAG -> two drafts -> judge -> policy gate
# --------------------------------------------------------------------------------------------
NORMALISE_JS = r"""
// Normalise the request and detect personal/sensitive data before any model sees it.
const b = $input.first().json.body || $input.first().json;
const text = `${b.subject || ''}\n${b.body || b.description || ''}`.trim();
const PII = {
  card: /\b(?:\d[ -]?){13,16}\b/,
  tfn: /\b\d{3}[ -]?\d{3}[ -]?\d{3}\b/,
  password: /\b(password|passcode|pwd)\s*(is|:|=)\s*\S+/i,
  dob: /\b(dob|date of birth)\b/i,
  medicare: /\bmedicare\b/i,
};
const hits = Object.entries(PII).filter(([, re]) => re.test(text)).map(([k]) => k);
const redacted = String(b.body || b.description || '')
  .replace(PII.card, '[REDACTED-NUMBER]')
  .replace(PII.tfn, '[REDACTED-NUMBER]')
  .replace(PII.password, '$1 $2 [REDACTED]');
return [{ json: {
  requester_name: b.name || 'Unknown', requester_email: b.email || null, channel: b.channel || 'webhook',
  subject: (b.subject || text.slice(0, 80)).slice(0, 200), body: redacted,
  contains_pii: hits.length > 0, pii_types: hits,
} }];
"""

INSERT_TICKET_SQL = """
INSERT INTO tickets (requester_name, requester_email, channel, subject, body, contains_pii)
SELECT x.requester_name, x.requester_email, x.channel, x.subject, x.body, x.contains_pii
FROM jsonb_to_record($1::jsonb) AS x(requester_name text, requester_email text, channel text, subject text, body text, contains_pii boolean)
RETURNING id
"""

CLASSIFY_REQ_JS = r"""
const t = $('Normalise and PII check').first().json;
const ticket_id = $input.first().json.id;
return [{ json: {
  task: 'classify', json: true, ticket_id, max_tokens: 200,
  system: `You triage IT service desk tickets for a small office. Reply with JSON only:
{"category": one of ["access","vpn","network","printing","file_share","email","hardware","software","security","onboarding","other"],
 "priority": one of ["P1","P2","P3","P4"],
 "summary": "max 20 words",
 "security_risk": true|false}
Priority guide: P1 business down or security incident (outage, compromised account, phishing clicked, lost device).
P2 team or service degraded (several users affected). P3 single user issue. P4 request or how-to question.`,
  prompt: `Subject: ${t.subject}\n\n${t.body}`,
} }];
"""

RETRIEVE_JS = r"""
// Embed the ticket text and fetch the best knowledge base sections with hybrid search (RRF).
const t = $('Normalise and PII check').first().json;
const OLLAMA = $env.OLLAMA_URL || 'http://host.docker.internal:11434';
const q = `${t.subject}\n${t.body}`;
const res = await this.helpers.httpRequest({ method: 'POST', url: `${OLLAMA}/api/embed`, json: true,
  body: { model: 'nomic-embed-text', input: 'search_query: ' + q } });
return [{ json: { q, vec: JSON.stringify(res.embeddings[0]), triage: $input.first().json } }];
"""

# n8n splits multiple query parameters on commas, so every multi-value query takes one JSON parameter.
SEARCH_SQL = "SELECT id, doc_id, coalesce(section,'') AS section, content, rrf, kw_rank, vec_rank FROM kb_retrieve($1::jsonb->>'q', ($1::jsonb->>'vec')::vector, CASE WHEN $1::jsonb->>'mode' = 'reranked' THEN 20 ELSE 4 END, $1::jsonb->>'mode')"
RETRIEVE_JS = RETRIEVE_JS.replace('q, vec:', "q, mode: $env.RAG_MEASURED === 'on' ? ($env.RAG_VARIANT || 'keyword') : 'hybrid', vec:")
RERANK_JS = r"""
const candidates = $input.all().map(i => i.json).filter(c => c.doc_id);
const mode = $('Retrieve KB').first().json.mode;
if (!candidates.length) return [{json: {retrieval_mode: mode}}];
if (mode !== 'reranked') return candidates.map(json => ({json: {...json, retrieval_mode: mode}}));
const query = $('Retrieve KB').first().json.q;
const system = __RERANK_PROMPT__;
try {
  const response = await this.helpers.httpRequest({method: 'POST',
    url: `${$env.OLLAMA_URL || 'http://host.docker.internal:11434'}/api/chat`, json: true, timeout: 300000,
    body: {model: 'qwen2.5:3b', stream: false, format: {type:'object',
      properties:{ranking:{type:'array',items:{type:'integer',enum:candidates.map(c=>Number(c.id))},
        minItems:candidates.length,maxItems:candidates.length}},required:['ranking'],additionalProperties:false},
      options: {temperature: 0, seed: 42, num_predict: 600, num_ctx: 8192},
      messages: [{role: 'system', content: system}, {role: 'user', content: JSON.stringify({question: query,
        sections: candidates.map(c => ({id: Number(c.id), doc_id: c.doc_id, section: c.section, content: c.content}))})}]}});
  const order = JSON.parse(response.message.content).ranking;
  if (!Array.isArray(order) || order.length !== candidates.length || new Set(order).size !== candidates.length ||
      order.some(i => !Number.isInteger(i) || !candidates.some(c => Number(c.id) === i))) throw new Error('invalid ranking');
  return order.slice(0,4).map(i => ({json: {...candidates.find(c => Number(c.id) === i), retrieval_mode: 'reranked'}}));
} catch (e) {
  // Retain service availability, and surface the fallback instead of pretending reranking succeeded.
  return candidates.slice(0,4).map(json => ({json: {...json, retrieval_mode: 'hybrid-fallback', rerank_error: String(e.message).slice(0,200)}}));
}
""".replace('__RERANK_PROMPT__', json.dumps((ROOT / 'eval/prompts/reranker.txt').read_text(encoding='utf-8')))

DRAFT_REQ_JS = r"""
// Build the same grounded prompt for two different models (A and B) so a judge can arbitrate.
const t = $('Normalise and PII check').first().json;
const ticket_id = $('Insert ticket').first().json.id;
const triage = $('Retrieve KB').first().json.triage;
const kb = $input.all().map(i => i.json).filter(c => c.doc_id);
const context = kb.map(k => `[${k.doc_id}#${k.section}]\n${k.content}`).join('\n\n');
const system = `You are an IT service desk analyst replying to a staff member.
Use ONLY the knowledge base excerpts provided, and only the steps that apply to this person's exact problem
(skip advice meant for other situations, e.g. lost devices or other services). Give short numbered steps. Cite every step with its source tag
exactly as written, e.g. [vpn-wireguard#Troubleshooting]. If the excerpts do not cover the issue, say a technician
will follow up and do not guess. Max 140 words. Reply with JSON only: {"reply": "...", "citations": ["doc#section", ...]}`;
const prompt = `Ticket (${triage.parsed?.priority || '?'}, ${triage.parsed?.category || '?'}):\nSubject: ${t.subject}\n${t.body}\n\nKnowledge base excerpts:\n${context}`;
const base = { json: true, ticket_id, system, prompt, max_tokens: 450 };
return [{ json: { ...base, task: 'draft_a' } }, { json: { ...base, task: 'draft_b' } }];
"""

JUDGE_REQ_JS = r"""
// Blind arbitration: the judge sees two anonymous drafts plus the evidence, and must check grounding.
const drafts = $input.all().map(i => i.json);
const a = drafts.find(d => d.task === 'draft_a') || drafts[0];
const b = drafts.find(d => d.task === 'draft_b') || drafts[1] || drafts[0];
const kb = $('Rerank KB').all().map(i => i.json).filter(c => c.doc_id);
const t = $('Normalise and PII check').first().json;
const context = kb.map(k => `[${k.doc_id}#${k.section}]\n${k.content}`).join('\n\n');
const show = d => d && d.ok ? (d.parsed?.reply || d.content) : '(no draft: model failed)';
return [{ json: {
  task: 'judge', json: true, ticket_id: $('Insert ticket').first().json.id, max_tokens: 300, temperature: 0,
  system: `You are a strict reviewer of IT support replies. Compare Draft A and Draft B against the evidence.
A reply is grounded only if every instruction appears in the evidence AND applies to this ticket's situation
(advice copied from an unrelated situation counts as unsupported). Be strict: confidence above 0.8 only if the
better draft is fully grounded, relevant, and would resolve the issue without a technician. Reply with JSON only:
{"winner": "A" or "B", "grounded": true|false, "unsupported_claims": ["..."], "confidence": number 0..1, "reason": "one sentence"}`,
  prompt: `Ticket: ${t.subject}\n${t.body}\n\nEvidence:\n${context}\n\nDraft A:\n${show(a)}\n\nDraft B:\n${show(b)}`,
  drafts: { A: { model: a?.model, ok: a?.ok, reply: a?.parsed?.reply, citations: a?.parsed?.citations || [] },
            B: { model: b?.model, ok: b?.ok, reply: b?.parsed?.reply, citations: b?.parsed?.citations || [] } },
} }];
"""

GATE_JS = r"""
// Policy gate (mirrors kb/service-desk-policy.md): auto-send only low-risk, confident, grounded P3/P4 answers.
const t = $('Normalise and PII check').first().json;
const ticket_id = $('Insert ticket').first().json.id;
const triage = $('Retrieve KB').first().json.triage.parsed || {};
const judgeRun = $input.first().json;
const j = judgeRun.parsed || {};
const drafts = $('Build judge request').first().json.drafts;
const kb = $('Rerank KB').all().filter(i => i.json.doc_id).map(i => `${i.json.doc_id}#${i.json.section}`);
const pick = j.winner === 'B' && drafts.B.ok ? drafts.B : (drafts.A.ok ? drafts.A : drafts.B);
// Small models often under-escape Windows paths in JSON ("\f" becomes a form feed): restore UNC paths.
const cleanReply = s => (s || '').replace(/\f/g, '\\f').replace(/(^|[^\\])\\(fileserver)/g, '$1\\\\$2');

// Deterministic checks that do not rely on any model.
const cites = (pick.citations || []).filter(c => kb.includes(String(c).replace(/^\[|\]$/g, '')));
const citationsValid = cites.length > 0;
const priority = ['P1','P2','P3','P4'].includes(triage.priority) ? triage.priority : 'P2';
const category = triage.category || 'other';
const confidence = Math.max(0, Math.min(1, Number(j.confidence) || 0));

const reasons = [];
if (!judgeRun.ok) reasons.push('judge unavailable');
if (t.contains_pii) reasons.push('contains personal or sensitive data');
if (triage.security_risk || category === 'security') reasons.push('security related');
// Rule-based backstop: access/permission requests always need approval, whatever the model's category.
const accessAsk = /\b(need|get|request|grant|give|add)\b[^.]{0,40}\b(access|permissions?)\b|\bpermissions? to\b/i.test(`${t.subject} ${t.body}`);
if (category === 'access' || category === 'onboarding' || accessAsk) reasons.push('access change needs approval');
if (!['P3','P4'].includes(priority)) reasons.push(`${priority} needs a human`);
if (!j.grounded) reasons.push('judge found unsupported content');
if (!citationsValid) reasons.push('no valid knowledge base citation');
if (confidence < 0.8) reasons.push(`confidence ${confidence.toFixed(2)} below 0.80`);
// Cross-model agreement: two independent drafts should rely on the same article.
const docs = d => new Set((d.citations || []).map(c => String(c).replace(/^\[/, '').split('#')[0]));
const agree = drafts.A.ok && drafts.B.ok && [...docs(drafts.A)].some(x => docs(drafts.B).has(x));
if (!agree) reasons.push('drafts disagree on the source article');

const status = priority === 'P1' || category === 'security' ? 'escalated'
  : reasons.length === 0 ? 'auto_resolved' : 'awaiting_approval';
const hours = { P1: 4, P2: 8, P3: 24, P4: 40 }[priority];   // business-hour targets, simplified to clock hours

return [{ json: {
  id: ticket_id, category, priority, summary: triage.summary || null, status,
  draft_reply: cleanReply(pick.reply) || null, citations: cites, confidence,
  judge_verdict: { winner: j.winner, grounded: !!j.grounded, unsupported_claims: j.unsupported_claims || [],
                   reason: j.reason || null, judge_model: judgeRun.model, draft_models: { A: drafts.A.model, B: drafts.B.model },
                   gate_reasons: reasons, retrieval_mode: $('Rerank KB').first().json.retrieval_mode,
                   rerank_error: $('Rerank KB').first().json.rerank_error || null },
  sla_hours: hours,
} }];
"""

UPDATE_TICKET_SQL = """
UPDATE tickets t SET category = x.category, priority = x.priority, summary = x.summary, status = x.status,
  draft_reply = x.draft_reply, citations = x.citations, confidence = x.confidence, judge_verdict = x.judge_verdict,
  sla_due_at = t.created_at + make_interval(hours => x.sla_hours),
  resolved_at = CASE WHEN x.status = 'auto_resolved' THEN now() END
FROM jsonb_to_record($1::jsonb) AS x(id bigint, category text, priority text, summary text, status text, draft_reply text,
  citations jsonb, confidence numeric, judge_verdict jsonb, sla_hours int)
WHERE t.id = x.id
RETURNING t.id, t.status, t.priority, t.category, t.summary, t.confidence, t.draft_reply, t.citations, t.judge_verdict, t.sla_due_at
"""

intake = workflow("itopsIntake00001", "Ticket intake (triage, hybrid RAG, arbitration, policy gate)", [
    node("New ticket", "n8n-nodes-base.webhook", 2,
         {"httpMethod": "POST", "path": "ticket", "responseMode": "responseNode", "options": {}},
         [0, 0], webhookId="7d3c2f8e-1a4b-4c55-9d1e-ticket000001"),
    code("Normalise and PII check", NORMALISE_JS, [200, 0]),
    sql("Insert ticket", INSERT_TICKET_SQL, [400, 0], "={{ JSON.stringify($json) }}"),
    code("Build classify request", CLASSIFY_REQ_JS, [600, 0]),
    call_gateway("Gateway: classify", [800, 0]),
    code("Retrieve KB", RETRIEVE_JS, [1000, 0]),
    sql("Hybrid search", SEARCH_SQL, [1200, 0], "={{ JSON.stringify({ q: $json.q, vec: $json.vec, mode: $json.mode }) }}", alwaysOutputData=True),
    code("Rerank KB", RERANK_JS, [1300, 0]),
    code("Build draft requests", DRAFT_REQ_JS, [1400, 0]),
    node("Gateway: drafts A and B", "n8n-nodes-base.executeWorkflow", 1.2, {
        "workflowId": {"__rl": True, "value": GATEWAY_ID, "mode": "id"},
        "mode": "each", "options": {"waitForSubWorkflow": True}}, [1600, 0]),
    code("Build judge request", JUDGE_REQ_JS, [1800, 0]),
    call_gateway("Gateway: judge", [2000, 0]),
    code("Policy gate", GATE_JS, [2200, 0]),
    sql("Update ticket", UPDATE_TICKET_SQL, [2400, 0], "={{ JSON.stringify($json) }}"),
    node("Respond", "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "firstIncomingItem", "options": {}}, [2600, 0]),
], chain("New ticket", "Normalise and PII check", "Insert ticket", "Build classify request", "Gateway: classify",
         "Retrieve KB", "Hybrid search", "Rerank KB", "Build draft requests", "Gateway: drafts A and B", "Build judge request",
         "Gateway: judge", "Policy gate", "Update ticket", "Respond"), tags=["it-ops-lab"])


# --------------------------------------------------------------------------------------------
# 3. Human approval (human-in-the-loop for anything the gate held back)
# --------------------------------------------------------------------------------------------
APPROVE_SQL = """
UPDATE tickets SET status = CASE WHEN $1::jsonb->>'action' = 'approve' THEN 'approved' ELSE 'rejected' END,
  approved_by = $1::jsonb->>'by', resolved_at = CASE WHEN $1::jsonb->>'action' = 'approve' THEN now() END
WHERE id = ($1::jsonb->>'id')::bigint AND status IN ('awaiting_approval', 'escalated')
RETURNING id, status, approved_by, draft_reply
"""

approval = workflow("itopsApproval001", "Approve or reject a drafted reply", [
    node("Approval link", "n8n-nodes-base.webhook", 2,
         {"httpMethod": "GET", "path": "approve", "responseMode": "lastNode",
          "options": {}}, [0, 0], webhookId="7d3c2f8e-1a4b-4c55-9d1e-approve00001"),
    code("Validate", r"""
const q = $input.first().json.query || {};
// Lab stand-in for SSO: approval links carry a shared token from .env (APPROVAL_TOKEN).
if (!$env.APPROVAL_TOKEN || q.token !== $env.APPROVAL_TOKEN) throw new Error('Invalid or missing approval token');
const action = q.action === 'approve' ? 'approve' : q.action === 'reject' ? 'reject' : null;
if (!/^\d+$/.test(q.id || '') || !action) throw new Error('Use ?id=<ticket>&action=approve|reject&by=<name>&token=<token>');
return [{ json: { id: q.id, action, by: (q.by || 'technician').slice(0, 60) } }];
""", [220, 0]),
    sql("Record decision", APPROVE_SQL, [440, 0], "={{ JSON.stringify($json) }}",
        alwaysOutputData=True),
    code("Result", r"""
const r = $input.first().json;
return [{ json: r.id ? { ok: true, ticket: r.id, status: r.status, by: r.approved_by }
                     : { ok: false, message: 'Ticket not found or not awaiting approval' } }];
""", [660, 0]),
], chain("Approval link", "Validate", "Record decision", "Result"), tags=["it-ops-lab"])


# --------------------------------------------------------------------------------------------
# 4. SLA monitor: flag tickets about to breach or already breached
# --------------------------------------------------------------------------------------------
SLA_SQL = """
UPDATE tickets SET sla_alerted = true
WHERE status IN ('new', 'awaiting_approval', 'escalated') AND NOT sla_alerted
  AND sla_due_at < now() + interval '30 minutes'
RETURNING id, priority, subject, status, sla_due_at, (sla_due_at < now()) AS breached
"""

sla = workflow("itopsSlaMonitor1", "SLA monitor (every 5 minutes)", [
    node("Every 5 minutes", "n8n-nodes-base.scheduleTrigger", 1.2,
         {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}}, [0, 0]),
    sql("Flag at-risk tickets", SLA_SQL, [220, 0]),
    code("Format alert", r"""
// In production this feeds Teams/Slack/email; the lab records the alert in the execution log.
return $input.all().filter(i => i.json.id).map(i => ({ json: {
  alert: `${i.json.breached ? 'BREACHED' : 'At risk'}: #${i.json.id} ${i.json.priority} "${i.json.subject}" (${i.json.status}) due ${i.json.sla_due_at}`,
} }));
""", [440, 0]),
], chain("Every 5 minutes", "Flag at-risk tickets", "Format alert"), tags=["it-ops-lab"])


# --------------------------------------------------------------------------------------------
# 5. Daily digest: KPIs + a short narrative written through the gateway
# --------------------------------------------------------------------------------------------
DIGEST_STATS_SQL = """
SELECT json_build_object(
  'tickets', count(*),
  'auto_resolved', count(*) FILTER (WHERE status = 'auto_resolved'),
  'awaiting_approval', count(*) FILTER (WHERE status = 'awaiting_approval'),
  'escalated', count(*) FILTER (WHERE status = 'escalated'),
  'by_category', (SELECT coalesce(json_object_agg(category, n), '{}') FROM (SELECT coalesce(category, 'unclassified') AS category, count(*) n FROM tickets
                   WHERE created_at >= current_date GROUP BY 1) c),
  'llm_calls', (SELECT count(*) FROM llm_calls WHERE created_at >= current_date AND attempt > 0),
  'fallbacks', (SELECT count(DISTINCT (ticket_id, task)) FROM llm_calls WHERE created_at >= current_date AND fallback_used),
  'est_cost_usd', (SELECT coalesce(round(sum(est_cost_usd), 4), 0) FROM llm_calls WHERE created_at >= current_date)
) AS stats FROM tickets WHERE created_at >= current_date
"""

digest = workflow("itopsDigest00001", "Daily service desk digest", [
    node("Weekdays 5pm", "n8n-nodes-base.scheduleTrigger", 1.2,
         {"rule": {"interval": [{"field": "cronExpression", "expression": "0 17 * * 1-5"}]}}, [0, 0]),
    sql("Today's stats", DIGEST_STATS_SQL, [220, 0]),
    code("Build digest request", r"""
const stats = $input.first().json.stats;
return [{ json: { task: 'digest', json: false, max_tokens: 220, stats,
  system: 'You write a 4-sentence end-of-day summary for an IT manager. Use only the numbers given. No greetings.',
  prompt: `Service desk stats for today (JSON): ${JSON.stringify(stats)}` } }];
""", [440, 0]),
    call_gateway("Gateway: digest", [660, 0]),
    sql("Save digest", """
INSERT INTO daily_digests (day, stats, narrative) VALUES (current_date, $1::jsonb->'stats', $1::jsonb->>'narrative')
ON CONFLICT (day) DO UPDATE SET stats = EXCLUDED.stats, narrative = EXCLUDED.narrative, created_at = now()
RETURNING day, narrative
""", [880, 0], "={{ JSON.stringify({ stats: $('Build digest request').first().json.stats, narrative: $json.content || 'Digest model unavailable.' }) }}"),
], chain("Weekdays 5pm", "Today's stats", "Build digest request", "Gateway: digest", "Save digest"), tags=["it-ops-lab"])

# Manual trigger copy of the digest so it can be run on demand from a webhook during demos.
digest_now = json.loads(json.dumps(digest))
digest_now["id"], digest_now["name"] = "itopsDigestNow01", "Daily digest (run now)"
digest_now["nodes"][0] = node("Run digest now", "n8n-nodes-base.webhook", 2,
                              {"httpMethod": "POST", "path": "digest", "responseMode": "lastNode", "options": {}},
                              [0, 0], webhookId="7d3c2f8e-1a4b-4c55-9d1e-digest000001")
digest_now["connections"] = chain("Run digest now", "Today's stats", "Build digest request", "Gateway: digest", "Save digest")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for wf, fname in [(gateway, "01-llm-gateway"), (intake, "02-ticket-intake"), (approval, "03-approval"),
                      (sla, "04-sla-monitor"), (digest, "05-daily-digest"), (digest_now, "06-digest-now")]:
        (OUT / f"{fname}.json").write_text(json.dumps(wf, indent=2), encoding="utf-8")
        print("wrote", fname)
