# #2 x402-fetch — Coinbase HackerOne submission

**Channel:** https://hackerone.com/coinbase  (Coinbase SECURITY.md: report
security findings via HackerOne; do not file public tickets.)

**Title:**
```
x402-fetch (v1): non-bigint maxValue silently disables the payer spend cap
```

**Asset / scope:** npm package `x402-fetch` (repo: coinbase/x402,
`typescript/packages/legacy/x402-fetch`).

**Weakness:** Improper input validation → spend-limit bypass (financial impact).

**Severity (suggested):** Low–Medium — funds loss requires a caller mistake, but
the mistake is silent and the package is still installable as `npm i x402-fetch`.

**Write-up (paste):**
```markdown
## Summary
`wrapFetchWithPayment(fetch, wallet, maxValue)` takes `maxValue` as a positional
`bigint` (base units), defaulting to 0.1 USDC. In untyped JS, passing an options
object — `wrapFetchWithPayment(fetch, wallet, { maxValue: 1_000_000n })` — is
accepted at runtime. The later check `BigInt(amount) > maxValue` becomes
`bigint > object`, which coerces the object to NaN and is always false, so the
cap never triggers and the built-in 0.1 USDC default is also lost. The wrapped
fetch will then pay whatever a 402 response quotes.

## Impact
A payer that intends to cap per-request spend can be charged an unbounded amount.
In our own testing an endpoint listed at $0.01 quoted and settled $15.00 while a
malformed (object) maxValue was in effect; with a correct bigint cap the same
request is rejected before signing.

## Reproduction
```js
// no throw, pays any amount (cap disabled):
const f1 = wrapFetchWithPayment(fetch, signer, { maxValue: 1_000_000n });
// enforced (throws over 1 USDC):
const f2 = wrapFetchWithPayment(fetch, signer, 1_000_000n);
```

## Fix
Reject a non-bigint `maxValue` at wrap time:
```ts
if (typeof maxValue !== "bigint") {
  throw new Error("wrapFetchWithPayment: `maxValue` must be a bigint (base units).");
}
```
Patch prepared against current `main`
(`typescript/packages/legacy/x402-fetch/src/index.ts`); happy to open the PR.

## Note
This package is the deprecated v1 (`@x402/fetch` v2 removes the positional
maxValue entirely). Since v1 still ships to npm and this is a silent spend-cap
bypass, a guard seems worthwhile even if the broader answer is "migrate to v2."
I plan to reference this in a public report in ~7 days and would welcome your
view first.
```
