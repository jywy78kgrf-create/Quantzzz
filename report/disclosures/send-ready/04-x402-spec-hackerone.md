# #4 Headerless settlement — Coinbase HackerOne (+ optional public spec proposal)

Two routes; pick per the checklist. The money-loss observation fits Coinbase's
"security → HackerOne" policy; the spec-wording fix is also a legitimate public
design proposal (`04-x402-spec-github-proposal.md`).

## Route A — HackerOne (https://hackerone.com/coinbase)

**Title:**
```
x402 spec: settlement confirmation (PAYMENT-RESPONSE) not required, enabling silent double-charge
```

**Weakness:** Insufficient protocol guarantee → duplicate/unconfirmed payment
(financial impact).

**Write-up (paste):**
```markdown
## Summary
The x402 v2 HTTP transport spec (`specs/transports-v2/http.md`) says only
"Servers communicate payment settlement results using the `PAYMENT-RESPONSE`
header." It uses no RFC-2119 keyword (no MUST/SHOULD) and does not address the
case where a payment settles but the server returns a non-2xx status. As a
result, servers can (and do) settle a payment on-chain while returning no
PAYMENT-RESPONSE header — sometimes with a 200 success body, sometimes with a
400/500 after taking the money.

## Impact
A paying client cannot tell from the response that it paid. The payment looks
unconfirmed or failed while funds have moved, and standard retry-on-failure
logic pays again. In a 75-endpoint measurement, 5 of 25 endpoints that settled
on-chain returned no PAYMENT-RESPONSE header; a client keying its "already paid"
state on that header re-paid 4 of them on a second run. (We caught it only by
reconciling against on-chain transfers.)

## Reproduction
Pay any affected endpoint and compare response headers to the on-chain USDC
transfer from the payer wallet, e.g. `https://www.qrbase.xyz/api/x402/ping`
(HTTP 200, body claims success, no PAYMENT-RESPONSE header, transfer present).

## Proposed fix
1. Make PAYMENT-RESPONSE normative: any response to a request whose payment
   settled MUST include it — including on 4xx/5xx.
2. Define "settled but failed" behavior (refund, or an explicit settled=true,
   delivered=false result) so clients can distinguish it from "not paid."
3. Advise clients/SDKs to treat on-chain settlement, not the header, as the
   source of truth and to derive idempotency from chain state.

I plan to reference this in a public report in ~7 days and would welcome your
view first.
```

## Route B
See `04-x402-spec-github-proposal.md` for a public spec-improvement issue if you
prefer to raise the fix openly rather than (or in addition to) HackerOne.
