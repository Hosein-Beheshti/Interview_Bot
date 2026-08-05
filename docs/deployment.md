# Deployment (Railway)

Three services in one Railway project, unchanged from the original setup:

| Service | What | Source |
|---|---|---|
| **Postgres** | database + pgvector | Railway's pgvector template |
| **backend** | FastAPI API | `backend/Dockerfile` |
| **frontend** | React behind nginx | `frontend/Dockerfile` |

There is no `railway.json` — the services are configured in the dashboard, which
is how they were set up originally. Nothing here changes that.

---

## What Phases 1–3 changed that Railway needs

The hardening work altered two defaults that were previously permissive. **On the
next redeploy the app will not work correctly until both are set**, so do these
before or immediately after pushing.

### `CORS_ORIGINS` — required, or the frontend is blocked

CORS used to be hard-coded to `*`. It now defaults to localhost only, because a
public API that accepts requests from any origin is exactly what you don't want
once there are rate limits and a spend ceiling worth bypassing.

On the **backend** service:

```
CORS_ORIGINS = https://YOUR-FRONTEND.up.railway.app
```

Comma-separate for more than one origin. If you later add a custom domain, it
goes here too.

> If the UI starts showing "Cannot reach the server" after this deploy, this is
> a likely cause. Confirm it before acting on it: a browser reports a genuine
> backend outage with the same missing-`Access-Control-Allow-Origin` message,
> because a request that never reached the app has no CORS header on it either.
> `curl -i https://YOUR-BACKEND.up.railway.app/health` settles which one it is —
> fix the backend first if that isn't a 200.

Railway auto-injects `RAILWAY_ENVIRONMENT` into every deploy. On boot, the app
checks that variable and logs a `CRITICAL` line (without refusing to start) if
`CORS_ORIGINS` is still the localhost default or `*` while it's set — a safety
net for exactly this "forgot to set it" case. Watch the deploy logs for that
line after a fresh deploy.

### `TRUST_PROXY_HEADERS` — required, or rate limits collapse

Railway terminates TLS in front of your container, so every request arrives with
the proxy's address as its socket peer. Without this, all visitors share a single
rate-limit bucket and the first person to hit the limit locks out everyone else.

On the **backend** service:

```
TRUST_PROXY_HEADERS = true
```

It is safe here *because* a proxy is guaranteed to be in front. It must stay
`false` anywhere the container is directly reachable, since the header is
caller-supplied and otherwise lets anyone reset their own limit.

### `DAILY_TOKEN_CEILING` — already safe by default

Defaults to **150,000 tokens/day**: roughly $0.20/day on Haiku 4.5, or about
20–30 full interviews. That is sized for a $5 credit, so no action is needed —
the default fails toward a small bill rather than an unbounded one. Reaching it
returns 503 until the window rolls over.

Raise it once you know what real traffic actually costs:

```
DAILY_TOKEN_CEILING = 500000
```

