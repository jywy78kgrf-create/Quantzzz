/**
 * Step 2a — cap verification, runnable offline (no network, no real key).
 *
 * A mock endpoint quotes a price against the $1.00 cap. Assertions:
 *   $15.00 -> executor throws, ZERO payment attempts (no 2nd fetch with X-PAYMENT)
 *   $ 1.01 -> throws, zero payment attempts (boundary, just over cap)
 *   $ 0.99 -> passes the cap and proceeds to a payment ATTEMPT: the wrapped
 *             fetch issues a retry carrying an X-PAYMENT header. The mock
 *             captures it and returns 200 — nothing signs away real funds
 *             (throwaway key, no facilitator, no network I/O).
 *
 * Run: node test_cap.mjs   (exit 0 = all three hold)
 */

import assert from "node:assert/strict";
import { wrapFetchWithPayment } from "x402-fetch";
import { privateKeyToAccount } from "viem/accounts";

const CAP_USDC = 1.0;
const THROWAWAY = privateKeyToAccount("0x" + "11".repeat(32)); // test-only key

function mock402(amountBaseUnits) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ hasPaymentHeader: Boolean(init.headers?.["X-PAYMENT"]) });
    if (init.headers?.["X-PAYMENT"]) {
      return new Response(JSON.stringify({ ok: true, mock: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({
      x402Version: 1,
      accepts: [{
        scheme: "exact", network: "base",
        maxAmountRequired: String(amountBaseUnits),
        asset: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        payTo: "0x0000000000000000000000000000000000000001",
        resource: "https://mock.invalid/x", description: "", mimeType: "",
        maxTimeoutSeconds: 60, extra: { name: "USDC", version: "2" },
      }],
    }), { status: 402, headers: { "content-type": "application/json" } });
  };
  return { fetchImpl, calls };
}

async function attempt(amountUsdc) {
  const { fetchImpl, calls } = mock402(Math.round(amountUsdc * 1e6));
  const wrapped = wrapFetchWithPayment(
    fetchImpl, THROWAWAY, BigInt(Math.round(CAP_USDC * 1e6)));
  try {
    const resp = await wrapped("https://mock.invalid/x", {});
    return { threw: false, status: resp.status,
             paymentAttempts: calls.filter(c => c.hasPaymentHeader).length };
  } catch (err) {
    return { threw: true, error: err.message,
             paymentAttempts: calls.filter(c => c.hasPaymentHeader).length };
  }
}

const over = await attempt(15.00);
console.log("$15.00 vs $1.00 cap:", JSON.stringify(over));
assert.equal(over.threw, true, "must throw over cap");
assert.match(over.error, /exceeds maximum/i);
assert.equal(over.paymentAttempts, 0, "must attempt zero payments");

const boundary = await attempt(1.01);
console.log("$ 1.01 vs $1.00 cap:", JSON.stringify(boundary));
assert.equal(boundary.threw, true, "must throw just over cap");
assert.equal(boundary.paymentAttempts, 0, "must attempt zero payments");

const under = await attempt(0.99);
console.log("$ 0.99 vs $1.00 cap:", JSON.stringify(under));
assert.equal(under.threw, false, "must pass under cap");
assert.equal(under.paymentAttempts, 1, "must reach exactly one payment attempt");
assert.equal(under.status, 200);

console.log("ALL CAP TESTS PASS");
