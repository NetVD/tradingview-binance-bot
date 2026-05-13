# Supabase

This directory holds everything that runs on Supabase: schema migrations,
Row Level Security policies, the `pgsodium` setup for Binance credentials,
and the Edge Functions called by the iOS app.

## Layout

```
migrations/   SQL migrations applied in lexical order
  001_initial_schema.sql      Tables, triggers, helper view
  002_rls_policies.sql        Row Level Security on every table
  003_indexes.sql             Indexes for the hot queries
  004_vault_setup.sql         pgsodium key + encrypt/decrypt helpers

functions/    Deno / TypeScript Edge Functions
  _shared/                    Code shared across functions (JWT, Binance client)
  binance-connect/            Validate + encrypt + store API keys
  binance-disconnect/         Soft-delete API keys
  binance-execute/            Execute a trade on Binance
  notify-subscribers/         Fan out APNS pushes when a signal arrives

tests/        Python integration tests (run against a live Supabase project)
  test_rls.py                 Verifies user isolation
```

## Applying migrations

Supabase CLI:

```bash
# Link the local repo to your Supabase project (once)
supabase login
supabase link --project-ref <project-ref>

# Apply migrations
supabase db push
```

Or, manually, run each file in order against the project's Postgres URL:

```bash
psql "$SUPABASE_DB_URL" -f migrations/001_initial_schema.sql
psql "$SUPABASE_DB_URL" -f migrations/002_rls_policies.sql
psql "$SUPABASE_DB_URL" -f migrations/003_indexes.sql
psql "$SUPABASE_DB_URL" -f migrations/004_vault_setup.sql
```

## Deploying Edge Functions

```bash
supabase functions deploy binance-connect
supabase functions deploy binance-disconnect
supabase functions deploy binance-execute
supabase functions deploy notify-subscribers

# Set the secrets used by the functions
supabase secrets set \
  BINANCE_BASE_URL="https://fapi.binance.com" \
  APNS_TEAM_ID="..." \
  APNS_KEY_ID="..." \
  APNS_BUNDLE_ID="com.skulltrading.app" \
  APNS_AUTH_KEY_P8="$(cat ./AuthKey_XXXXXXXX.p8)" \
  SERVICE_TOKEN="$(openssl rand -hex 32)"
```

See `../docs/BACKEND_V2.md` for the complete environment variable reference.

## Running RLS tests

```bash
cd tests
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SUPABASE_URL=https://<ref>.supabase.co
export SUPABASE_ANON_KEY=...
export SUPABASE_SERVICE_KEY=...
pytest test_rls.py -v
```
