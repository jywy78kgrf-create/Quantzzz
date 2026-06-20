# Honest-mistake seed taxonomy (plain English)

These are **honest errors / off-policy slips**, NOT deliberate fraud or
adversarial evasion. Think: a tired analyst, a miskeyed field, a vendor onboarded
without updating a list, a purchase coded to the wrong bucket. The seed cases
built from this taxonomy are injected into the real haystack and labeled; the
firewall should catch them while leaving the real legitimate spend alone.

Domain: U.S. federal IT systems-design contracts (NAICS 541512), FY2024. The
governing mandate funds IT systems-design / engineering / O&M services from
approved IT vendors, under a per-award cap, in USD.

## Error types

- **E1 — amount just over the cap.** A normal-looking IT services award whose
  amount lands a bit above the per-award cap (honest scope creep or a keying
  error). Everything else is fine.
- **E2 — vendor not on the approved list.** A plausible, real-sounding IT
  services firm that simply isn't on the approved-vendor list yet (a smaller or
  newly engaged contractor onboarded before the list was updated).
- **E3 — wrong spend category.** An award miscoded to a category that isn't IT
  systems design (e.g. construction, office supplies, vehicles), an honest
  miscategorization at data entry.
- **E4 — duplicate of an existing award.** A near-duplicate of a real award
  already in the data — same vendor, same amount, same or barely-changed award
  identifier, entered a second time (honest double-submission).
- **E5 — off-objective purpose, correctly coded otherwise.** The hardest and most
  important: an award from an approved vendor, coded to the right IT category,
  under the cap, with valid fields — but the **description** makes clear the money
  is for something the mandate does not fund (office furniture, employee
  relocation/travel, building construction, fleet vehicles, catering/event
  space). An honest "the vendor does IT so I coded it IT" slip where the actual
  work isn't IT systems design. Quantitatively flawless; only the stated purpose
  is wrong.
- **E6 — wrong currency.** An otherwise-fine award recorded in a non-USD currency
  (e.g. a foreign-office payment miskeyed against this USD mandate).

## What "caught" means

The firewall returns ALLOW / DENY / ESCALATE. A seed is "caught" if the verdict
is DENY or ESCALATE. E1–E4 and E6 should be caught by the deterministic gate;
E5 can only be caught by the semantic judge (it passes every quantitative rule).
