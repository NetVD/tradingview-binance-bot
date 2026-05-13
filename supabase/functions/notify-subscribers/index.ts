// POST /functions/v1/notify-subscribers
//
// Called by VPS-2 (service-role JWT) immediately after it persists a
// webhook from VPS-1. We fan out APNS pushes to every device whose owner:
//   - has tier ≥ global AND is_active
//   - has a row in user_pair_subscriptions for the signal's symbol
//   - whose notify_* flag matches the recommendation
//   - and whose user_devices row has notifications_enabled = true
//
// Body:
//   {
//     signal_id: number,
//     symbol: string,
//     direction: "LONG" | "SHORT",
//     recommendation: "STRONG_GO" | "GO" | "NEUTRAL" | "AVOID",
//     conviction: number,
//     entry_price: string | null,
//     headline: string | null
//   }
//
// Returns: { dispatched: number, skipped: number, failed: number }

import { adminClient } from "../_shared/supabase.ts";
import { preflight, corsHeaders } from "../_shared/cors.ts";
import { buildApnsJwt, sendApnsPush } from "./apns.ts";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });

type SignalBody = {
  signal_id: number;
  symbol: string;
  direction: "LONG" | "SHORT";
  recommendation: "STRONG_GO" | "GO" | "NEUTRAL" | "AVOID";
  conviction: number;
  entry_price: string | null;
  headline: string | null;
};

function verifyServiceRole(req: Request): boolean {
  const auth = req.headers.get("Authorization") ?? "";
  const expected = `Bearer ${Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""}`;
  return auth === expected;
}

Deno.serve(async (req) => {
  const pre = preflight(req);
  if (pre) return pre;
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  if (!verifyServiceRole(req)) return json({ error: "unauthorized" }, 401);

  let body: SignalBody;
  try {
    body = (await req.json()) as SignalBody;
  } catch {
    return json({ error: "invalid_json" }, 400);
  }

  const admin = adminClient();

  // -- 1. Pull (user, device) pairs that should receive this notif ----
  // We rely on a SQL view for clarity; if you have a chunked-fanout
  // requirement later, paginate this query.
  const { data: targets, error: targetError } = await admin.rpc(
    "list_notification_targets",
    {
      p_symbol: body.symbol,
      p_recommendation: body.recommendation,
      p_min_conviction: body.conviction,
    },
  );
  if (targetError) {
    return json({ error: "target_lookup_failed", detail: targetError.message }, 500);
  }

  if (!Array.isArray(targets) || targets.length === 0) {
    return json({ dispatched: 0, skipped: 0, failed: 0 });
  }

  // -- 2. Build the APNS JWT (cached implicitly by Deno isolate) ------
  const jwtToken = await buildApnsJwt();
  const useSandbox = (Deno.env.get("APNS_USE_SANDBOX") ?? "false") === "true";
  const bundleId = Deno.env.get("APNS_BUNDLE_ID") ?? "com.skulltrading.app";

  const title = `${body.symbol} ${body.recommendation === "STRONG_GO" ? "⭐⭐⭐" : "⭐⭐"} ${body.direction}`;
  const subtitle = body.headline ?? `Conviction ${body.conviction}/10`;
  const apsPayload = {
    aps: {
      alert: { title, body: subtitle },
      sound: "default",
      "thread-id": body.symbol,
      "mutable-content": 1,
      "interruption-level": body.recommendation === "STRONG_GO" ? "time-sensitive" : "active",
    },
    signal_id: body.signal_id,
    symbol: body.symbol,
    direction: body.direction,
    recommendation: body.recommendation,
  };

  // -- 3. Fan out ----------------------------------------------------
  let dispatched = 0;
  let failed = 0;
  let skipped = 0;
  const expired: string[] = [];

  await Promise.all(
    (targets as Array<{ apns_token: string; user_id: string; device_id: string }>).map(
      async (t) => {
        try {
          const result = await sendApnsPush({
            token: jwtToken,
            useSandbox,
            bundleId,
            deviceToken: t.apns_token,
            payload: apsPayload,
          });
          if (result.status === 200) {
            dispatched += 1;
          } else if (result.status === 410 || result.reason === "Unregistered") {
            // The device uninstalled the app. Disable the token.
            expired.push(t.apns_token);
            skipped += 1;
          } else {
            failed += 1;
            console.error("apns_failed", {
              status: result.status,
              reason: result.reason,
              device_id: t.device_id,
            });
          }
        } catch (e) {
          failed += 1;
          console.error("apns_exception", { error: String(e), device_id: t.device_id });
        }
      },
    ),
  );

  if (expired.length > 0) {
    await admin
      .from("user_devices")
      .update({ notifications_enabled: false })
      .in("apns_token", expired);
  }

  return json({ dispatched, skipped, failed });
});
