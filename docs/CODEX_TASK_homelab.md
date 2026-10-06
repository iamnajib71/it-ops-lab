# Task for Codex: build and verify the homelab half of IT Ops Lab

Context: `H:\My Projects - IT\it-ops-lab` is a portfolio project for Nazmul Hassan, who is applying for ICT Support Engineer / Service Desk / IT Coordinator roles in Melbourne. It has two halves:
1. AI service-desk copilot (n8n + Postgres/pgvector + Ollama + Grafana). Claude is building this. **Do not edit**: `workflows/`, `db/`, `kb/`, `grafana/`, `scripts/ingest_kb.py`, `.env`.
2. A small-office homelab defined in `docker-compose.yml` under the `homelab` profile: `wireguard` (wg-easy), `fileserver` (dperson/samba), `printserver` (olbat/cupsd), `uptime` (uptime-kuma). **This is your part.**

Docker Desktop is running. Windows reserves TCP ports 2806-3223 and 5344-5443; do not use those. Secrets come from `.env` (already contains SMB_ALICE_PASSWORD, SMB_BOB_PASSWORD, WG_HOST; WG_PASSWORD_HASH is empty). Never print secret values into docs or logs.

## Deliverables
1. `homelab/cups/cupsd.conf`: CUPS config that listens on all interfaces, allows the LAN and the Docker network to print and to view `/`, `/jobs` and `/printers`, and keeps `/admin` restricted to the admin user.
2. `homelab/cups/setup-printers.sh`: idempotent script, run inside the printserver container, that creates:
   - `Office-PDF`: a virtual PDF printer (cups-pdf, or a file:/dev/null-style backend if cups-pdf is unavailable; say which in the runbook).
   - `Office-Laser`: an IPP Everywhere/generic queue pointing at a placeholder device URI. Mark it clearly as a simulated device.
   Then sets `Office-PDF` as the default.
3. Make the stack start cleanly with `docker compose --profile homelab up -d`. For wg-easy, generate a bcrypt `WG_PASSWORD_HASH` with the wg-easy image's own `wgpw` helper (`docker run --rm ghcr.io/wg-easy/wg-easy:14 wgpw <password>`), using a random password. Write the password to `.env` as `WG_ADMIN_PASSWORD=` and the hash as `WG_PASSWORD_HASH=` (escape `$` as `$$` for compose). Do not change other `.env` lines.
4. `tests/homelab_check.ps1` (PowerShell 5.1 compatible) that verifies and prints PASS/FAIL for:
   - all four containers running;
   - Samba: list shares and prove access control. Alice can write to Finance; bob gets access denied on Finance; both can use Public. Use `docker run --rm --network it-ops-lab_default` with a small smbclient image, or exec into the container.
   - CUPS: `lpstat -p -d` shows both queues; submit a test page to Office-PDF and show the job completes.
   - WireGuard: admin UI responds on 51821; create one peer via the wg-easy API (`POST /api/session`, then `POST /api/wireguard/client`); confirm it is listed; delete it again.
   - Uptime Kuma responds on 13001.
   Save a timestamped transcript to `docs/evidence/homelab-check-<date>.txt` with secrets redacted.
5. `docs/homelab-runbook.md`: an engineer-style runbook covering a network/architecture diagram (Mermaid), each service's purpose, ports and how to administer it, onboarding/offboarding a user (Samba user plus VPN peer), revoking a lost device, restoring a file, clearing a stuck print queue, adding monitors in Uptime Kuma (list the monitors to add: n8n :5678, Grafana :13000, Postgres :55432, Samba :1445, CUPS :6631, wg-easy :51821), backup approach, and security notes (least privilege, secrets in .env, no ports exposed to the internet). Keep the wording consistent with the user-facing KB articles in `kb/` (share names Public/Finance/Scans, queues Office-Laser/Office-PDF, VPN via WireGuard app).
6. Run the check script and fix issues until everything passes. Report what passed, what you changed, and anything you could not get working (with the error).

Constraints: no new public network exposure, no system or firewall setting changes, no global installs. Work only inside this project folder (and Docker). Be concise in the docs: an IT manager should be able to read the runbook in 5 minutes.
