# Send checklist — x402 audit disclosures

Prepared 2026-07-03. **Nothing here has been sent.** This file tells you exactly
where each disclosure goes, in what format, and in what order. Fill in the
day-0 date when you send, and the 7-day window is measured from it.

## Day-0 send date: ____________  (window closes: day-0 + 7 = ____________)

## Routing summary

| # | Finding | Recipient | Channel | Format file | Notes |
|---|---|---|---|---|---|
| 1 | x402scan 3× aggregate inflation | Merit Systems | **Private DM** (Discord or X) now → public GitHub issue + PR at day 7 | `01-x402scan-DM.md`, `01-x402scan-github-issue.md` | Not a security vuln; DM keeps the window intact since a public issue = immediate disclosure |
| 2 | x402-fetch silent maxValue cap bypass | Coinbase | **HackerOne** `hackerone.com/coinbase` | `02-x402-fetch-hackerone.md` | Coinbase policy: security → HackerOne, no public tickets. Funds-loss footgun qualifies. |
| 3 | basetomcat paid-500 DB-error leak | (operator) | **No reachable contact found** | `03-basetomcat-NO-CONTACT.md` | Meme-presale site, no contact channel. Recommend: anonymize in report; do not name. |
| 4 | Headerless settlement (spec gap) | Coinbase | **HackerOne** (funds-loss report) + optional public spec proposal | `04-x402-spec-hackerone.md`, `04-x402-spec-github-proposal.md` | Money-loss angle → HackerOne per policy; the MUST-header fix can also be a public design proposal |

## Order of operations

1. **Day 0 — send the private/coordinated notices:**
   - #1: DM Merit Systems (Discord `discord.gg/JuKt7tPnNc` or X `@merit_systems`) — text in `01-x402scan-DM.md`.
   - #2: submit HackerOne report — text in `02-x402-fetch-hackerone.md`.
   - #4: submit HackerOne report — text in `04-x402-spec-hackerone.md`.
   - #3: nothing to send (no contact). Decision: anonymize in report (default).
   - Record the date above.
2. **Days 0–7 — hold everything public.** Fold in any responses/fixes. **Do not
   open the PRs** (opening a PR is public disclosure).
3. **Day 7+ — publish:**
   - Open the two PRs (`../patches/`), timed with publication.
   - File #1's public GitHub issue (`01-x402scan-github-issue.md`) and, if you
     choose, #4's public spec proposal (`04-x402-spec-github-proposal.md`).
   - Publish the report.
   - If a recipient shipped a fix in the window, change the finding to
     "reported privately; fixed in <ref> on <date>" rather than removing it.

## Judgment calls to make before sending

- **#2 / #4 via HackerOne may be closed as "informative"** (a deprecated-package
  footgun and a spec-wording proposal are borderline for a bug bounty). That's
  fine — it's the courteous, policy-respecting channel, and it still creates a
  timestamped private notice. If you'd rather, #4's fix is legitimately a public
  design discussion and could skip HackerOne and go straight to a spec proposal.
- **#3 has no owner to notify.** The clean, fair choice is to describe the
  *pattern* (paid 500 leaking an internal DB error) in the report without naming
  basetomcat, since we cannot give them a chance to respond. Naming an
  un-notifiable operator is the one move that would read as a cheap shot.
- **Identity/reply-to:** all of these ask for a response. Send from an address /
  account you monitor for the next 2+ weeks.
