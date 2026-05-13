// Thin Binance Futures client used by binance-connect (validation) and
// binance-execute (order placement).
//
// We DO NOT use the official Binance SDK here: it pulls in too much for an
// Edge Function, and we only need a handful of endpoints. Signing is
// HMAC-SHA256 over the query string (Binance's standard pattern).
//
// Crucially: api keys are passed in as arguments. They never live in a
// closure or module-level variable. Every call wipes them from the local
// scope as soon as it returns.

const BINANCE_BASE_URL = Deno.env.get("BINANCE_BASE_URL") ?? "https://fapi.binance.com";

export type BinanceCredentials = {
  apiKey: string;
  apiSecret: string;
};

export type OrderSide = "BUY" | "SELL";
export type MarginType = "ISOLATED" | "CROSSED";

async function sign(secret: string, queryString: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(queryString));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function toQS(params: Record<string, string | number | undefined>): string {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
}

async function signedRequest(
  creds: BinanceCredentials,
  method: "GET" | "POST" | "DELETE",
  path: string,
  params: Record<string, string | number | undefined> = {},
): Promise<unknown> {
  const ts = Date.now();
  const qs = toQS({ ...params, timestamp: ts, recvWindow: 5000 });
  const signature = await sign(creds.apiSecret, qs);
  const url = `${BINANCE_BASE_URL}${path}?${qs}&signature=${signature}`;

  const resp = await fetch(url, {
    method,
    headers: { "X-MBX-APIKEY": creds.apiKey },
  });

  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new BinanceError(resp.status, body?.code, body?.msg ?? "binance error");
  }
  return body;
}

export class BinanceError extends Error {
  constructor(public status: number, public code: number | undefined, message: string) {
    super(message);
  }
}

// --- Endpoints we actually use -----------------------------------------

export async function getAccountInfo(creds: BinanceCredentials): Promise<unknown> {
  return await signedRequest(creds, "GET", "/fapi/v2/account");
}

export async function getApiPermissions(creds: BinanceCredentials): Promise<{
  ipRestrict: boolean;
  enableSpotAndMarginTrading: boolean;
  enableFutures: boolean;
  enableWithdrawals: boolean;
}> {
  // /sapi/v1/account/apiRestrictions on the spot host. We hit it cross-host.
  const ts = Date.now();
  const qs = toQS({ timestamp: ts, recvWindow: 5000 });
  const signature = await sign(creds.apiSecret, qs);
  const resp = await fetch(
    `https://api.binance.com/sapi/v1/account/apiRestrictions?${qs}&signature=${signature}`,
    { method: "GET", headers: { "X-MBX-APIKEY": creds.apiKey } },
  );
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new BinanceError(resp.status, body?.code, body?.msg ?? "binance error");
  }
  return body;
}

export async function setLeverage(
  creds: BinanceCredentials,
  symbol: string,
  leverage: number,
): Promise<unknown> {
  return await signedRequest(creds, "POST", "/fapi/v1/leverage", { symbol, leverage });
}

export async function setMarginType(
  creds: BinanceCredentials,
  symbol: string,
  marginType: MarginType,
): Promise<unknown> {
  try {
    return await signedRequest(creds, "POST", "/fapi/v1/marginType", {
      symbol,
      marginType,
    });
  } catch (err) {
    // Binance returns -4046 if the margin type is already set; that's fine.
    if (err instanceof BinanceError && err.code === -4046) {
      return { code: -4046, msg: "already set" };
    }
    throw err;
  }
}

export async function placeMarketOrder(
  creds: BinanceCredentials,
  symbol: string,
  side: OrderSide,
  quantity: number,
  clientOrderId: string,
): Promise<unknown> {
  return await signedRequest(creds, "POST", "/fapi/v1/order", {
    symbol,
    side,
    type: "MARKET",
    quantity: quantity.toString(),
    newClientOrderId: clientOrderId,
  });
}

export async function placeStopMarket(
  creds: BinanceCredentials,
  symbol: string,
  side: OrderSide,
  stopPrice: number,
  clientOrderId: string,
): Promise<unknown> {
  return await signedRequest(creds, "POST", "/fapi/v1/order", {
    symbol,
    side,
    type: "STOP_MARKET",
    stopPrice: stopPrice.toString(),
    closePosition: "true",
    timeInForce: "GTE_GTC",
    newClientOrderId: clientOrderId,
  });
}

export async function placeTakeProfitMarket(
  creds: BinanceCredentials,
  symbol: string,
  side: OrderSide,
  stopPrice: number,
  clientOrderId: string,
): Promise<unknown> {
  return await signedRequest(creds, "POST", "/fapi/v1/order", {
    symbol,
    side,
    type: "TAKE_PROFIT_MARKET",
    stopPrice: stopPrice.toString(),
    closePosition: "true",
    timeInForce: "GTE_GTC",
    newClientOrderId: clientOrderId,
  });
}
