"""Shared ranking, scoring and local-model calls; no gold labels enter retrieval."""
import hashlib
import json
import math
import os
import pathlib
import subprocess
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
EMBED_MODEL = 'nomic-embed-text'
RERANK_MODEL = 'qwen2.5:3b'
VARIANTS = ('keyword', 'vector', 'hybrid', 'reranked')


def digest(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode()); h.update(p.read_bytes().replace(b'\r\n',b'\n'))
    return h.hexdigest()


def provenance():
    return {'utc': datetime.now(timezone.utc).isoformat(),
            'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)),
            'kb_sha256': digest((ROOT / 'kb').glob('*.md')),
            'questions_sha256': digest([ROOT / 'eval/questions.jsonl']),
            'sql_sha256': digest([ROOT / 'db/init.sql']),
            'prompts_sha256': digest((ROOT / 'eval/prompts').glob('*.txt'))}


def questions():
    return [json.loads(s) for s in (ROOT / 'eval/questions.jsonl').read_text().splitlines()]


def api(path, body):
    url = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
    # Cloud model names are never permitted in this evaluation.
    if ':cloud' in body.get('model', ''):
        raise ValueError('Local models only')
    req = urllib.request.Request(url + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def model_manifest():
    base=os.environ.get('OLLAMA_URL','http://localhost:11434')
    with urllib.request.urlopen(base+'/api/tags',timeout=30) as r:
        models=json.load(r)['models']
    with urllib.request.urlopen(base+'/api/version',timeout=30) as r:
        version=json.load(r)
    return {'ollama':version,'models':[{k:m[k] for k in ('name','digest','size')} for m in models
      if m['name'].split(':')[0] in ('nomic-embed-text','qwen2.5','llama3.1')]}


def chat(model, system, prompt, tokens=600, schema=None):
    r = api('/api/chat', {'model': model, 'stream': False, 'format': schema or 'json',
            'options': {'temperature': 0, 'seed': 42, 'num_predict': tokens, 'num_ctx': 8192},
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]})
    raw=r['message']['content']
    try: return json.loads(raw)
    except json.JSONDecodeError as e: raise ValueError('Invalid JSON model response: '+raw) from e


def embed(text, query=True):
    prefix = 'search_query: ' if query else 'search_document: '
    return api('/api/embed', {'model': EMBED_MODEL, 'input': prefix + text})['embeddings'][0]


def cosine(a, b):
    return sum(x*y for x,y in zip(a,b)) / math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))


def rank(kw, vec, scores=None):
    fused = {}
    for ranking in (kw[:20], vec[:20]):
        for i, cid in enumerate(ranking, 1):
            fused[cid] = fused.get(cid, 0) + 1/(60+i)
    hybrid = sorted(fused, key=lambda cid: (-fused[cid], cid))
    reranked = sorted(hybrid[:20], key=lambda cid: (scores.get(str(cid), 999), hybrid.index(cid))) if scores is not None else hybrid
    return dict(zip(VARIANTS, (kw, vec, hybrid, reranked)))


def rerank(question, candidates):
    prompt = json.dumps({'question': question, 'sections': candidates}, ensure_ascii=False)
    ids = [c['id'] for c in candidates]
    schema={'type':'object','properties':{'ranking':{'type':'array','items':{'type':'integer','enum':ids},'minItems':len(ids),'maxItems':len(ids)}},'required':['ranking'],'additionalProperties':False}
    try:
        response = chat(RERANK_MODEL, (ROOT/'eval/prompts/reranker.txt').read_text(), prompt,schema=schema)
    except ValueError as e:
        return {str(cid):i for i,cid in enumerate(ids)}, {'error':str(e),'fallback':'hybrid'}
    ranking = response.get('ranking')
    if not isinstance(ranking, list) or any(type(i) is not int for i in ranking) or len(ranking) != len(ids) or set(ranking) != set(ids):
        # Production falls back to candidate order on invalid model output; measure that behavior.
        return {str(cid):i for i,cid in enumerate(ids)}, {'response':response,'error':'invalid permutation','fallback':'hybrid'}
    return {str(cid): i for i,cid in enumerate(ranking)}, response


def metrics(ranking, gold, chunks, k=5):
    # Rank chunks as in production, then deduplicate documents within the top-k window.
    docs = list(dict.fromkeys(chunks[str(i)]['doc_id'] for i in ranking[:k]))
    recall = len(set(docs)&set(gold))/len(gold)
    all_docs = list(dict.fromkeys(chunks[str(i)]['doc_id'] for i in ranking))
    mrr = next((1/(i+1) for i,d in enumerate(all_docs) if d in gold), 0)
    dcg = sum(1/math.log2(i+2) for i,d in enumerate(docs) if d in gold)
    ideal = sum(1/math.log2(i+2) for i in range(min(k, len(gold))))
    return {'recall@'+str(k): recall, 'mrr': mrr, 'ndcg@'+str(k): dcg/ideal}


def write_result(kind, data):
    out = ROOT/'eval/results'
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = out/f'{stamp}-{kind}.json'
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(path)
    return path
