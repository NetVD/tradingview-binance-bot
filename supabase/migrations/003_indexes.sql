-- =====================================================================
-- SkullTrading iOS — Indexes
-- Phase 1, Semaine 1
-- =====================================================================
-- Indexes tuned for the hottest queries:
--   1. notify-subscribers : "give me every active APNS token whose owner
--      is subscribed to symbol X with notify_strong_go = true".
--   2. iOS "Mes trades" : "give me my last N executions, newest first".
--   3. Analytics / rate-limit : "how many accesses by user X in the last minute".
-- =====================================================================

BEGIN;

-- Active APNS tokens only.
CREATE INDEX IF NOT EXISTS idx_user_devices_user_id_active
    ON public.user_devices (user_id)
    WHERE notifications_enabled = true;

-- "Who is subscribed to BTCUSDT?" — drives the notify-subscribers fan-out.
CREATE INDEX IF NOT EXISTS idx_pair_subs_symbol
    ON public.user_pair_subscriptions (symbol);

-- Lookup by (user, symbol) for the iOS app's preferences screen.
CREATE INDEX IF NOT EXISTS idx_pair_subs_user_symbol
    ON public.user_pair_subscriptions (user_id, symbol);

-- "Show me my trade history, newest first."
CREATE INDEX IF NOT EXISTS idx_trade_exec_user_time
    ON public.trade_executions (user_id, executed_at DESC);

-- Rate-limit / analytics window queries.
CREATE INDEX IF NOT EXISTS idx_signal_logs_user_time
    ON public.signal_access_logs (user_id, accessed_at DESC);

-- Tier expiry sweep (e.g. nightly job that demotes expired subscribers).
CREATE INDEX IF NOT EXISTS idx_user_profiles_tier_expiry
    ON public.user_profiles (subscription_expires_at)
    WHERE current_tier <> 'free';

COMMIT;
