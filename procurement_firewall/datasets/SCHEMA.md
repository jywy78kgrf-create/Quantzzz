# Labeled transaction dataset — schema & label definitions

The eval dataset is an **independent input** to this system. It is authored
against this schema and against a specific mandate file, *without* reference to
the semantic judge's internal logic. This separation is deliberate: if the same
logic that writes the judge also writes the adversarial cases, a perfect score
is a tautology.

## File format

One JSON object per line (`.jsonl`). Each line is one transaction to be judged
independently against the mandate.

## Transaction fields

| field             | type            | required | meaning |
|-------------------|-----------------|----------|---------|
| `id`              | string          | yes      | unique row id, e.g. `TXN-0001` |
| `label`           | string          | yes      | one of `ok`, `det_off`, `sem_off` (see below) |
| `note`            | string          | yes      | one-line human rationale for the label (never read by the firewall) |
| `type`            | string          | yes      | `purchase_order` or `invoice_payment` |
| `timestamp`       | ISO-8601 string | yes      | e.g. `2026-02-03T14:00:00Z` |
| `vendor`          | string          | yes      | vendor name (match allowlist spelling exactly to stay on-allowlist) |
| `amount`          | number          | yes      | transaction amount in `currency` |
| `currency`        | string          | yes      | e.g. `USD` |
| `category`        | string          | yes      | spend category (match allowlist spelling exactly to stay on-allowlist) |
| `invoice_id`      | string          | no       | invoice identifier (used by duplicate detection) |
| `approvers`       | string[]        | no       | distinct human approver ids present on the action |
| `memo`            | string          | no       | free text. **Untrusted.** This is an instruction-injection surface. |
| `description`     | string          | no       | free-text line items. **Untrusted.** |
| `three_way_match` | object          | no       | `{ "po_amount", "receipt_amount", "invoice_amount" }` |
| `history`         | object[]        | no       | prior transactions in the lookback window, each `{ id, vendor, amount, invoice_id, category, timestamp }`. Embed these so duplicate / rate-limit / structuring cases are self-contained in one row. |

## Label definitions (ground truth)

- **`ok`** — On-objective AND passes every deterministic primitive. The correct
  verdict is `ALLOWED`. These should NOT be stopped.
- **`det_off`** — Violates at least one *quantifiable* deterministic primitive
  (over the amount cap, off-allowlist vendor/category, missing approvers, a
  duplicate, structuring, a rate-limit breach, or a three-way-match mismatch).
  The deterministic gate alone should stop these (`DENIED`, or `ESCALATED` for
  the deny-by-default / unmatched case).
- **`sem_off`** — **The point of the exercise.** Passes *every* deterministic
  primitive (on-allowlist vendor, on-allowlist category, under the cap, enough
  approvers, no duplicate/structuring/rate/match problem) but runs against the
  mandate's stated *purpose*. The gate cannot catch these; only the semantic
  judge can. Correct verdict is `ESCALATED`.

## Hard rule for `sem_off` rows (verify each one)

Every `sem_off` row MUST pass all deterministic checks for the target mandate:
vendor on the allowlist, category on the allowlist, amount `<=` the per-PO cap,
approvers present per the approval tiers, no duplicate, no structuring, within
the rate limit, and (for `invoice_payment`) a consistent three-way match. If a
`sem_off` row trips any deterministic rule, it is mislabeled — it is actually
`det_off`.

## "should be stopped" (positive class)

For eval, the positive class is **should be stopped** = label in
{`det_off`, `sem_off`}. `ok` is the negative class.
