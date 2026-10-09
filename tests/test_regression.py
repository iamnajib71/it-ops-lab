"""Gate computed behavior, never trust summary numbers in a saved report."""
import json
from eval.core import ROOT, questions
from eval.run_retrieval import FIXTURE, evaluate
from eval.run_answers import checks, summarize

def test_measured_retrieval_regression():
    baseline=json.loads((ROOT/'eval/baseline.json').read_text())
    fixture=json.loads(FIXTURE.read_text())
    report=evaluate(fixture)
    score=report['summary']['dev'][baseline['selected_variant']]['recall@5']
    assert score>=baseline['min_recall@5'], f'Recall regression: {score}'

def test_measured_abstention_regression():
    baseline=json.loads((ROOT/'eval/baseline.json').read_text())
    answers=json.loads((ROOT/f"eval/fixtures/answers-{baseline['selected_variant']}.json").read_text())
    labels={q['id']:q for q in questions()}
    assert set(labels)=={r['id'] for r in answers['questions']}
    for row in answers['questions']:
        row['checks']=checks(row['answer'],labels[row['id']]['gold_article_ids'],row['context'])
    score=summarize(answers['questions'])['dev']['no_answer_abstention_accuracy']
    assert score>=baseline['min_abstention_accuracy'],f'Abstention regression: {score}'
