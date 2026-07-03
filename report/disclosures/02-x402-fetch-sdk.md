# Disclosure draft — x402-fetch: deprecated-v1 parse gap + silent cap footgun

**To:** maintainers of the `x402` TypeScript packages (Coinbase)
**Status:** DRAFT — not sent. Do not send without explicit authorization.
**Version tested:** `x402-fetch@1.2.0` (npm, 2026-07-03) — the **deprecated v1**
package. Current `x402` core (main) and `@x402/fetch` v2 were also inspected.
**Severity:** (A) tooling maturity — the still-installable v1 package can't pay
v2 servers (not a defect in maintained code); (B) safety — the v1 package
silently disables the payer's spend cap.

> **Correction from an earlier draft.** We initially characterized (A) as an SDK
> bug. On inspection, current `x402` core already accepts CAIP-2 and v2 bodies
> (`NetworkSchema = union(V1, V2)`, `PaymentRequirementsSchema = union(V1, V2)`),
> and `x402-fetch@1.2.0` is the **explicitly deprecated v1 package** ("security
> patches only", migrate to `@x402/fetch`). So (A) is not a bug in maintained
> code — it is the consequence of the deprecated package still being the default
> `npm i x402-fetch`, and speaking v1 by design. We report it as such below.

## Issue A — the deprecated v1 package cannot parse x402-v2 402 responses

`x402-fetch@1.2.0`'s `PaymentRequirementsSchema` rejects payment-requirement
objects that use x402-v2 conventions, which a large fraction of live servers now
emit. (This is expected for a v1 package; the concern is that it remains the
package `npm i x402-fetch` installs.)

1. **CAIP-2 network identifiers.** Servers return `network: "eip155:8453"`
   (CAIP-2 for Base mainnet); the schema's `network` is an enum of SDK-internal
   names (`"base"`, `"base-sepolia"`, …) and throws
   `invalid_enum_value ... received 'eip155:8453'`.
2. **v2 field names.** Some servers send `amount` rather than `maxAmountRequired`
   and omit `resource` / `description` / `mimeType`, which the v1 schema marks
   required, throwing `invalid_type ... "maxAmountRequired" Required`.

### Impact (measured)

In a 75-endpoint paid probe run, **30 of 75 attempts (40%) failed at this parse
step before any payment could be constructed** — i.e. the SDK could not pay
otherwise-payable, live x402 endpoints. CAIP-2 forms observed included
`eip155:8453`, `eip155:137`, `eip155:196`, `eip155:42161`, and
`solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`.

### Reproduction

```js
import { wrapFetchWithPayment } from "x402-fetch";
// GET any x402-v2 endpoint that answers 402 with network:"eip155:8453"
// e.g. https://api.biotechcatalystsentinel.com/v1/catalysts/upcoming
// -> throws a Zod error on `network` (and, once mapped, on maxAmountRequired)
```

We worked around it with a normalization shim that rewrites `network` (CAIP-2 →
SDK name) and back-fills v2 field names before the SDK parses the body
(`pipeline/paid/paid_probe.mjs`, `normalizeAccept`). After the shim, previously
rejected endpoints paid successfully.

### Proposed action

Current `@x402/fetch` v2 already parses these bodies, so no schema change is
needed there. The actionable item is reducing the footgun of the deprecated
package still being the default install: e.g. a runtime/console deprecation
notice pointing v1 users to `@x402/fetch`, or npm-deprecating `x402-fetch` so
`npm i x402-fetch` surfaces the migration path. (No code PR filed for this item.)

## Issue B — `maxValue` passed as an object silently disables the cap

`wrapFetchWithPayment(fetch, signer, maxValue)` takes the max spend as a
**positional `bigint`** (third argument). Passing a config-style object —
`wrapFetchWithPayment(fetch, signer, { maxValue: 100000n })` — is **accepted
without error** and disables the cap: the internal comparison `amount > maxValue`
becomes `bigint > object`, which is always `false`, so no amount is ever
rejected, and the library's own default ceiling (0.1 USDC) is also lost.

### Impact (measured, on ourselves)

Our first run used the object form. An endpoint listed at $0.01 quoted **$15.00**
at settlement, and the payment went through because the cap was silently inert.
A correct positional `bigint` cap rejects it before signing.

### Reproduction

```js
// disabled cap — no throw, pays any amount:
const f1 = wrapFetchWithPayment(fetch, signer, { maxValue: 1_000_000n });
// enforced cap — throws "Payment amount exceeds maximum allowed" over 1 USDC:
const f2 = wrapFetchWithPayment(fetch, signer, 1_000_000n);
```

Our regression test demonstrating both the enforced and boundary cases:
`pipeline/paid/test_cap.mjs` ($15.00 and $1.01 throw with zero payment attempts;
$0.99 proceeds to exactly one attempt).

### Proposed fix

Reject a non-`bigint` `maxValue` at wrap time (throw a clear error), or accept an
options object and read `maxValue` from it. Either removes the silent-no-op.
Given this argument gates real spend, failing loud is the safer default.

## Note

We are preparing a public report on x402 endpoint quality that references both
issues. We would like to offer a **7-day window** from the send date to review
and respond before publication, and will gladly reflect a fix or comment.
