// POST /functions/v1/binance-disconnect
//
// Soft-disables the user's Binance credentials. The row is kept so we can
// audit historic trade_executions; the encrypted blob stays encrypted and
// will never be used again because is_active = false short-circuits the
// binance-execute function.

import { adminClient, requireAuthedUser } from "../_shared/supabase.ts";
import { preflight, corsHeaders } from "../_shared/cors.ts";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });

Deno.serve(async (req) => {
  const pre = preflight(req);
  if (pre) return pre;

  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const { user, error } = await requireAuthedUser(req);
  if (!user) return json({ error: "unauthorized", detail: error }, 401);

  const admin = adminClient();

  const { error: credError } = await admin
    .from("binance_credentials")
    .update({ is_active: false })
    .eq("user_id", user.id);
  if (credError) return json({ error: "disconnect_failed", detail: credError.message }, 500);

  const { error: profileError } = await admin
    .from("user_profiles")
    .update({ binance_connected: false })
    .eq("id", user.id);
  if (profileError) {
    return json({ error: "profile_update_failed", detail: profileError.message }, 500);
  }

  return json({ status: "disconnected" });
});
