## v1.0.0

- Local n8n service-desk copilot with two drafts, a judge and human approval rules.
- 70 labelled KB questions, including typos, multi-article cases and ten no-answer cases.
- Measured keyword, vector, RRF and local LLM reranking; raw results and model provenance retained.
- Keyword coverage winner behind a feature flag; original hybrid path and experimental reranker available.
- Citation, faithfulness and abstention evaluation plus baseline-derived Windows CI regression gates.
- Windows setup, real 68-second demo GIF, MIT licence and clean-clone verification.

Reranking hurt this small synthetic benchmark. The local judge is fallible, citation
format compliance is weak, and abstention is incomplete. Runs locally; fictional
data only. This is evaluation evidence, not a production correctness guarantee.
