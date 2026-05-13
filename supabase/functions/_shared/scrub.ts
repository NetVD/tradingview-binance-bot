// Scrub credential-ish fields before any kind of logging or persistence.
// Defensive: even if Binance changes its response shape, we'd rather strip
// too much than leak a secret into the trade_executions table.

const SENSITIVE_KEYS = new Set([
  "apikey",
  "api_key",
  "apisecret",
  "api_secret",
  "secret",
  "x-mbx-apikey",
  "signature",
  "authorization",
]);

export function scrub<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map(scrub) as unknown as T;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_KEYS.has(k.toLowerCase())) {
        out[k] = "[REDACTED]";
      } else {
        out[k] = scrub(v);
      }
    }
    return out as unknown as T;
  }
  return value;
}
