-- =====================================================================
-- SkullTrading iOS — Row Level Security policies
-- Phase 1, Semaine 1
-- =====================================================================
-- Every public.* table is locked down: the anon and authenticated roles
-- can only see rows where user_id = auth.uid().
--
-- The service_role bypasses RLS entirely (used by Edge Functions and the
-- VPS-2 API for admin queries).
-- =====================================================================

BEGIN;

ALTER TABLE public.user_profiles            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_devices             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_pair_subscriptions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.binance_credentials      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trade_executions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.signal_access_logs       ENABLE ROW LEVEL SECURITY;

-- Defence in depth: explicitly forbid the anon role from reading credentials
-- even if a future policy is mis-written. Only service_role and authenticated
-- (matched by uid) should ever touch this table.
REVOKE ALL ON public.binance_credentials FROM anon;

-- ---------------------------------------------------------------------
-- user_profiles
-- ---------------------------------------------------------------------
DROP POLICY IF EXISTS user_profiles_select ON public.user_profiles;
CREATE POLICY user_profiles_select ON public.user_profiles
    FOR SELECT TO authenticated
    USING (auth.uid() = id);

DROP POLICY IF EXISTS user_profiles_update ON public.user_profiles;
CREATE POLICY user_profiles_update ON public.user_profiles
    FOR UPDATE TO authenticated
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- Insert is handled by the on_auth_user_created trigger (SECURITY DEFINER).
-- Users should not create profiles directly.

-- ---------------------------------------------------------------------
-- user_devices
-- ---------------------------------------------------------------------
DROP POLICY IF EXISTS user_devices_all ON public.user_devices;
CREATE POLICY user_devices_all ON public.user_devices
    FOR ALL TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- user_pair_subscriptions
-- ---------------------------------------------------------------------
DROP POLICY IF EXISTS user_pair_subscriptions_all ON public.user_pair_subscriptions;
CREATE POLICY user_pair_subscriptions_all ON public.user_pair_subscriptions
    FOR ALL TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- binance_credentials
-- ---------------------------------------------------------------------
-- Users may see *metadata* about their own credentials (label, permissions,
-- timestamps) but the ciphertext columns are never useful to a client.
-- We still allow SELECT through RLS for the user's own row so the iOS app
-- can render "Binance connected: yes, last used at X". The actual
-- decryption is gated by the service_role inside Edge Functions.
DROP POLICY IF EXISTS binance_credentials_select ON public.binance_credentials;
CREATE POLICY binance_credentials_select ON public.binance_credentials
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

-- Inserts / updates / deletes go through Edge Functions (service_role).
-- No direct INSERT/UPDATE/DELETE policy for authenticated users.

-- ---------------------------------------------------------------------
-- trade_executions
-- ---------------------------------------------------------------------
DROP POLICY IF EXISTS trade_executions_select ON public.trade_executions;
CREATE POLICY trade_executions_select ON public.trade_executions
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

-- Inserts done by the Edge Function (service_role) after a successful order.

-- ---------------------------------------------------------------------
-- signal_access_logs
-- ---------------------------------------------------------------------
DROP POLICY IF EXISTS signal_access_logs_select ON public.signal_access_logs;
CREATE POLICY signal_access_logs_select ON public.signal_access_logs
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

-- Inserts done by the VPS-2 API (service_role).

COMMIT;
