# SkullTrading iOS

Native iOS app (SwiftUI) that delivers AI-powered trading signals from the
"Gekko" agent backend, and lets opted-in users execute trades on Binance
Futures.

This repository contains the **new commercial app** and its supporting
infrastructure. The existing personal trading bot (VPS-1) lives in a
separate repository and is left untouched.

## Repository layout

```
docs/                       Specifications and architecture documents
supabase/
  migrations/               SQL migrations applied to the Supabase Postgres
  functions/                Supabase Edge Functions (Deno / TypeScript)
  tests/                    Migration & RLS tests (Python)
vps2-api/                   FastAPI service running on VPS-2 (api.skulltrading.com)
vps1-integration/           Snippets to add to the existing VPS-1 codebase
ops/                        Runbooks, monitoring configs, ops docs
ios-app/                    Xcode project (added in Phase 2)
```

## High-level architecture

```
iOS app  ──HTTPS+JWT──►  VPS-2 API  ──webhook+token──►  VPS-1 (existing bot)
         ──HTTPS+JWT──►  Supabase   ──Binance API──►   Binance Futures
                          (auth, DB, vault, Edge Fns)
```

See `docs/SKULLTRADING_iOS_SPEC.md` for the full specification.

## Status

| Phase | Scope | Status |
|-------|-------|--------|
| 1     | Backend foundation (Supabase, VPS-2 API, Edge Functions, APNS) | In progress |
| 2     | iOS app (SwiftUI, RevenueCat, Binance flows) | Not started |
| 3     | App Store submission and launch | Not started |

## Working on this repo

All development happens on feature branches. See `docs/SKULLTRADING_iOS_SPEC.md`
section 6 for the week-by-week roadmap.

Setup steps for each component live next to the code:

- `supabase/README.md` — how to apply migrations and deploy Edge Functions
- `vps2-api/README.md` — how to run the FastAPI service locally and deploy
- `vps1-integration/README.md` — how to wire the existing VPS-1 bot to VPS-2
- `ops/runbook.md` — VPS-2 provisioning and incident response

## Security

- Binance API keys are stored encrypted at rest using `pgsodium` (Supabase
  Vault). They are decrypted in memory inside Edge Functions only, never
  logged, and wiped after use.
- Service-to-service calls between VPS-1 and VPS-2 are authenticated with a
  shared secret token (`SERVICE_TOKEN`) and IP-restricted.
- All user-facing endpoints validate Supabase JWTs and enforce
  tier-based authorization.
- Row Level Security is enabled on every Supabase table; users can only see
  their own rows.

See `docs/BACKEND_V2.md` for the full list of secrets and how they are managed.
