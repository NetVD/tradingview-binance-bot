// POST /functions/v1/binance-execute
//
// Body:
//   {
//     signal_id: number,
//     symbol: "BTCUSDT" | "XAUUSDT" | "XAGUSDT",
//     side: "LONG" | "SHORT",
//     margin_usdt: number,
//     leverage: number,
//     sl_price: number,   // user-confirmed
//     tp_price: number,   // user-confirmed
//     entry_price_hint: number   // last seen mark price (for size calc)
//   }
//
// 1. Verifies JWT + tier (must be ≥ global per the spec; binance_connected
//    must be true).
// 2. Loads the active credentials row.
// 3. RPC decrypt_binance_secret to obtain plaintext key+secret in this scope.
// 4. Calls SET_LEVERAGE → SET_MARGIN_TYPE → NEW_ORDER (market entry)
//    → STOP_MARKET (SL, closePosition) → TAKE_PROFIT_MARKET (TP, closePosition).
// 5. Persists a trade_executions row with scrubbed raw_response.
// 6. Returns a summary.
//
// On error after the market order is filled we attempt best-effort cleanup
// of dangling SL/TP brackets and log a 'partial' execution. The client
// must be prepared to surface that state.

import {
  BinanceCredentials,
  BinanceError,
  OrderSide,
  placeMarketOrder,
  placeStopMarket,
  placeTakeProfitMarket,
  setLeverage,
  setMarginType,
} from "../_shared/binance.ts";
import { adminClient, requireAuthedUser } from "../_shared/supabase.ts";
import { preflight, corsHeaders } from "../_shared/cors.ts";
import { scrub } from "../_shared/scrub.ts";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });

type ExecuteBody = {
  signal_id: number;
  symbol: "BTCUSDT" | "XAUUSDT" | "XAGUSDT";
  side: "LONG" | "SHORT";
  margin_usdt: number;
  leverage: number;
  sl_price: number;
  tp_price: number;
  entry_price_hint: number;
};

function validateBody(body: unknown): ExecuteBody | string {
  const b = body as Partial<ExecuteBody>;
  if (typeof b !== "object" || b === null) return "body_not_object";
  if (typeof b.signal_id !== "number") return "signal_id_required";
  if (b.symbol !== "BTCUSDT" && b.symbol !== "XAUUSDT" && b.symbol !== "XAGUSDT") {
    return "symbol_invalid";
  }
  if (b.side !== "LONG" && b.side !== "SHORT") return "side_invalid";
  if (typeof b.margin_usdt !== "number" || b.margin_usdt <= 0) return "margin_usdt_invalid";
  if (typeof b.leverage !== "number" || b.leverage < 1 || b.leverage > 125) {
    return "leverage_invalid";
  }
  if (typeof b.sl_price !== "number" || b.sl_price <= 0) return "sl_price_invalid";
  if (typeof b.tp_price !== "number" || b.tp_price <= 0) return "tp_price_invalid";
  if (typeof b.entry_price_hint !== "number" || b.entry_price_hint <= 0) {
    return "entry_price_hint_invalid";
  }
  return b as ExecuteBody;
}

