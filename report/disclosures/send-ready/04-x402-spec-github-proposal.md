# #4 Headerless settlement — public spec proposal (optional; file at day 7)

**Repo:** github.com/coinbase/x402/issues/new — only if you choose the public
route in addition to / instead of HackerOne. File at day 7, not before.

**Title:**
```
Spec: require PAYMENT-RESPONSE on all settled payments, including error responses
```

**Body:**
```markdown
### Motivation
`specs/transports-v2/http.md` currently states only: "Servers communicate payment
settlement results using the `PAYMENT-RESPONSE` header." There is no RFC-2119
keyword, and no guidance for the case where a payment settles but the server
returns a non-2xx status.

In practice this lets servers settle a payment on-chain while returning no
PAYMENT-RESPONSE header (observed: some 200 with a success body, some 400/500
after charging). A paying client then cannot confirm payment from the response;
the payment looks failed while funds moved, and retry logic double-pays. In a
recent 75-endpoint measurement, 5 of 25 endpoints that settled on-chain returned
no PAYMENT-RESPONSE header.

### Proposal
1. A response to a request whose payment settled **MUST** include
   `PAYMENT-RESPONSE` with the settlement result, **including on 4xx/5xx**.
2. Define standard "settled but not delivered" semantics (refund, or an explicit
   `settled: true, delivered: false`) so clients can distinguish it from
   "not paid."
3. Recommend clients treat on-chain settlement (not the header) as the source of
   truth for idempotency.

Happy to open a PR against the spec text if the direction is agreeable.
```
