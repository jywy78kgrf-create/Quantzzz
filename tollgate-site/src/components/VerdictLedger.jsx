import { motion, useReducedMotion } from "framer-motion";

const ROWS = [
  {
    id: "PO-48117",
    vendor: "Approved cloud vendor",
    amount: "$42,000",
    verdict: "ALLOW",
    layer: "gate + intent",
    note: "On-contract renewal, within cap, approvals present.",
  },
  {
    id: "PO-48119",
    vendor: "Approved cloud vendor",
    amount: "$9,800 ×3",
    verdict: "DENY",
    layer: "gate",
    note: "Three sub-cap POs in 48h sum past the $25k approval tier.",
  },
  {
    id: "INV-90042",
    vendor: "Approved SaaS vendor",
    amount: "$17,500",
    verdict: "ESCALATE",
    layer: "intent",
    note: "On allowlist, under cap — line item is off-contract. Routed to a human.",
  },
];

const STYLES = {
  ALLOW: "text-verdict-allow border-verdict-allow/30 bg-verdict-allow/5",
  DENY: "text-verdict-deny border-verdict-deny/30 bg-verdict-deny/5",
  ESCALATE: "text-verdict-escalate border-verdict-escalate/30 bg-verdict-escalate/5",
};

export function VerdictLedger() {
  const reduce = useReducedMotion();
  return (
    <figure className="relative overflow-hidden rounded-sharp border border-line bg-paper-raised shadow-panel">
      <figcaption className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="font-mono text-[0.7rem] uppercase tracking-[0.12em] text-ink-muted">
          PO log · live decisions
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[0.7rem] text-ink-faint">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-verdict-allow" />
          mandate&nbsp;FY26-INFRA
        </span>
      </figcaption>

      <motion.ul
        className="relative divide-y divide-line"
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "0px 0px -15% 0px" }}
        variants={{ show: { transition: { staggerChildren: reduce ? 0 : 0.55, delayChildren: 0.2 } } }}
      >
        {/* scanning hairline that sweeps the ledger once */}
        {!reduce && (
          <motion.span
            aria-hidden
            className="pointer-events-none absolute inset-x-0 z-10 h-px bg-signal/60"
            initial={{ top: 0, opacity: 0 }}
            whileInView={{ top: "100%", opacity: [0, 1, 1, 0] }}
            viewport={{ once: true }}
            transition={{ duration: 1.7, ease: "easeInOut" }}
          />
        )}

        {ROWS.map((r) => (
          <li key={r.id} className="grid grid-cols-[1fr_auto] gap-x-4 px-4 py-3.5">
            <div className="min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[0.8rem] text-ink">{r.id}</span>
                <span className="truncate font-sans text-[0.8rem] text-ink-muted">{r.vendor}</span>
              </div>
              <p className="mt-1 font-sans text-[0.8rem] leading-snug text-ink-muted">{r.note}</p>
            </div>
            <div className="flex flex-col items-end gap-1.5">
              <span className="font-mono text-[0.85rem] text-ink">{r.amount}</span>
              <motion.span
                variants={{
                  hidden: reduce ? {} : { opacity: 0, scale: 0.85 },
                  show: { opacity: 1, scale: 1, transition: { type: "spring", stiffness: 420, damping: 22 } },
                }}
                className={`rounded-sharp border px-2 py-0.5 font-mono text-[0.68rem] font-medium tracking-wide ${STYLES[r.verdict]}`}
              >
                {r.verdict}
              </motion.span>
              <span className="font-mono text-[0.62rem] uppercase tracking-wider text-ink-faint">
                {r.layer}
              </span>
            </div>
          </li>
        ))}
      </motion.ul>

      <div className="border-t border-line bg-paper-sunk px-4 py-2.5">
        <p className="font-mono text-[0.66rem] leading-relaxed text-ink-faint">
          Illustrative. Every DENY/ESCALATE writes a signed who/what/why/when record.
        </p>
      </div>
    </figure>
  );
}
