-- =====================================================================
-- SkullTrading iOS — Initial Supabase schema
-- Phase 1, Semaine 1
-- =====================================================================
-- Creates the user-facing tables that back the iOS app.
-- auth.users is managed by Supabase Auth; we never write to it directly.
-- All user data is namespaced under public.* and gated by RLS (002).
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- user_profiles : 1-1 extension of auth.users
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_profiles (
    id                          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name                TEXT,
    preferred_language          TEXT NOT NULL DEFAULT 'en',
    preferred_timezone          TEXT NOT NULL DEFAULT 'UTC',
    current_tier                TEXT NOT NULL DEFAULT 'free'
        CHECK (current_tier IN ('free', 'global', 'pro', 'personalized')),
    subscription_expires_at     TIMESTAMPTZ,
    binance_connected           BOOLEAN NOT NULL DEFAULT false,
    disclaimers_accepted_at     TIMESTAMPTZ,
    disclaimers_version         INTEGER NOT NULL DEFAULT 1,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  public.user_profiles IS 'Extended user profile (tier, language, disclaimer acceptance, Binance link state).';
COMMENT ON COLUMN public.user_profiles.current_tier IS 'Subscription tier from RevenueCat. Authoritative for tier-gated features.';
COMMENT ON COLUMN public.user_profiles.disclaimers_version IS 'Increment when legal text changes to force re-acceptance.';

-- Auto-create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.user_profiles (id, display_name)
    VALUES (NEW.id, COALESCE(NEW.raw_user_meta_data->>'display_name', NEW.email));
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS user_profiles_touch ON public.user_profiles;
CREATE TRIGGER user_profiles_touch
    BEFORE UPDATE ON public.user_profiles
    FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();


-- ---------------------------------------------------------------------
-- user_devices : APNS push tokens
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_devices (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    apns_token              TEXT NOT NULL,
    device_model            TEXT,
    ios_version             TEXT,
    app_version             TEXT,
    last_active_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notifications_enabled   BOOLEAN NOT NULL DEFAULT true,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, apns_token)
);

COMMENT ON TABLE public.user_devices IS 'APNS device tokens. Soft-disabled via notifications_enabled.';


-- ---------------------------------------------------------------------
-- user_pair_subscriptions : per-symbol notification preferences
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_pair_subscriptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    symbol              TEXT NOT NULL
        CHECK (symbol IN ('BTCUSDT', 'XAUUSDT', 'XAGUSDT')),
    notify_strong_go    BOOLEAN NOT NULL DEFAULT true,
    notify_go           BOOLEAN NOT NULL DEFAULT true,
    notify_avoid        BOOLEAN NOT NULL DEFAULT false,
    min_conviction      INTEGER NOT NULL DEFAULT 6
        CHECK (min_conviction BETWEEN 1 AND 10),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, symbol)
);

COMMENT ON TABLE public.user_pair_subscriptions IS 'Per-user, per-symbol notification preferences. Used by notify-subscribers Edge Function.';


-- ---------------------------------------------------------------------
-- binance_credentials : encrypted API keys
-- ---------------------------------------------------------------------
-- Encryption strategy:
--   The Edge Function (binance-connect) uses pgsodium.crypto_aead_det_encrypt
--   to encrypt api_key and api_secret with a key stored in pgsodium.key.
--   The key's UUID is referenced via key_id below.
--
--   We store:
--     encrypted_api_key, encrypted_api_secret : ciphertext (BYTEA)
--     nonce_*                                  : nonces used for encryption
--     key_id                                   : pgsodium key UUID
--
--   Decryption happens *only* inside Edge Functions, never in the client
--   nor in plain queries from the VPS-2 API. RLS still applies, so even
--   a leaked anon key cannot read another user's row.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.binance_credentials (
    user_id                 UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    encrypted_api_key       BYTEA NOT NULL,
    encrypted_api_secret    BYTEA NOT NULL,
    nonce_key               BYTEA NOT NULL,
    nonce_secret            BYTEA NOT NULL,
    key_id                  UUID NOT NULL,
    account_label           TEXT,
    permissions             JSONB NOT NULL DEFAULT '{}'::JSONB,
    is_active               BOOLEAN NOT NULL DEFAULT true,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at            TIMESTAMPTZ
);

COMMENT ON TABLE  public.binance_credentials IS 'AES-256-GCM ciphertext for Binance API key/secret. Decrypted in Edge Functions only.';
COMMENT ON COLUMN public.binance_credentials.permissions IS '{ "read": bool, "trade": bool, "withdraw": bool } as detected during binance-connect validation.';
COMMENT ON COLUMN public.binance_credentials.key_id IS 'pgsodium.key.id used for encryption. Allows key rotation.';


-- ---------------------------------------------------------------------
-- trade_executions : user-facing history of orders placed by the app
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.trade_executions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    signal_id           BIGINT,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    leverage            INTEGER NOT NULL CHECK (leverage BETWEEN 1 AND 125),
    margin_usdt         NUMERIC(12, 2) NOT NULL CHECK (margin_usdt > 0),
    entry_price         NUMERIC(18, 8),
    sl_price            NUMERIC(18, 8),
    tp_price            NUMERIC(18, 8),
    binance_order_id    TEXT,
    binance_sl_order_id TEXT,
    binance_tp_order_id TEXT,
    status              TEXT NOT NULL
        CHECK (status IN ('pending', 'filled', 'failed', 'cancelled', 'partial')),
    error_message       TEXT,
    raw_response        JSONB,
    executed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  public.trade_executions IS 'One row per user-confirmed order. Never holds credentials, only order identifiers and outcome.';
COMMENT ON COLUMN public.trade_executions.raw_response IS 'Full Binance response for debugging. Scrubbed of any sensitive fields by the Edge Function.';


-- ---------------------------------------------------------------------
-- signal_access_logs : analytics and rate-limit audit
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.signal_access_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    signal_id       BIGINT,
    access_type     TEXT NOT NULL
        CHECK (access_type IN ('view', 'gekko_basic', 'gekko_detailed', 'execute', 'push_received')),
    tier_at_time    TEXT NOT NULL,
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.signal_access_logs IS 'Append-only access log. Drives per-user analytics and tier-tampering detection.';


-- ---------------------------------------------------------------------
-- Helper view : tier expiry (drives binance-execute authorization)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_user_tier AS
SELECT
    p.id AS user_id,
    p.current_tier,
    p.subscription_expires_at,
    CASE
        WHEN p.current_tier = 'free' THEN true
        WHEN p.subscription_expires_at IS NULL THEN false
        WHEN p.subscription_expires_at > NOW() THEN true
        ELSE false
    END AS is_active
FROM public.user_profiles p;

COMMENT ON VIEW public.v_user_tier IS 'Authoritative source for "is this user entitled right now?" — checks RevenueCat-driven expiry.';


COMMIT;
