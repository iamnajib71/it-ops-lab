"""Explicit baseline update from completed live dev measurements only."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eval.core import ROOT

def main():
    retrieval=json.loads(Path(sys.argv[1]).read_text())
    answers=json.loads(Path(sys.argv[2]).read_text())
    if retrieval['mode']!='live' or answers['mode']!='live': raise ValueError('Baseline requires live results')
    dev=retrieval['summary']['dev']
    winner=max(dev,key=lambda v:(dev[v]['recall@5'],dev[v]['mrr'],dev[v]['ndcg@5']))
    # The rollout decision can retain hybrid if reranking does not win.
    chosen='reranked' if winner=='reranked' else winner
    if answers['variant']!=chosen: raise ValueError(f'Run answer evaluation for measured winner {chosen}')
    baseline={'retrieval_report':Path(sys.argv[1]).relative_to(ROOT).as_posix(),
      'answer_report':Path(sys.argv[2]).relative_to(ROOT).as_posix(), 'selected_variant':chosen,
      'selection':'dev recall@5, then MRR, then nDCG; ties prefer earlier simpler variant',
      'dev_recall@5':dev[chosen]['recall@5'],
      'dev_abstention_accuracy':answers['summary']['dev']['no_answer_abstention_accuracy'],
      'min_recall@5':max(0,dev[chosen]['recall@5']-0.02),
      'min_abstention_accuracy':answers['summary']['dev']['no_answer_abstention_accuracy'],
      'policy':'At most 2 percentage points recall loss; no lost dev no-answer refusals. Small set, explicit baseline review required.'}
    (ROOT/'eval/baseline.json').write_text(json.dumps(baseline,indent=2)+'\n')
    print(json.dumps(baseline,indent=2))

if __name__=='__main__': main()
