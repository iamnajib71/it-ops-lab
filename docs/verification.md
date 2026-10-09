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
