# Raw evidence history

Reports are immutable observations, including early working-tree measurements.
The final v2 answer protocol separates article membership from exact section tag
validity, and explicit refusal from citation-free refusal. The initial
`20261009T125807Z-answers.json` report used the stricter, conflated v1 checks.
It is kept for audit, not used for the final baseline. V2 rescored the exact same
saved drafts and judge responses; no model output or labels were changed.

Fixture hash migrations verify the original input byte hashes, then canonicalize
CRLF/LF for portable clean-clone and Windows CI replay. Original provenance is
preserved under `hash_migrations`. This changes neither embeddings nor outputs.
Later live capture resumes calls with identical inputs, recaptures changed SQL
rankings, and retains capture history. Commit hash plus `dirty=true` identifies
pre-commit measurements; source input hashes and all raw outputs remain available.
