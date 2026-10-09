"""Answer generation, deterministic citation checks, then local LLM judge."""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eval.core import ROOT, chat, model_manifest, provenance, questions, write_result
from eval.run_retrieval import FIXTURE, evaluate

SYSTEM = '''You are an IT service desk analyst. Use ONLY supplied KB sections, and only instructions relevant to the question. Cite each instruction using [doc_id#section]. If the KB does not answer the exact question, say "The KB does not cover this; a technician will follow up." Do not guess. Return JSON {"reply": "...", "citations": ["doc_id#section"], "abstained": true|false}. Keep the reply under 140 words.'''

def checks(answer,gold,context):
    reply=answer.get('reply',''); citations=answer.get('citations',[])
    present=bool(citations) and all('['+c+']' in reply for c in citations)
    valid=bool(citations) and all(c.split('#')[0] in gold for c in citations)
    tags_valid=bool(citations) and all(c in context for c in citations)
    abstained=answer.get('abstained') is True and bool(re.search(r'(does not cover|not covered|cannot answer|no information|not specified|not in (?:the )?KB)',reply,re.I))
    return {'citation_present':present,'cited_article_in_gold':valid,'citation_tags_retrieved':tags_valid,
            'abstained':abstained,'citation_free_abstention':abstained and not citations}

def summarize(rows):
    out={}
    for split in ('all','dev','test'):
        rs=[r for r in rows if split=='all' or r['split']==split]
        yes=[r for r in rs if r['gold']]; no=[r for r in rs if not r['gold']]
        out[split]={'citation_present':sum(r['checks']['citation_present'] for r in yes)/len(yes),
          'cited_article_in_gold':sum(r['checks']['cited_article_in_gold'] for r in yes)/len(yes),
          'citation_tags_retrieved':sum(r['checks']['citation_tags_retrieved'] for r in yes)/len(yes),
          'judge_faithfulness':sum(r['judge']['faithful'] is True for r in yes)/len(yes),
          'no_answer_abstention_accuracy':sum(r['checks']['abstained'] for r in no)/len(no),
          'citation_free_abstention_accuracy':sum(r['checks']['citation_free_abstention'] for r in no)/len(no),
          'answerable_response_accuracy':sum(not r['checks']['abstained'] for r in yes)/len(yes),
          'judge_abstention_accuracy':sum(r['judge']['abstained'] is True for r in no)/len(no)}
    return out

def main():
    p=argparse.ArgumentParser(); p.add_argument('--live',action='store_true'); p.add_argument('--variant',choices=['keyword','vector','hybrid','reranked'],default='reranked'); args=p.parse_args()
    fixture=json.loads(FIXTURE.read_text()); retrieval=evaluate(fixture)
    cache=ROOT/f'eval/fixtures/answers-{args.variant}.json'
    if not args.live:
        result=json.loads(cache.read_text())
        for key in ('kb_sha256','questions_sha256','prompts_sha256'):
            if result['provenance'][key]!=provenance()[key]: raise ValueError('Stale answers: '+key)
        labels={q['id']:q for q in questions()}
        if set(labels)!={r['id'] for r in result['questions']}: raise ValueError('Incomplete answer fixture')
        for row in result['questions']:
            row['checks']=checks(row['answer'],labels[row['id']]['gold_article_ids'],row['context'])
        result['summary']=summarize(result['questions']); result['mode']='cached checks replay'
    else:
        result={'provenance':provenance(),'mode':'live','variant':args.variant,'metric_protocol':'v2: article membership separate from exact tags; explicit refusal separate from citation-free refusal',
                'models':{'answer':'qwen2.5:3b','judge':'llama3.1:8b'},'runtime':model_manifest(),'questions':[]}
        if cache.exists():
            prior=json.loads(cache.read_text())
            if prior.get('runtime')==result['runtime'] and all(prior['provenance'][k]==result['provenance'][k] for k in ('kb_sha256','questions_sha256','prompts_sha256','sql_sha256')):
                result['questions']=prior['questions']
                result['source_capture_history']=prior.get('source_capture_history',[])+[prior['provenance']]
                result['hash_migrations']=prior.get('hash_migrations',[])
        completed={r['id'] for r in result['questions']}
        for item,row in zip(questions(),retrieval['questions']):
            if item['id'] in completed: continue
            cs=[fixture['chunks'][str(cid)] for cid in row['rankings'][args.variant][:4]]
            context={c['doc_id']+'#'+c['section']:c['content'] for c in cs}
            answer=chat('qwen2.5:3b',SYSTEM,json.dumps({'question':item['question'],'evidence':context}))
            simple=checks(answer,item['gold_article_ids'],context)
            result['questions'].append({'id':item['id'],'split':item['split'],'gold':item['gold_article_ids'],'context':context,'answer':answer,'checks':simple})
            cache.write_text(json.dumps(result,indent=2),encoding='utf-8'); print('draft',item['id'],simple,flush=True)
        labels={q['id']:q for q in questions()}
        for row in result['questions']:
            if 'judge' in row: continue
            item=labels[row['id']]
            judge=chat('llama3.1:8b',(ROOT/'eval/prompts/judge.txt').read_text(),json.dumps({'question':item['question'],'reference':item['gold_answer'],'evidence':row['context'],'answer':row['answer']}))
            if any(type(judge.get(k)) is not bool for k in ('faithful','abstained')): raise ValueError('Invalid judge response')
            row['judge']=judge
            cache.write_text(json.dumps(result,indent=2),encoding='utf-8'); print('judge',item['id'],judge,flush=True)
        for row in result['questions']:
            row['checks']=checks(row['answer'],labels[row['id']]['gold_article_ids'],row['context'])
        result['summary']=summarize(result['questions']); cache.write_text(json.dumps(result,indent=2),encoding='utf-8')
    write_result('answers',result); print(json.dumps(result['summary'],indent=2))

if __name__=='__main__': main()
