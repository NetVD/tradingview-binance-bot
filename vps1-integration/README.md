# VPS-1 integration

The existing VPS-1 codebase (your personal trading bot + Gekko + dashboard)
is **left untouched** except for two tiny additions:

1. A new module `webhook_emitter.py` placed inside the existing project
   (e.g. under `agents/` or wherever `gekko_agent.py` lives).
2. Two new env vars (`APP_VPS_WEBHOOK_URL`, `SERVICE_TOKEN`).
3. One call inside `gekko_agent.py` right after the Gekko analysis is
   persisted, with `STRONG_GO` or `GO` recommendation.

Everything is fire-and-forget. If VPS-2 is unreachable, your bot continues
exactly as before; nothing in the personal trading path can fail because
of the webhook emitter.

## Files

- `webhook_emitter.py` — drop this into the existing bot project.
- `integration_snippet.py` — the exact lines to add inside `gekko_agent.py`.

## Adding to your bot

```bash
# From the existing VPS-1 bot repository
cp /path/to/this/repo/vps1-integration/webhook_emitter.py agents/
```

Open `agents/gekko_agent.py` and locate the spot, just after Gekko has
finished and the signal has been persisted, where you'd want to publish
to the iOS app. Add:

```python
from agents.webhook_emitter import emit_signal_to_app_vps

# ... your existing logic ...
if analysis.recommendation in ("STRONG_GO", "GO"):
    # Fire-and-forget. Does not raise.
    emit_signal_to_app_vps(signal_id=signal.id, payload=build_webhook_payload(signal, analysis))
```

See `integration_snippet.py` for a copy-pasteable version and for the
`build_webhook_payload(...)` helper that maps your domain objects to the
shape expected by VPS-2.

## Env vars

Append to your VPS-1 `.env` (alongside whatever you already have):

```
APP_VPS_WEBHOOK_URL=https://api.skulltrading.com/internal/signal-webhook
SERVICE_TOKEN=<same value as on VPS-2 and in Supabase>
```

Reload the bot (`docker compose restart` or whatever your bot uses).

## Verifying the integration

After deploying:

```bash
# On VPS-2
docker compose logs -f api | grep signal-webhook

# Then trigger a fresh analysis on VPS-1 (or wait for one). You should see:
#   POST /internal/signal-webhook 202
```

If you want to test without waiting for a real signal, use the manual
replay tool from the runbook (`docker compose exec api python -m app.tools.replay_signal --signal-id <id>`).
