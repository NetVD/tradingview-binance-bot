# Backend V2 — Environment variables and secrets

This document is the single source of truth for the secrets and config
needed by every backend component of SkullTrading iOS.

Three locations hold secrets:

1. **Supabase project secrets** — consumed by Edge Functions.
2. **VPS-2 `.env`** — consumed by the FastAPI service on `api.skulltrading.com`.
3. **VPS-1 `.env`** — consumed by the existing bot (only the webhook bits are new).

The same `SERVICE_TOKEN` value is shared between VPS-1 and VPS-2.

---

## 1. Supabase secrets (Edge Functions)

Set via `supabase secrets set KEY=value` or in the dashboard
(Settings → Edge Functions → Secrets).

| Key | Purpose | Example / How to obtain |
|-----|---------|-------------------------|
| `SUPABASE_URL` | Project URL. Auto-injected by Supabase, no need to set. | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | Anon key. Auto-injected. | from dashboard |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role. Auto-injected. | from dashboard |
| `BINANCE_BASE_URL` | Binance Futures endpoint. | `https://fapi.binance.com` (prod) / `https://testnet.binancefuture.com` (sandbox) |
| `APNS_TEAM_ID` | Apple Developer Team ID. | Apple Developer → Membership |
| `APNS_KEY_ID` | APNS auth key ID. | Apple Developer → Keys |
| `APNS_BUNDLE_ID` | iOS app bundle id. | `com.skulltrading.app` |
| `APNS_AUTH_KEY_P8` | Contents of the `.p8` private key (PEM). | Apple Developer → Keys → Download |
| `APNS_USE_SANDBOX` | `"true"` for TestFlight, `"false"` for prod. | self |
| `SERVICE_TOKEN` | Shared secret with VPS-1 and VPS-2. | `openssl rand -hex 32` |

---

## 2. VPS-2 `/etc/skulltrading-app/.env`

The FastAPI service reads these on boot. Permissions: `chmod 600` and owned
by the dedicated service user.

| Key | Purpose | Example |
|-----|---------|---------|
| `APP_ENV` | `production` / `staging` / `development`. | `production` |
| `BIND_HOST` | Interface to bind to. | `127.0.0.1` (behind Caddy/Nginx) |
| `BIND_PORT` | Listening port. | `8000` |
| `DATABASE_URL` | Local Postgres on VPS-2 for `signal_cache`. | `postgresql+asyncpg://skull:...@localhost:5432/skulltrading_app` |
| `REDIS_URL` | Local Redis for rate limiting. | `redis://localhost:6379/0` |
| `SUPABASE_URL` | Same project as Edge Functions. | `https://<ref>.supabase.co` |
| `SUPABASE_JWT_JWKS_URL` | JWKS endpoint for JWT verification. | `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` |
| `SUPABASE_JWT_ISSUER` | Issuer claim to validate. | `https://<ref>.supabase.co/auth/v1` |
| `SUPABASE_JWT_AUDIENCE` | Audience claim to validate. | `authenticated` |
| `SUPABASE_SERVICE_KEY` | Used to call Edge Functions admin-style. | from Supabase dashboard |
| `VPS1_BASE_URL` | Internal URL of VPS-1. | `https://dashboard.skulltrading.com` |
| `SERVICE_TOKEN` | Shared with VPS-1 + Supabase. | same value |
| `RATE_LIMIT_PER_MINUTE` | Per-user rate cap. | `100` |
| `LOG_LEVEL` | `info` / `debug` / `warning`. | `info` |
| `SENTRY_DSN` | Crash reporting (optional). | `https://...@sentry.io/...` |
| `ALLOWED_ORIGINS` | CORS allow-list (mostly empty in prod — only iOS app calls). | `https://app.skulltrading.com` |
| `NOTIFY_FN_URL` | Full URL to the `notify-subscribers` Edge Function. | `https://<ref>.functions.supabase.co/notify-subscribers` |

---

## 3. VPS-1 `.env` additions (existing project)

Only two new lines need to be added to the existing bot's environment.
**Do not rename or remove any existing variable.**

| Key | Purpose | Example |
|-----|---------|---------|
| `APP_VPS_WEBHOOK_URL` | Where to POST the webhook when Gekko emits a STRONG_GO/GO. | `https://api.skulltrading.com/internal/signal-webhook` |
| `SERVICE_TOKEN` | Shared with VPS-2 and Supabase. | same value as elsewhere |

---

## 4. iOS app config (Info.plist / xcconfig)

Build-time, not secrets per se — the values are public anyway since they
end up in the binary.

| Key | Purpose | Example |
|-----|---------|---------|
| `SUPABASE_URL` | Same as everywhere. | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | The anon key (public, safe to embed). | from dashboard |
| `API_V2_BASE_URL` | VPS-2 endpoint. | `https://api.skulltrading.com` |
| `REVENUECAT_API_KEY` | Public RevenueCat key (iOS). | from RevenueCat dashboard |
| `APNS_ENVIRONMENT` | `sandbox` or `production`. | matches build configuration |

---

## 5. Rotating the master encryption key

The `binance_credentials` table records the `key_id` used for each row.
To rotate:

1. Provision a new pgsodium key: `SELECT pgsodium.create_key(name := 'binance_creds_v2', key_type := 'aead-det'::pgsodium.key_type);`
2. Update `migrations/004_vault_setup.sql` to point both helpers at `binance_creds_v2`.
3. Run a one-off migration that, for each row, decrypts with the old key
   and re-encrypts with the new one. (Edge Function service_role only.)
4. Once all rows have `key_id = <new>`, soft-delete the old key
   (do not hard-delete — older logs may still reference it).

The rotation script is intentionally not committed; design it as a one-shot
SQL function inside a migration when you actually need to rotate.

---

## 6. Local development

For local Supabase development with `supabase start`:

```bash
supabase start          # spins up local Supabase stack
supabase db reset       # applies all migrations on the local DB
supabase functions serve binance-connect --env-file ./supabase/functions/.env.local
```

Create `supabase/functions/.env.local` with the dev values of every secret
listed in section 1. Never commit this file.
