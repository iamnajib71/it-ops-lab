import json
import math
from pathlib import Path
import pytest
from eval.core import ROOT, metrics, questions, rank
from eval.run_answers import checks

def test_labels():
    qs=questions(); assert 60<=len(qs)<=100
    assert len({q['id'] for q in qs})==len(qs)
    assert sum(not q['gold_article_ids'] for q in qs)==10
    for q in qs:
        assert q['gold_answer'] and q['question']
        assert all((ROOT/'kb'/f'{d}.md').exists() for d in q['gold_article_ids'])

def test_multi_gold_metric_and_duplicates():
    chunks={'1':{'doc_id':'a'},'2':{'doc_id':'a'},'3':{'doc_id':'b'}}
    m=metrics([1,2,3],['a','b'],chunks,2)
    assert m['recall@2']==0.5
    assert m['mrr']==1
    assert m['ndcg@2']==pytest.approx(1/(1+1/math.log2(3)))
    assert metrics([3,1],['a'],chunks,1)['mrr']==0.5

def test_rrf_union_and_ties():
    assert rank([1,2],[2,3])['hybrid']==[2,1,3]
    assert rank([1,2],[2,3],{'1':0,'2':2,'3':1})['reranked']==[1,3,2]

def test_citation_and_abstention_checks():
    assert checks({'reply':'Do it [a#x]','citations':['a#x']},['a'],{'a#x':'Do it'})['cited_article_in_gold']
    assert not checks({'reply':'Do it [b#x]','citations':['b#x']},['a'],{'b#x':'Do it'})['cited_article_in_gold']
    assert not checks({'reply':'Guess something','abstained':True},[],{})['abstained']
    assert checks({'reply':'The KB does not cover this; a technician will follow up.','abstained':True,'citations':[]},[],{})['abstained']
    malformed={'reply':'The KB does not cover this; a technician will follow up.','abstained':True,'citations':['a#wrong']}
    result=checks(malformed,[],{'a#x':'Do it'})
    assert result['abstained'] and not result['citation_free_abstention']
    assert not result['citation_tags_retrieved']
    # Gold article membership and exact section validity measure different errors.
    assert checks({'reply':'Do it','citations':['a#invented']},['a'],{'a#x':'Do it'})['cited_article_in_gold']

def test_workflow_flag_and_evidence():
    from scripts.build_workflows import intake, SEARCH_SQL, RERANK_JS, GATE_JS, JUDGE_REQ_JS
    from scripts.build_workflows import RETRIEVE_JS
    assert "RAG_MEASURED" in RETRIEVE_JS and 'hybrid-fallback' in RERANK_JS
    assert 'THEN 20 ELSE 4' in SEARCH_SQL
    assert "$('Rerank KB')" in GATE_JS and "$('Rerank KB')" in JUDGE_REQ_JS
    assert intake['connections']['Hybrid search']['main'][0][0]['node']=='Rerank KB'

def test_input_hash_portability(tmp_path):
    from eval.core import digest
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    (a/'article.md').write_bytes(b'line one\r\nline two\r\n')
    (b/'article.md').write_bytes(b'line one\nline two\n')
    assert digest([a/'article.md'])==digest([b/'article.md'])
