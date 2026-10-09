# Evaluation protocol

`questions.jsonl` contains 70 synthetic, KB-derived questions: 56 single-article
paraphrases (including five typo cases), four multi-article questions and ten
questions whose exact answer is absent. Labels and short reference answers were
written by reading each committed KB article. The reproducible authoring source
is `build_questions.py`; article stems are the stable IDs. The no-answer cases
include near misses (actual guest password and server IP), not only unrelated
products. No gold answers or article IDs enter retrieval or reranking.

Every third question is reserved as `test`; the others are `dev`. Configuration
selection and regression thresholds must use dev results only. The all/test
results remain descriptive, not an independent benchmark: this small authored
set is not blinded, not human-adjudicated and not sampled from real tickets.
Seven related questions per article introduce dependence. Scores are article
coverage, not proof that the correct troubleshooting section was retrieved.
Expanding this set and obtaining independent human labels are necessary before
any production claim. No confidential tickets are used.

## Retrieval

`python eval/run_retrieval.py --live` uses the actual Postgres English
`ts_rank_cd` keyword scores, Ollama `nomic-embed-text` vectors, RRF (constant 60,
20 candidates per branch), and a local `qwen2.5:3b` listwise LLM reranker of the
top 20 fused chunks. Ties use chunk ID, consistently for every variant.
The same reranker prompt and model options are used in n8n. Invalid permutations
are recorded and fall back to hybrid in both evaluation and the live workflow.

Recall@k measures the fraction of gold articles represented within the first k
**chunks**. Duplicate articles in that window count once. MRR uses the first
relevant article in the deduplicated full candidate ranking. nDCG@k uses binary
article relevance, deduplicates the top-k chunk window and normalizes by the ideal
gold article order. No-answer cases are excluded from retrieval means: empty gold
sets have undefined recall. Reports contain all, dev and held-out test means plus
every question's rankings, allowing audit of failures and multi-article coverage.

The fixture retains document/query embeddings, Postgres keyword order, raw LLM
ranking responses and latency. `python eval/run_retrieval.py` recomputes cosine,
RRF and metrics offline. Cached keyword ranks do not test SQL changes; cached
reranker responses do not test model drift. Refresh with `--live` after SQL/model
changes. Fixtures are rejected when KB, questions or prompts change.

## Answers

`python eval/run_answers.py --live --variant reranked` generates one local
qwen2.5 draft per question using four chunks, checks literal citations and gold
article membership, then uses local llama3.1 as a judge with the committed prompt
in `prompts/judge.txt`. This is a controlled single-draft answer experiment;
the production workflow separately arbitrates two drafts and applies its policy
gate. Citation checks measure provenance, not factual truth. The judge is also
fallible and has no human agreement/calibration study.

No-answer abstention accuracy requires an explicit refusal and `abstained=true`.
Citation-free abstention is a separate stricter metric: several real refusals
still emitted irrelevant citation metadata. Both are reported, alongside answerable response accuracy,
to expose a system that refuses everything. Judge faithfulness and judge-rated
abstention are separate signals, not substitutes for deterministic checks.
Cached answer replay reruns checks against saved real drafts, not a new generation.

Raw timestamped reports in `results/` carry model names, UTC time, commit,
dirty-tree status and SHA256 input hashes. A dirty run refers to the recorded
commit plus working changes and is explicitly identified. Never edit scores to
pass a gate. Keep historical reports when refreshing a baseline.

Live capture resumes completed local model calls when their inputs are unchanged.
After a SQL change it recaptures keyword ranks and only reuses reranking when
the candidate order is identical. Capture history preserves the earlier source
provenance. Delete `eval/fixtures/retrieval.json` (after preserving evidence) to
force fresh model calls for a model drift study; cached CI cannot detect drift.
