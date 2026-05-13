-- =====================================================================
-- SkullTrading iOS — RPC helper for notify-subscribers Edge Function
-- =====================================================================
-- Returns the (user_id, device_id, apns_token) tuples that should receive
-- a push for a given signal, based on:
--   - tier ≥ global AND subscription active
--   - subscribed to the symbol
--   - recommendation matches notify_strong_go / notify_go / notify_avoid
--   - conviction ≥ user's min_conviction
--   - device has notifications_enabled = true
-- =====================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.list_notification_targets(
    p_symbol TEXT,
    p_recommendation TEXT,
    p_min_conviction INTEGER
)
RETURNS TABLE (
    user_id   UUID,
    device_id UUID,
    apns_token TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        d.user_id,
        d.id AS device_id,
        d.apns_token
    FROM public.user_devices d
    JOIN public.v_user_tier t
        ON t.user_id = d.user_id
       AND t.is_active = true
       AND t.current_tier <> 'free'
    JOIN public.user_pair_subscriptions s
        ON s.user_id = d.user_id
       AND s.symbol = p_symbol
       AND s.min_conviction <= p_min_conviction
       AND (
           (p_recommendation = 'STRONG_GO' AND s.notify_strong_go = true)
        OR (p_recommendation = 'GO'        AND s.notify_go = true)
        OR (p_recommendation = 'AVOID'     AND s.notify_avoid = true)
       )
    WHERE d.notifications_enabled = true;
$$;

REVOKE ALL ON FUNCTION public.list_notification_targets(TEXT, TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.list_notification_targets(TEXT, TEXT, INTEGER) TO service_role;

COMMIT;
