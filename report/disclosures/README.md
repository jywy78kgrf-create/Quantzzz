# Disclosure drafts — NOT SENT

These four documents are **drafts prepared for review**. None has been sent.
No recipient has been contacted. Sending requires explicit authorization.

| # | Recipient | Finding | Report handling |
|---|---|---|---|
| 01 | Merit Systems (x402scan) | Seller-aggregate inflation ~3× (unnest-before-SUM); $154.8M→$51.9M | Named in report; corrected values used |
| 02 | x402-fetch / x402 maintainers (Coinbase) | v2 402-body parse failure (40% of attempts) + silent `maxValue` cap footgun | Named in report |
| 03 | basetomcat.com operator | Paid 500 leaking internal DB auth error | **Withheld from report** unless unresponsive |
| 04 | x402 spec working group | Headerless settlement (5/25); mandate `X-PAYMENT-RESPONSE` | Pattern cited in report §7.1 |

Each draft states a **7-day review window** from its send date before
publication. Coordinate send timing so the report is not published inside any
open window.

## Disclosure timeline (the order these must happen)

Apply the 7-day window **uniformly to all four**, even the findings that are
courtesy rather than security — one policy applied evenly is the defensible
posture. The sequence:

1. **Notify (day 0).** Send all four disclosures privately on the same day.
   Record the send date; the window runs 7 days from it.
2. **Window (days 0–7).** Hold everything public. Incorporate any corrections
   or fixes the recipients send back (this is also a last accuracy check on our
   own claims). Do **not** open the PRs yet — opening a PR is itself public
   disclosure and would break the window.
3. **Publish (day 7+).** After the window closes: open the two PRs
   (`patches/`), publish the report, and — only if the basetomcat operator (#03)
   did not respond — decide whether to name that endpoint.

Key constraint: **a PR cannot be embargoed.** Filing it publishes the finding
immediately, so the x402scan and x402-fetch PRs are day-7 actions, timed to land
with (not before) publication.

If a recipient ships a fix inside the window, note it in the report rather than
removing the finding — "reported privately; fixed in <ref> on <date>" is the
strongest possible version of a finding.
