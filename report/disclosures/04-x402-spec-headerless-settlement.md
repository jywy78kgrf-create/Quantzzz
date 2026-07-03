# Disclosure draft — x402 spec: mandate X-PAYMENT-RESPONSE on settled payments

**To:** x402 protocol maintainers (spec repository / working group)
**Status:** DRAFT — not sent. Do not send without explicit authorization.
**Type:** Specification gap / hardening proposal

## Summary

Servers can settle an x402 payment on-chain while returning **no
`X-PAYMENT-RESPONSE` header** (and no other machine-readable settlement
confirmation) to the payer. When this happens the payer cannot determine from
the HTTP response that payment succeeded — the response may even be a 4xx/5xx —
while the funds have already moved. Naive but reasonable retry-on-failure logic
then pays a second time. We propose the spec **require** a settlement
confirmation on the response of any request whose payment settled.

## Evidence

In a paid probe of 75 listed endpoints, **25 settled a payment on-chain. 5 of
those 25 (20%) returned no `X-PAYMENT-RESPONSE` header:**

- 2 returned HTTP 200 with an ad-hoc success body (one echoed the settlement tx
  hash inside the JSON, i.e. the server *had* the confirmation and simply did
  not put it in the standard header);
- 3 returned HTTP 400 or 500 *after* settling (e.g. "Missing 'url' parameter",
  "Mint failed") — a failure response for a payment that succeeded.

Because our own client keyed its "already paid" set on the presence of
`X-PAYMENT-RESPONSE`, it recorded these as unpaid and **re-paid 4 of them on a
second run** (~$0.031 in duplicate charges). We only detected the double-pay by
reconciling against on-chain transfers. This is a concrete demonstration that
header-absent settlement leads directly to double payment under ordinary client
logic.

## Reproduction

Pay any of the affected endpoints and inspect the response headers vs. the
on-chain USDC transfer from the payer wallet:

- `https://www.qrbase.xyz/api/x402/ping` — 200, body says "Payment successful",
  no `X-PAYMENT-RESPONSE`, on-chain transfer present.
- `https://x402-secure-api.t54.ai/x402/tools/get_api_health` — 400 after
  settlement, no header.
- `https://nut402.codenut.xyz/api/mint/xs` — 500 after settlement, no header.

(Full list and tx hashes: `data/raw/paid_probes/`.)

## Current spec wording (verified 2026-07-03)

The v2 HTTP transport spec
(`specs/transports-v2/http.md`) states only: *"Servers communicate payment
settlement results using the `PAYMENT-RESPONSE` header."* It uses **no RFC-2119
keyword** (no MUST/SHOULD/MAY) for this header, and it **does not address the
case where payment settled but the server returns a non-2xx status**. So the
header is described but not required, and the settled-but-error case is
unspecified — which is exactly the gap the observed behavior falls through.

## Proposed spec change

1. Make it normative: a response to a request whose payment settled **MUST**
   include `PAYMENT-RESPONSE` with the settlement result (tx hash / network /
   status), **including on 4xx/5xx responses** — if you took the money, you must
   confirm it, even when the business logic failed.
2. Recommend that servers **not settle before they can fulfill** (validate and
   be ready before capturing payment), and define a standard behavior for
   "settled but failed" (refund, or an explicit `settled: true, delivered:
   false` result) so clients can distinguish it from "not paid".
3. Advise clients (and SDKs) to treat **on-chain settlement, not the response
   header, as the source of truth** for whether a payment occurred, and to
   derive idempotency/skip logic from chain state.

## Note

We are preparing a public report on x402 endpoint quality that cites the 5/25
observed rate and recommends chain-anchored client design. We would welcome the
working group's view and offer a **7-day window** from the send date before
publication to review and respond.