**Set a spend alert in the [Anthropic Console](https://console.anthropic.com)
regardless.** The in-app ceiling only counts what this application spends —
anything else on the same API key is invisible to it, and a bug in the metering
path would be invisible too. Two independent backstops, one of which does not
depend on your own code being correct.

Optionally, set `ALERT_WEBHOOK_URL` to a Slack incoming-webhook (or Discord, or
anything accepting a JSON `{"text": ...}` POST) to get notified the first time
the ceiling is actually hit on a given day, instead of finding out from the
console at the end of the week. It fires at most once per UTC day and never
blocks a request — a failed or unconfigured webhook is logged and ignored.

---

## Everything else

**No new required variables.** Every other setting added in Phases 1–3 has a
working default (`RATE_LIMIT_ENABLED`, the per-IP quotas, `SESSION_RETENTION_DAYS`,
`AUDIO_MAX_BYTES`). Override them only if you want different numbers — see
`.env.example` for the full list.

**Port binding — verify this one, it is not automatic.** The container binds
`$PORT` (falling back to 8000), which is portable across platforms. But Railway
tracks the *target port* for the public domain separately, in **Settings →
Networking**, and it does not follow the `PORT` it injects. If the injected
`PORT` is 8080 while the target port is still 8000, every request returns a
`502 Application failed to respond` from `railway-hikari` while the container
logs look perfectly healthy — and because nothing answers, no CORS header is
attached either, so the browser blames CORS. Do not chase that; check the port.

The container's log line states the port it actually bound:

```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Make that number equal the target port. Pinning `PORT` on the service is the
tidier of the two fixes, since it also matches the Dockerfile's `EXPOSE 8000`:

```
PORT = 8000
```

**Schema migrations run themselves** on boot, inside one advisory-locked
transaction (`persistence/schema.py`). This deploy adds a `usage_counters` table
and converts the existing timestamp columns to `timestamptz`. The conversion is
guarded so it runs exactly once; re-running it on already-converted columns would
shift the stored instants, which is why it checks the column type first.

**pgvector** is already enabled on your existing Postgres service — no change.

---

## Retention sweep

`.github/workflows/retention.yml` runs the purge daily via GitHub Actions. Add a
repository secret `DATABASE_URL` (GitHub → Settings → Secrets and variables →
Actions) with your Railway Postgres connection string.

Railway's own cron would work equally well; GitHub Actions is used because it is
free and platform-independent. Verify it without deleting anything: Actions →
retention-sweep → Run workflow, leaving "dry run" checked.

---

## Backup and restore

Session transcripts, per-answer scores, and uploaded CV text/embeddings live in
one Postgres instance with no automatic redundancy beyond Railway's own volume.
Check what your plan actually provides before assuming a safety net exists:
**Postgres service → Settings → Backups** in the Railway dashboard. If that
tier doesn't include backups, the manual procedure below is your only recovery
path, not a supplement to one.

**Backup** — `pg_dump` against the same `DATABASE_URL` already used as the
GitHub Actions secret for the retention workflow, so there's no new credential
to manage:

```sh
pg_dump "$DATABASE_URL" --format=custom --file="backup-$(date +%F).dump"
```

`--format=custom` captures `pgvector` *usage* (the `vector` columns and their
data) but not the extension's *installation*. Restoring into a fresh database
needs the extension created first — the same step `persistence/schema.py`
already performs on every boot, so this only matters if you restore outside
that boot path:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**Restore**:

```sh
pg_restore --clean --if-exists --dbname="$DATABASE_URL" backup-2026-08-05.dump
```

Point the backend's `DATABASE_URL` at the restored database and redeploy so
`persistence/migrations.py` runs its forward-only migrations against whatever
schema state the dump captured. Verify with `curl .../health/ready` returning
200 as the acceptance check — it's the endpoint that actually queries Postgres.

**Interaction with `SESSION_RETENTION_DAYS`.** A restore can reintroduce
personal data — CVs, transcripts — that the retention sweep already purged, if
the backup predates that purge. Run `scripts/purge_expired.py` again
immediately after any restore to reconcile. For the same reason, don't keep
backup dumps around much longer than `SESSION_RETENTION_DAYS` — otherwise the
backup archive quietly becomes the real data-retention boundary, undermining
the number configured everywhere else.

**Where dumps live.** Not this repo, and not a long-lived GitHub Actions
artifact — these are personal data from people trying a public demo. Use a
private, access-controlled store (encrypted local disk, a private bucket) and
apply the same retention discipline to it as above; the specific choice is
yours to make, not something this doc can decide for you.

---

## Cost note

Three always-on services (Postgres, backend, frontend) all bill continuously on
Railway's usage model. A $5 credit is tight for three containers running 24/7 —
watch the usage graph in the first week rather than assuming it fits.

The cheapest lever, if it doesn't: move the **frontend** to Cloudflare Pages,
which is free and unmetered for static sites. That drops Railway to two services
and changes nothing about the architecture — the frontend is a static bundle
either way, and `VITE_API_URL` already points it at the backend's public URL.

---

## Verify after deploying

```sh
curl https://YOUR-BACKEND.up.railway.app/health        # {"status":"ok"}
curl https://YOUR-BACKEND.up.railway.app/health/ready  # {"status":"ready"}
```

`/health` is deliberately dependency-free so a database blip cannot make the
platform restart a container that is otherwise serving. `/health/ready` is the
one that actually checks Postgres — point any uptime monitor at that one.

Then in the browser:

- [ ] Run a full interview — the reply should stream in word by word, and the
      score for your previous answer should appear *before* the next question
      finishes writing
- [ ] Upload a CV, confirm questions reference it, then use **Delete my
      transcript and CV** and confirm it is gone
