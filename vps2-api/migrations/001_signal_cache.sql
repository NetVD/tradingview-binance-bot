-- =====================================================================
-- VPS-2 local Postgres : signal cache + dead letter + audit
-- =====================================================================
-- This DB is owned by the FastAPI service. It holds:
--   - signal_cache       : the latest N signals received from VPS-1
--   - signal_dead_letter : webhooks that failed downstream processing
--   - api_audit          : per-request audit log (best-effort, sampled)
-- =====================================================================

CREATE TABLE IF NOT EXISTS signal_cache (
    id                      BIGSERIAL PRIMARY KEY,
    vps1_signal_id          BIGINT NOT NULL UNIQUE,
    symbol                  TEXT NOT NULL,
    direction               TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    recommendation          TEXT NOT NULL
        CHECK (recommendation IN ('STRONG_GO', 'GO', 'NEUTRAL', 'AVOID')),
    conviction              SMALLINT NOT NULL CHECK (conviction BETWEEN 1 AND 10),
    entry_price             NUMERIC(18, 8),
    sl_price                NUMERIC(18, 8),
    tp_price                NUMERIC(18, 8),
    key_levels              JSONB,
    gekko_basic             JSONB,
    gekko_detailed          JSONB,
    tools_used              JSONB,
    score                   NUMERIC(8, 4),
    market_regime           TEXT,
    received_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at              TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_signal_cache_symbol_received
    ON signal_cache (symbol, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_cache_recommendation
    ON signal_cache (recommendation, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_cache_expires_at
    ON signal_cache (expires_at);


CREATE TABLE IF NOT EXISTS signal_dead_letter (
    id              BIGSERIAL PRIMARY KEY,
    payload         JSONB NOT NULL,
    error           TEXT NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retried_at      TIMESTAMPTZ,
    resolved        BOOLEAN NOT NULL DEFAULT false
);


CREATE TABLE IF NOT EXISTS api_audit (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID,
    tier            TEXT,
    method          TEXT NOT NULL,
    path            TEXT NOT NULL,
    status_code     SMALLINT NOT NULL,
    latency_ms      INTEGER NOT NULL,
    request_id      TEXT,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_audit_user_time
    ON api_audit (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_audit_status_time
    ON api_audit (status_code, created_at DESC)
    WHERE status_code >= 400;
