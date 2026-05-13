# VPS-2 API — `api.skulltrading.com`

FastAPI service that the iOS app talks to. Hosted on the dedicated
Infomaniak VPS-2; never on VPS-1 (which keeps running the personal bot
in isolation).

## Responsibilities

- Validate Supabase JWTs and resolve the user's current tier.
- Serve cached signals + Gekko analyses (tier-gated).
- Proxy specific endpoints to VPS-1 (`/crypto-score`, `/leverage-calc`,
  `/backtest`).
- Receive `POST /internal/signal-webhook` from VPS-1, persist to
  `signal_cache`, trigger the Supabase `notify-subscribers` Edge Function.
- Expose `/metrics` for Prometheus, `/health` for the load balancer.
- Per-user rate limiting via Redis.

## Layout

```
app/
  main.py                    FastAPI app entrypoint + lifespan
  core/
    config.py                Pydantic settings (env vars)
    auth.py                  JWT verification via JWKS
    tier_auth.py             Tier-based dependency
    rate_limit.py            Redis token-bucket
    db.py                    asyncpg pool for local Postgres
    metrics.py               Prometheus instrumentation
  models/
    signals.py               Pydantic models for the public API
    webhooks.py              Internal webhook payload model
  services/
    vps1_client.py           HTTPX client to VPS-1 (service token)
    supabase_client.py       HTTPX client to Supabase Edge Functions
    cache.py                 signal_cache CRUD
  routers/
    health.py                /health, /metrics
    v2_signals.py            /api/v2/signals*
    v2_gekko.py              /api/v2/gekko/*
    v2_prices.py             /api/v2/prices/*
    v2_tools.py              /api/v2/leverage-calc, /backtest, /crypto-score
    internal.py              /internal/signal-webhook
migrations/
  001_signal_cache.sql       Local schema for the cache table
tests/
  test_health.py
  test_jwt.py
  test_internal_webhook.py
Dockerfile
docker-compose.yml
pyproject.toml
.env.example
```

## Local dev

```bash
cd vps2-api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # then fill in dev values
docker compose up -d postgres redis
psql "$DATABASE_URL" -f migrations/001_signal_cache.sql
uvicorn app.main:app --reload --port 8000
```

## Tests

```bash
pytest -v
```
