---
name: Mongo persistence & deploy safety
description: Why local mongod must use a persistent dbPath, why autoscale needs managed Mongo, and a gotcha when restarting mongod from tests.
---

# Mongo persistence & deploy safety

## Local mongod must NOT use /tmp
- `start.sh` launches a local mongod only when `MONGO_URL` points at localhost/127.0.0.1, and uses a persistent dbPath under the repl (`.data/mongodb`), which is gitignored.
- **Why:** `/tmp` is wiped on container recycle, so a `/tmp` dbPath silently loses all user accounts/state between restarts — the original beta data-loss bug.
- **How to apply:** never point mongod's dbPath at `/tmp`. The startup health-check in `server.py on_startup` pings Mongo, logs a loud error if dbPath is under `/tmp`, and raises if Mongo is unreachable (fail loud, don't mask data loss).

## Any deployment needs managed Mongo (local mongod is dev-only)
- **Why:** a deployment runs from a *built image*, not the dev workspace, and the local mongod's dbPath (`.data/mongodb`) is gitignored — so it won't exist in the deployment and resets on every redeploy. Local mongod is dev-only, regardless of deploy target.
- **How to apply:** for production, provision managed Mongo (e.g. Atlas) and set `MONGO_URL` as a secret. start.sh already skips launching local mongod when `MONGO_URL` is external, so no code change is needed — just set the secret. server.py on_startup pings Mongo and refuses to boot if unreachable (fail loud).

## Deploy target is Reserved VM, single worker (not autoscale)
- **Why:** the app loads the full catalog into memory at startup and keeps in-memory caches (discover cache, refill locks). Autoscale (multi-instance + scale-to-zero) would reload the catalog per instance, diverge caches, and cold-start slowly. A single always-on VM with ONE uvicorn worker keeps one consistent in-memory state.
- **How to apply:** keep `deploymentTarget = vm` and a single-process uvicorn run command (no `--reload`, no multiple workers) until catalog/session state is externalized. In production FastAPI serves the built frontend + the API under `/api` on one port (single origin); the SPA catch-all must never shadow `/api`.

## Signing-secret removal can stay hidden until a process recycle
- JWT signing should prefer a dedicated production secret but remain startup-safe by falling back to an existing strong server-side session secret when the dedicated value is absent.
- **Why:** a deleted secret can remain inherited by an already-running development process, making development appear healthy while a newly recycled production VM fails at import and takes the entire API offline. The lost signing value cannot be reconstructed, so old tokens will require a one-time login.
- **How to apply:** keep signing values in Replit Secrets, never plaintext configuration. Validate signing configuration at startup, log fallback use clearly, and test a clean process with the preferred secret deliberately absent. Treat secret rotation or fallback activation as a session-invalidating event.

## Gotcha: mongod forked inside a bash/test call dies when the call ends
- The bash tool kills the command's process group on return, so a `mongod --fork` started inside a bash/test invocation is killed when that invocation finishes — even though `--fork` daemonizes. Only the workflow-owned mongod (child of the long-lived start.sh) is durable.
- **How to apply:** the restart-persistence test (`backend/tests/test_restart_persistence.py`) restarts mongod itself to prove persistence; that proof is valid *during* the run, but after it exits mongod is down. Always `restart_workflow "Start application"` after running it to restore a durable mongod. Source the test's swipe ids straight from `movies_cache` (catalog has thousands) — `/discover` is per-user limited by genre/provider filters + recently-shown cooldown (~40 max for one user), so it can't supply 50.

## Gotcha: Atlas "SSL handshake failed / tlsv1 alert internal error" = IP not allowlisted
- A `mongodb+srv://` connection to Atlas that fails with `ServerSelectionTimeoutError` + `SSL handshake failed: ...mongodb.net:27017: [SSL: TLSV1_ALERT_INTERNAL_ERROR]` is **not** a TLS/cert bug — Atlas's proxy aborts the handshake when the connecting IP is not in Network Access. Replit egress IPs are dynamic.
- **How to apply:** in Atlas → Network Access, add `0.0.0.0/0` (allow from anywhere; rely on user/pass + TLS) or the specific IPs. This is a user-side dashboard action — the agent cannot do it. Same fix needed for both the dev workspace and the deployed VM.

## Gotcha: VM deploy run-command port must match the externalPort 80 mapping
- Symptom: published VM app returns 502 "deployment could not be reached" (or proxy 500 on `/`) with NO Python traceback in deployment logs, while `/` works in dev. The app never receives the request.
- **Why:** the public URL (443/80) routes to whichever `[[ports]]` entry has `externalPort = 80`. Here that is `localPort 8000` (the dev backend port, exposeLocalhost). If the deploy `run` command binds a *different* port (it was `--port 5000`, which maps to the non-public externalPort 5000), the proxy forwards public traffic to 8000 where nothing listens → 502/500. Outbound work (e.g. TMDB import) still logs, masking that inbound never arrives.
- **How to apply:** bind the deployed app to the localPort mapped to `externalPort = 80` (here 8000), not whatever dev happens to use for the webview. Check `.replit` `[[ports]]` to find the externalPort-80 localPort, then set the deploy run port to match via deployConfig. Dev backend already runs on 8000, so prod on 8000 is consistent.

## Gotcha: rapid successive workflow restarts can leave mongod down with a stale lock
- Restarting the workflow several times in quick succession races: a dying mongod still matches `pgrep -x mongod`, so start.sh skips relaunch, then it exits leaving no mongod plus a stale `.data/mongodb/mongod.lock`.
- **How to apply:** if Mongo is "Connection refused" after restarts, `rm -f .data/mongodb/mongod.lock`, then `restart_workflow "Start application"` ONCE and poll `pgrep -x mongod` before testing.
