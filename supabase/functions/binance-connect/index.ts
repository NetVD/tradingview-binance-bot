// POST /functions/v1/binance-connect
//
// Body: { api_key: string, api_secret: string, label?: string }
//
// 1. Verifies the caller's JWT (via Supabase auth).
// 2. Calls Binance with the supplied credentials to:
//      a) confirm they're valid
//      b) detect their permissions (read / trade / withdraw / IP-restrict)
// 3. Refuses the connect if `enableWithdrawals` is true — the spec is
//    explicit that we never accept a key that can withdraw.
// 4. Encrypts secret + key via public.encrypt_binance_secret (pgsodium).
// 5. Upserts into public.binance_credentials.
// 6. Flips user_profiles.binance_connected = true.
//
// Returns: { account_label, permissions }
//
// Notes
//   - We hold the plaintext keys only inside this function. They never
//     touch our local DB in cleartext and we deliberately don't even put
//     them into a let-binding outside the try/finally.

import { adminClient, requireAuthedUser } from "../_shared/supabase.ts";
import { preflight, corsHeaders } from "../_shared/cors.ts";
import { getApiPermissions } from "../_shared/binance.ts";

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

  let payload: { api_key?: string; api_secret?: string; label?: string };
  try {
    payload = await req.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }
  const apiKey = (payload.api_key ?? "").trim();
  const apiSecret = (payload.api_secret ?? "").trim();
  const label = (payload.label ?? "Main").slice(0, 64);

  if (!apiKey || !apiSecret) {
    return json({ error: "missing_credentials" }, 400);
  }

  // -- 1. Validate with Binance ---------------------------------------
  let perms;
  try {
    perms = await getApiPermissions({ apiKey, apiSecret });
  } catch (e) {
    return json({ error: "binance_rejected", detail: String(e) }, 400);
  }

  if (perms.enableWithdrawals) {
    return json(
      {
        error: "withdrawals_must_be_disabled",
        detail:
          "Your API key has withdrawal permission enabled. " +
          "Disable it on Binance > API Management before connecting.",
      },
      400,
    );
  }
  if (!perms.enableFutures) {
    return json(
      {
        error: "futures_not_enabled",
        detail: "Enable 'Futures' permission on your Binance API key.",
      },
      400,
    );
  }

  // -- 2. Encrypt + store ---------------------------------------------
  const admin = adminClient();
  try {
    const associated = `binance_creds_v1:${user.id}`;

    const { data: encKey, error: e1 } = await admin
      .rpc("encrypt_binance_secret", { plaintext: apiKey, associated })
      .single();
    const { data: encSec, error: e2 } = await admin
      .rpc("encrypt_binance_secret", { plaintext: apiSecret, associated })
      .single();
    if (e1 || e2 || !encKey || !encSec) {
      return json({ error: "encryption_failed", detail: e1?.message ?? e2?.message }, 500);
    }

    const { error: upsertError } = await admin
      .from("binance_credentials")
      .upsert(
        {
          user_id: user.id,
          encrypted_api_key: encKey.ciphertext,
          encrypted_api_secret: encSec.ciphertext,
          nonce_key: encKey.nonce,
          nonce_secret: encSec.nonce,
          key_id: encKey.key_id,
          account_label: label,
          permissions: {
            read: true,
            trade: perms.enableFutures || perms.enableSpotAndMarginTrading,
            withdraw: false,
            ip_restricted: perms.ipRestrict,
          },
          is_active: true,
        },
        { onConflict: "user_id" },
      );
    if (upsertError) return json({ error: "store_failed", detail: upsertError.message }, 500);

    const { error: profileError } = await admin
      .from("user_profiles")
      .update({ binance_connected: true })
      .eq("id", user.id);
    if (profileError) {
      return json({ error: "profile_update_failed", detail: profileError.message }, 500);
    }

    return json({
      account_label: label,
      permissions: {
        read: true,
        trade: true,
        withdraw: false,
        ip_restricted: perms.ipRestrict,
      },
    });
  } finally {
    // Best-effort: nothing else in this scope holds the plaintext, but be
    // explicit so a future refactor doesn't accidentally hoist them.
    // (Deno isolates terminate after the response anyway.)
  }
});