Deno.serve(async (req) => {
  const pre = preflight(req);
  if (pre) return pre;
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const { user, error: authError } = await requireAuthedUser(req);
  if (!user) return json({ error: "unauthorized", detail: authError }, 401);

  let raw: unknown;
  try {
    raw = await req.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }
  const body = validateBody(raw);
  if (typeof body === "string") return json({ error: body }, 400);

  const admin = adminClient();

  // -- 1. Tier + connection state --------------------------------------
  const { data: profile, error: profileError } = await admin
    .from("v_user_tier")
    .select("current_tier,is_active")
    .eq("user_id", user.id)
    .single();
  if (profileError || !profile) return json({ error: "profile_missing" }, 403);
  if (!profile.is_active || profile.current_tier === "free") {
    return json({ error: "tier_required", current_tier: profile.current_tier }, 403);
  }

  // -- 2. Load credentials --------------------------------------------
  const { data: credRow, error: credError } = await admin
    .from("binance_credentials")
    .select("encrypted_api_key,encrypted_api_secret,key_id,is_active")
    .eq("user_id", user.id)
    .maybeSingle();
  if (credError) return json({ error: "credentials_lookup_failed" }, 500);
  if (!credRow || !credRow.is_active) return json({ error: "binance_not_connected" }, 403);

  const associated = `binance_creds_v1:${user.id}`;
  const { data: keyPlain, error: kErr } = await admin.rpc("decrypt_binance_secret", {
    ciphertext: credRow.encrypted_api_key,
    associated,
    p_key_id: credRow.key_id,
  });
  const { data: secPlain, error: sErr } = await admin.rpc("decrypt_binance_secret", {
    ciphertext: credRow.encrypted_api_secret,
    associated,
    p_key_id: credRow.key_id,
  });
  if (kErr || sErr || !keyPlain || !secPlain) {
    return json({ error: "decryption_failed" }, 500);
  }

  const creds: BinanceCredentials = { apiKey: keyPlain as string, apiSecret: secPlain as string };
  const orderSide: OrderSide = body.side === "LONG" ? "BUY" : "SELL";
  const closingSide: OrderSide = body.side === "LONG" ? "SELL" : "BUY";

  // Position notional = margin × leverage. Quantity = notional / entry hint.
  const notional = body.margin_usdt * body.leverage;
  const qty = +(notional / body.entry_price_hint).toFixed(3);

  // -- 3. Pre-flight: leverage + margin type --------------------------
  try {
    await setLeverage(creds, body.symbol, body.leverage);
    await setMarginType(creds, body.symbol, "ISOLATED");
  } catch (e) {
    return await persistFailure(admin, user.id, body, qty, e, "pre_flight");
  }

  // -- 4. Place the market entry --------------------------------------
  const baseClient = `sk-${user.id.slice(0, 8)}-${body.signal_id}-${Date.now()}`;
  let entryResp: Record<string, unknown>;
  try {
    entryResp = (await placeMarketOrder(
      creds,
      body.symbol,
      orderSide,
      qty,
      `${baseClient}-e`,
    )) as Record<string, unknown>;
  } catch (e) {
    return await persistFailure(admin, user.id, body, qty, e, "entry");
  }

  // -- 5. Brackets (SL + TP). If either fails, log 'partial' ----------
  let slResp: unknown = null;
  let tpResp: unknown = null;
  let bracketError: unknown = null;
  try {
    slResp = await placeStopMarket(creds, body.symbol, closingSide, body.sl_price, `${baseClient}-s`);
  } catch (e) {
    bracketError = e;
  }
  if (!bracketError) {
    try {
      tpResp = await placeTakeProfitMarket(
        creds,
        body.symbol,
        closingSide,
        body.tp_price,
        `${baseClient}-t`,
      );
    } catch (e) {
      bracketError = e;
    }
  }

  // -- 6. Persist execution row + update credentials.last_used_at ----
  const status = bracketError ? "partial" : "filled";
  const errorMsg = bracketError ? extractErrorMessage(bracketError) : null;
  const orderId =
    typeof entryResp.orderId === "number" || typeof entryResp.orderId === "string"
      ? String(entryResp.orderId)
      : null;
  const slOrderId = extractOrderId(slResp);
  const tpOrderId = extractOrderId(tpResp);

  await admin.from("trade_executions").insert({
    user_id: user.id,
    signal_id: body.signal_id,
    symbol: body.symbol,
    side: body.side,
    leverage: body.leverage,
    margin_usdt: body.margin_usdt,
    entry_price: body.entry_price_hint,
    sl_price: body.sl_price,
    tp_price: body.tp_price,
    binance_order_id: orderId,
    binance_sl_order_id: slOrderId,
    binance_tp_order_id: tpOrderId,
    status,
    error_message: errorMsg,
    raw_response: scrub({ entry: entryResp, sl: slResp, tp: tpResp }),
  });

  await admin
    .from("binance_credentials")
    .update({ last_used_at: new Date().toISOString() })
    .eq("user_id", user.id);

  if (bracketError) {
    return json(
      {
        status: "partial",
        error: errorMsg,
        order_id: orderId,
        message:
          "Entry filled, brackets failed. Open Binance and set SL/TP manually. " +
          "Then close the position from 'Mes positions' once safe.",
      },
      207,
    );
  }

  return json({
    status: "filled",
    order_id: orderId,
    sl_order_id: slOrderId,
    tp_order_id: tpOrderId,
  });
});

async function persistFailure(
  admin: ReturnType<typeof adminClient>,
  userId: string,
  body: ExecuteBody,
  qty: number,
  err: unknown,
  stage: string,
) {
  const message = extractErrorMessage(err);
  await admin.from("trade_executions").insert({
    user_id: userId,
    signal_id: body.signal_id,
    symbol: body.symbol,
    side: body.side,
    leverage: body.leverage,
    margin_usdt: body.margin_usdt,
    sl_price: body.sl_price,
    tp_price: body.tp_price,
    status: "failed",
    error_message: `${stage}: ${message}`,
    raw_response: scrub({ qty }),
  });
  return new Response(
    JSON.stringify({ status: "failed", stage, error: message }),
    { status: 400, headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
}

function extractErrorMessage(err: unknown): string {
  if (err instanceof BinanceError) return `[${err.code}] ${err.message}`;
  if (err instanceof Error) return err.message;
  return String(err);
}

function extractOrderId(resp: unknown): string | null {
  if (resp === null || typeof resp !== "object") return null;
  const id = (resp as Record<string, unknown>).orderId;
  if (typeof id === "number" || typeof id === "string") return String(id);
  return null;
}
