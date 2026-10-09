-- IT Ops Lab schema: tickets, knowledge base (hybrid search), LLM gateway telemetry.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS n8n;

-- Knowledge base chunks: dense vector (nomic-embed-text, 768-d) + sparse full-text index.
CREATE TABLE IF NOT EXISTS kb_chunks (
  id          BIGSERIAL PRIMARY KEY,
  doc_id      TEXT NOT NULL,
  title       TEXT NOT NULL,
  section     TEXT,
  content     TEXT NOT NULL,
  embedding   vector(768),
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || coalesce(section,'') || ' ' || content)) STORED,
  updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kb_chunks_tsv_idx ON kb_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS kb_chunks_vec_idx ON kb_chunks USING hnsw (embedding vector_cosine_ops);

-- Hybrid retrieval with Reciprocal Rank Fusion (RRF): combines keyword and semantic rankings.
-- Keyword side ORs the query's stemmed terms (ranked by cover density), so a long natural-language
-- ticket still matches articles that share only some of its words.
CREATE OR REPLACE FUNCTION kb_hybrid_search(q_text TEXT, q_vec vector(768), k INT DEFAULT 4)
RETURNS TABLE(id BIGINT, doc_id TEXT, title TEXT, section TEXT, content TEXT, rrf DOUBLE PRECISION, kw_rank INT, vec_rank INT)
LANGUAGE sql STABLE AS $$
  WITH tq AS (
    SELECT to_tsquery('english', nullif(array_to_string(tsvector_to_array(to_tsvector('english', q_text)), ' | '), '')) AS q
  ), kw AS (
    SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, tq.q) DESC, c.id)::INT AS r
    FROM kb_chunks c, tq
    WHERE tq.q IS NOT NULL AND c.tsv @@ tq.q
    ORDER BY ts_rank_cd(c.tsv, tq.q) DESC, c.id
    LIMIT 20
  ), vec AS (
    SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> q_vec, c.id)::INT AS r
    FROM kb_chunks c
    ORDER BY c.embedding <=> q_vec, c.id
    LIMIT 20
  )
  SELECT c.id, c.doc_id, c.title, c.section, c.content,
         coalesce(1.0/(60+kw.r),0) + coalesce(1.0/(60+vec.r),0) AS rrf,
         kw.r, vec.r
  FROM kb_chunks c
  LEFT JOIN kw ON kw.id = c.id
  LEFT JOIN vec ON vec.id = c.id
  WHERE kw.id IS NOT NULL OR vec.id IS NOT NULL
  ORDER BY rrf DESC, c.id
  LIMIT k;
$$;

-- Measured variants; the original hybrid function remains available unchanged.
CREATE OR REPLACE FUNCTION kb_retrieve(q_text TEXT, q_vec vector(768), k INT DEFAULT 4, mode TEXT DEFAULT 'hybrid')
RETURNS TABLE(id BIGINT, doc_id TEXT, title TEXT, section TEXT, content TEXT, rrf DOUBLE PRECISION, kw_rank INT, vec_rank INT)
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF mode = 'keyword' THEN
    RETURN QUERY
      WITH tq AS (SELECT to_tsquery('english',nullif(array_to_string(tsvector_to_array(to_tsvector('english',q_text)), ' | '),'')) q)
      SELECT c.id,c.doc_id,c.title,c.section,c.content,ts_rank_cd(c.tsv,tq.q)::double precision,
        row_number() OVER (ORDER BY ts_rank_cd(c.tsv,tq.q) DESC,c.id)::int,NULL::int
      FROM kb_chunks c,tq WHERE tq.q IS NOT NULL AND c.tsv @@ tq.q
      ORDER BY ts_rank_cd(c.tsv,tq.q) DESC,c.id LIMIT k;
  ELSIF mode = 'vector' THEN
    RETURN QUERY SELECT c.id,c.doc_id,c.title,c.section,c.content,(1-(c.embedding <=> q_vec))::double precision,
      NULL::int,row_number() OVER (ORDER BY c.embedding <=> q_vec,c.id)::int
      FROM kb_chunks c ORDER BY c.embedding <=> q_vec,c.id LIMIT k;
  ELSIF mode IN ('hybrid','reranked') THEN
    RETURN QUERY SELECT * FROM kb_hybrid_search(q_text,q_vec,k);
  ELSE
    RAISE EXCEPTION 'Unknown retrieval mode: %',mode;
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS tickets (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ DEFAULT now(),
  requester_name  TEXT,
  requester_email TEXT,
  channel         TEXT DEFAULT 'form',
  subject         TEXT,
  body            TEXT,
  category        TEXT,
  priority        TEXT,           -- P1..P4
  summary         TEXT,
  contains_pii    BOOLEAN DEFAULT false,
  draft_reply     TEXT,
  citations       JSONB,
  confidence      NUMERIC(4,3),
  judge_verdict   JSONB,
  status          TEXT DEFAULT 'new',  -- new | auto_resolved | awaiting_approval | approved | rejected | escalated
  sla_due_at      TIMESTAMPTZ,
  resolved_at     TIMESTAMPTZ,
  approved_by     TEXT,
  sla_alerted     BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS tickets_status_idx ON tickets(status);

-- Every model call made through the LLM gateway (cost/latency/fallback observability).
CREATE TABLE IF NOT EXISTS llm_calls (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ DEFAULT now(),
  ticket_id       BIGINT,
  task            TEXT,           -- classify | draft | judge | digest
  model           TEXT,
  attempt         INT,
  fallback_used   BOOLEAN,
  success         BOOLEAN,
  error           TEXT,
  prompt_tokens   INT,
  output_tokens   INT,
  latency_ms      INT,
  est_cost_usd    NUMERIC(10,6)
);

-- Reference price list used for cost estimates (local models are free; cloud prices are illustrative).
CREATE TABLE IF NOT EXISTS model_prices (
  model              TEXT PRIMARY KEY,
  usd_per_1k_input   NUMERIC(10,6),
  usd_per_1k_output  NUMERIC(10,6),
  tier               TEXT
);
INSERT INTO model_prices VALUES
  ('qwen2.5:3b', 0, 0, 'local-fast'),
  ('llama3.1:8b', 0, 0, 'local-strong'),
  ('glm-5.3:cloud', 0.0006, 0.0022, 'cloud')
ON CONFLICT (model) DO NOTHING;

CREATE TABLE IF NOT EXISTS daily_digests (
  day        DATE PRIMARY KEY,
  stats      JSONB,
  narrative  TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE OR REPLACE VIEW v_ticket_kpis AS
SELECT date_trunc('day', created_at) AS day,
       count(*) AS tickets,
       count(*) FILTER (WHERE status = 'auto_resolved') AS auto_resolved,
       count(*) FILTER (WHERE status IN ('awaiting_approval','approved','rejected')) AS human_reviewed,
       count(*) FILTER (WHERE status = 'escalated') AS escalated,
       round(avg(confidence)::numeric, 3) AS avg_confidence
FROM tickets GROUP BY 1;
