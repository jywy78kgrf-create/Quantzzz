# #3 basetomcat — NO REACHABLE CONTACT (action required: decide)

**Status:** Cannot send. No contact channel found.

## What we found
`basetomcat.com` describes itself as "a meme presale powered by fully automated
payments, Base-native settlement, and unapologetic cartoon chaos." The site
lists **no email, Discord, Telegram, GitHub, or its own X handle** — only
references to `@base` and `@x402scan` as tech partners. There is no vulnerability
contact and no operator identity to notify.

## The finding (unchanged)
`https://basetomcat.com/api/mint-experience` settles an x402 payment and then, on
failure, returns HTTP 500 whose body exposes an internal Prisma-style database
authentication error. Payment is taken before the backend can fulfill, so a
buyer is charged for the error. (No literal secret value was exposed; it rendered
as `(not available)`.) Tx:
`0x4f67c2047dbf14a4dc483299a5984333c92b1f24d3ee16f87d0ece6a90523ff2`. <!-- public tx hash, not-a-key -->

## Recommendation
Because we cannot give the operator a chance to respond, the fair and defensible
choice is to **describe the pattern anonymously in the report and not name the
endpoint** — this is already the report's default handling (§7.2 describes
"paid 500 leaking an internal database error" without naming it). Naming an
un-notifiable operator is the one move that would read as a cheap shot rather
than research.

## If you still want to try to notify
Options, none reliable:
- Reply to / DM whatever X account the presale posts from (we could not identify
  it from the site; you may find it via the site's live socials).
- Post a note via `@x402scan` or the Bazaar listing, since the service is listed
  there, asking them to relay to the operator.

Absent a response, keep it anonymized. **Decision needed from you: anonymize
(recommended) or attempt one of the above.**
