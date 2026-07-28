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
> the cause — it is a CORS rejection, not a backend outage.

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

### `DAILY_TOKEN_CEILING` — set it deliberately

Defaults to 2,000,000 tokens/day, which on Haiku 4.5 is roughly $50–85/month at
the absolute worst case. With a $5 credit that default is far too high to be a
meaningful backstop. Something like:

```
DAILY_TOKEN_CEILING = 150000
```

is closer to a $5 budget (~$0.20/day worst case). Reaching it returns 503 until
the window rolls over. Set a spend alert in the Anthropic Console as well — the
in-app ceiling only stops what it can see.

---

## Everything else

**No new required variables.** Every other setting added in Phases 1–3 has a
working default (`RATE_LIMIT_ENABLED`, the per-IP quotas, `SESSION_RETENTION_DAYS`,
`AUDIO_MAX_BYTES`). Override them only if you want different numbers — see
`.env.example` for the full list.

**Port binding.** The container now binds `$PORT` rather than a hard-coded 8000.
Railway injects `PORT` and routes to it, so this is strictly more correct than
before and needs no configuration.

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
- [ ] Update the demo link at the top of `README.md`
