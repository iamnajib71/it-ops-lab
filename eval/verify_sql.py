"""Check cached Python fusion against the production pgvector SQL function."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eval.core import questions, provenance, write_result
from eval.run_retrieval import FIXTURE, evaluate, sql
from scripts.ingest_kb import q

def main():
    fixture=json.loads(FIXTURE.read_text()); report=evaluate(fixture)
    values=','.join('('+q(row['id'])+','+q(row['question'])+','+q(json.dumps(fixture['queries'][row['id']]['embedding']))+'::vector)' for row in questions())
    query='WITH queries(qid,text,vec) AS (VALUES '+values+") SELECT json_object_agg(qid,ids) FROM (SELECT qid,(SELECT json_agg(id ORDER BY rrf DESC,id) FROM kb_hybrid_search(text,vec,20)) ids FROM queries) r"
    live=sql(query)
    for row in report['questions']:
        assert live[row['id']]==row['rankings']['hybrid'], f"SQL mismatch {row['id']}"
    write_result('sql-equivalence',{'provenance':provenance(),'checked':len(live),'passed':True,'rankings':live})
    print('Production SQL and cached fusion agree on',len(live),'questions')

if __name__=='__main__': main()
