# Clean-clone verification

The README PowerShell quick-start commands passed on Windows with Python 3.14.3
and pytest 8.4.2 from a fresh checkout of `4131466`, before the first push of the
measured pipeline. Docker project `it-ops-lab-verify-fixed` created new Postgres
and n8n volumes and generated new local credentials; no `.env` or database was
copied from the development lab. The three `ollama pull` commands reused locally
cached model weights. The application and evaluation use local models only.

- All six demo tickets routed to their expected queues.
- Cached retrieval reproduced the committed four-way comparison.
- All eight pytest unit/regression tests passed (0.31 seconds in that run).
- Workflow regeneration produced no Git diff in a clean Windows checkout.

The first clean-start attempt exposed a readiness race: n8n's HTTP health endpoint
was available before its ticket webhook was registered. `setup_lab.py` now waits
for readiness and the published POST ticket webhook. The full fresh-start run
above passed with that fix. Raw replay evidence is retained in
`eval/results/20261009T131313Z-retrieval.json`.

The real demo GIF is 67.97 seconds, with output recorded by `scripts/record_demo.py`
in asciinema v2 format and rendered with agg 1.9.0. Its source recording and
actual elapsed-time metadata are committed alongside the GIF.

## Published GitHub clone

The final check cloned `https://github.com/iamnajib71/it-ops-lab.git` at `b1d7fa5`
into another temp folder and followed every README quick-start command with fresh
`it-ops-lab-final` Docker volumes. All six tickets passed, retrieval metrics matched,
and all eight tests passed (0.31 seconds). Raw replay is retained in
`eval/results/20261009T131845Z-retrieval.json`.

After that check, two additional fictional webhook tickets exercised
`RAG_MEASURED=on`, `RAG_VARIANT=reranked`: scanner location and Finance folder.
Both returned `retrieval_mode=reranked`, proving the real local reranker branch
ran. Full responses are in `eval/results/20261009T132128Z-reranker-integration.json`.
This smoke check does not replace the 70-question benchmark or promote the reranker.
