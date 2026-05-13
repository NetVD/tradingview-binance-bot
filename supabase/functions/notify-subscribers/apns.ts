// Minimal APNS client using the JWT-based provider authentication.
// We talk to Apple's HTTP/2 endpoint directly with fetch() — Deno supports
// HTTP/2 natively so we don't need an extra library.
//
// Apple's docs:
//   https://developer.apple.com/documentation/usernotifications/sending_notification_requests_to_apns
//
// Env required:
//   APNS_TEAM_ID
//   APNS_KEY_ID
//   APNS_AUTH_KEY_P8       PEM-encoded ECDSA P-256 private key
//   APNS_USE_SANDBOX       "true" for TestFlight, "false" for App Store
//   APNS_BUNDLE_ID

import { create, getNumericDate, Header, Payload } from "https://deno.land/x/djwt@v3.0.2/mod.ts";

const TEAM_ID = Deno.env.get("APNS_TEAM_ID") ?? "";
const KEY_ID = Deno.env.get("APNS_KEY_ID") ?? "";
const PRIVATE_KEY_PEM = Deno.env.get("APNS_AUTH_KEY_P8") ?? "";

// Apple recommends regenerating the JWT every ~50 min; we regenerate every
// 30 min to be safe. The token is cached at module scope so warm Edge
// Function invocations reuse it.
let cachedToken: { token: string; expires_at: number } | null = null;

async function importP8Key(pem: string): Promise<CryptoKey> {
  const stripped = pem
    .replace(/-----BEGIN PRIVATE KEY-----/, "")
    .replace(/-----END PRIVATE KEY-----/, "")
    .replace(/\s+/g, "");
  const der = Uint8Array.from(atob(stripped), (c) => c.charCodeAt(0));
  return await crypto.subtle.importKey(
    "pkcs8",
    der,
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign"],
  );
}

export async function buildApnsJwt(): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  if (cachedToken && cachedToken.expires_at > now + 60) {
    return cachedToken.token;
  }

  const key = await importP8Key(PRIVATE_KEY_PEM);
  const header: Header = { alg: "ES256", kid: KEY_ID, typ: "JWT" };
  const payload: Payload = { iss: TEAM_ID, iat: getNumericDate(0) };
  const token = await create(header, payload, key);
  cachedToken = { token, expires_at: now + 30 * 60 };
  return token;
}

export type ApnsResult = {
  status: number;
  reason?: string;
  apnsId?: string;
};

export async function sendApnsPush(args: {
  token: string;
  useSandbox: boolean;
  bundleId: string;
  deviceToken: string;
  payload: Record<string, unknown>;
  collapseId?: string;
}): Promise<ApnsResult> {
  const host = args.useSandbox ? "api.sandbox.push.apple.com" : "api.push.apple.com";
  const url = `https://${host}/3/device/${args.deviceToken}`;

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `bearer ${args.token}`,
      "apns-topic": args.bundleId,
      "apns-push-type": "alert",
      "apns-priority": "10",
      ...(args.collapseId ? { "apns-collapse-id": args.collapseId } : {}),
      "content-type": "application/json",
    },
    body: JSON.stringify(args.payload),
  });

  if (resp.status === 200) {
    return { status: 200, apnsId: resp.headers.get("apns-id") ?? undefined };
  }
  const body = await resp.json().catch(() => ({}));
  return {
    status: resp.status,
    reason: typeof body?.reason === "string" ? body.reason : undefined,
  };
}
