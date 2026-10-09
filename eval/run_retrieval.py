"""Live Postgres/Ollama measurement or offline fixture replay."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.core import ROOT, VARIANTS, cosine, embed, metrics, model_manifest, provenance, questions, rank, rerank, write_result
from scripts.ingest_kb import load_env, q

FIXTURE = ROOT/'eval/fixtures/retrieval.json'

def sql(query):
    env = load_env()
    p = subprocess.run(['docker','compose','exec','-T','postgres','psql','-X','-At','-v','ON_ERROR_STOP=1',
                        '-U',env['PG_USER'],'-d',env['PG_DB']],input=query+';\n',cwd=ROOT,text=True,capture_output=True,check=True)
    return json.loads(p.stdout)

def capture():
    chunks = sql("SELECT json_agg(x ORDER BY id) FROM (SELECT id,doc_id,title,coalesce(section,'') section,content,embedding::text FROM kb_chunks) x")
    by_id = {str(c['id']):c for c in chunks}
    for c in chunks: c['embedding'] = json.loads(c['embedding'])
    fixture = {'provenance':provenance(),'models':{'embedding':'nomic-embed-text','reranker':'qwen2.5:3b'},'runtime':model_manifest(),'chunks':by_id,'queries':{}}
    # Resume completed expensive queries only when inputs match.
    if FIXTURE.exists():
        prior=json.loads(FIXTURE.read_text())
        if prior.get('runtime')==fixture['runtime'] and all(prior['provenance'].get(k)==fixture['provenance'][k] for k in ('kb_sha256','questions_sha256','prompts_sha256')):
            fixture['queries']=prior['queries']
            fixture['capture_history']=prior.get('capture_history',[])+[prior['provenance']]
            fixture['hash_migrations']=prior.get('hash_migrations',[])
            if prior['provenance'].get('sql_sha256')!=fixture['provenance']['sql_sha256']:
                for item in questions():
                    if item['id'] not in fixture['queries']: continue
                    query=item['question']
                    kw=sql("WITH tq AS (SELECT to_tsquery('english',nullif(array_to_string(tsvector_to_array(to_tsvector('english',"+q(query)+")), ' | '),'')) q) SELECT coalesce(json_agg(id),'[]') FROM (SELECT id FROM kb_chunks,tq WHERE tq.q IS NOT NULL AND tsv @@ tq.q ORDER BY ts_rank_cd(tsv,tq.q) DESC,id LIMIT 20) r")
                    if kw!=fixture['queries'][item['id']]['keyword']:
                        del fixture['queries'][item['id']]
                print('SQL refreshed; reused identical model inputs only',flush=True)
    for item in questions():
        if item['id'] in fixture['queries']: continue
        start=time.perf_counter(); query=item['question']; v=embed(query)
        kw = sql("WITH tq AS (SELECT to_tsquery('english',nullif(array_to_string(tsvector_to_array(to_tsvector('english',"+q(query)+")), ' | '),'')) q) SELECT coalesce(json_agg(id),'[]') FROM (SELECT id FROM kb_chunks,tq WHERE tq.q IS NOT NULL AND tsv @@ tq.q ORDER BY ts_rank_cd(tsv,tq.q) DESC,id LIMIT 20) r")
        vec=sorted((c['id'] for c in chunks),key=lambda cid:(-cosine(v,by_id[str(cid)]['embedding']),cid))[:20]
        hybrid=rank(kw,vec)['hybrid']
        fixture['queries'][item['id']]={'embedding':v,'keyword':kw,'embedding_keyword_latency_s':time.perf_counter()-start}
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(fixture),encoding='utf-8')
        print('embedded',item['id'], f'{time.perf_counter()-start:.1f}s',flush=True)
    for item in questions():
        f=fixture['queries'][item['id']]
        if 'reranker_scores' in f: continue
        start=time.perf_counter()
        vec=sorted((c['id'] for c in chunks),key=lambda cid:(-cosine(f['embedding'],by_id[str(cid)]['embedding']),cid))[:20]
        hybrid=rank(f['keyword'],vec)['hybrid']
        candidates=[{k:by_id[str(cid)][k] for k in ('id','doc_id','section','content')} for cid in hybrid[:20]]
        scores,response=rerank(item['question'],candidates)
        f.update(reranker_scores=scores,reranker_response=response,reranker_latency_s=time.perf_counter()-start)
        FIXTURE.write_text(json.dumps(fixture),encoding='utf-8')
        print('reranked',item['id'],f'{time.perf_counter()-start:.1f}s',flush=True)
    fixture['completed_utc']=provenance()['utc']
    FIXTURE.write_text(json.dumps(fixture),encoding='utf-8')
    return fixture

def evaluate(fixture,k=5):
    p=provenance()
    for key in ('kb_sha256','questions_sha256','prompts_sha256','sql_sha256'):
        if fixture['provenance'][key]!=p[key]: raise ValueError('Stale fixture: '+key)
    rows=[]
    for item in questions():
        f=fixture['queries'][item['id']]; chunks=fixture['chunks']
        vec=sorted((int(cid) for cid in chunks),key=lambda cid:(-cosine(f['embedding'],chunks[str(cid)]['embedding']),cid))[:20]
        rankings=rank(f['keyword'],vec,f['reranker_scores'])
        rows.append({'id':item['id'],'split':item['split'],'gold':item['gold_article_ids'],'rankings':rankings,
                     'metrics':{v:metrics(r,item['gold_article_ids'],chunks,k) for v,r in rankings.items()} if item['gold_article_ids'] else {}})
    summary={}
    for split in ('all','dev','test'):
        eligible=[r for r in rows if r['gold'] and (split=='all' or r['split']==split)]
        summary[split]={v:{m:sum(r['metrics'][v][m] for r in eligible)/len(eligible) for m in ('recall@'+str(k),'mrr','ndcg@'+str(k))} for v in VARIANTS}
    return {'provenance':p,'fixture_provenance':fixture['provenance'],'fixture_completed_utc':fixture.get('completed_utc'),'mode':'cached replay','models':fixture['models'],
            'runtime':fixture.get('runtime',{}),'reranker_fallback_count':sum('error' in f['reranker_response'] for f in fixture['queries'].values()),
            'k':k,'summary':summary,'questions':rows}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--live',action='store_true'); parser.add_argument('--k',type=int,default=5)
    parser.add_argument('--summary',action='store_true',help='Print a compact comparison table')
    args=parser.parse_args()
    fixture=capture() if args.live else json.loads(FIXTURE.read_text())
    result=evaluate(fixture,args.k); result['mode']='live' if args.live else 'cached replay'
    write_result('retrieval',result)
    if args.summary:
        print(f"{'Variant':12} {'Recall@'+str(args.k):>10} {'MRR':>10} {'nDCG@'+str(args.k):>10}")
        for name,m in result['summary']['all'].items():
            print(f"{name:12} {m['recall@'+str(args.k)]:10.4f} {m['mrr']:10.4f} {m['ndcg@'+str(args.k)]:10.4f}")
        print('60 answerable questions; 10 no-answer cases scored separately.')
        print('Reranker invalid-output fallbacks:',result['reranker_fallback_count'])
    else: print(json.dumps(result['summary'],indent=2))

if __name__=='__main__': main()
