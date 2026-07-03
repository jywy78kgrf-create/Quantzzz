# Disclosure draft — paid endpoint leaks internal database error

**To:** operator of the endpoint below (contact TBD — see "Identification")
**Status:** DRAFT — not sent. Do not send without explicit authorization.
**Severity:** Information disclosure + charge-on-failure
**Handling:** Per instruction, this operator is **not named in the public
report** unless they are unresponsive after the disclosure window.

## Summary

The endpoint charges an x402 payment and then, on an internal failure, returns
an HTTP 500 whose body discloses a backend **database-authentication error**.
The payment settles on-chain regardless of the failure, so a buyer is charged
for an error response that also leaks internal infrastructure detail.

## Endpoint

- URL: `https://basetomcat.com/api/mint-experience`
- Listed: "Buy 50 TOM (experience tier) for 0.01 USDC on Base."
- Observed: payment settled on Base (tx
  `0x4f67c2047dbf14a4dc483299a5984333c92b1f24d3ee16f87d0ece6a90523ff2`), <!-- public on-chain tx hash, not-a-key -->
  response **HTTP 500** with body:

```json
{"error":"Failed to create transfer task: Authentication failed against
database server, the provided database credentials for `(not available)` are
not valid. Please make sure to provide valid database credentials for the
database server at the configured address."}
```

The literal credential value is not present (it renders as `(not available)`),
so no secret string was exposed to us; what leaks is the backend architecture
and error state (a Prisma-style database auth failure) surfaced verbatim to a
paying, unauthenticated client. The more serious issue for your users is that
**the payment is taken before the backend can fulfill**, so the buyer pays for a
500.

## Reproduction

Send a paid x402 request to the URL above (0.01 USDC on Base). The payment
settles; the response is the 500 body shown. Observed 2026-07-03.

## Proposed fix

1. Do not settle payment until the backend operation can succeed (validate
   inputs and reach the database *before* accepting the x402 payment), or refund
   / do not capture on internal failure.
2. Return a generic error body to clients; log the detailed database error
   server-side only. Never surface database/connection errors to the caller.

## Note

We are preparing a public report on x402 endpoint quality. We are contacting you
privately first and will **withhold your identity from the report** provided you
respond within a **7-day window** from the send date; the report will describe
the *pattern* (paid 500 leaking an internal DB error) without naming the
endpoint. If we cannot reach you or receive no response in that window, we may
name the endpoint as an unremediated example.
