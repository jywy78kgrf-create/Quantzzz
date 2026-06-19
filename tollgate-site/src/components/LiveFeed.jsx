import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

const VENDORS = [
  "AWS", "Datadog", "Snowflake", "PagerDuty", "Fivetran", "dbt Labs",
  "Confluent", "GitHub", "Cvent", "LinkedIn Ads", "Marriott Events",
];
const CATS = ["cloud_infra", "observability", "data_whse", "pipeline", "dev_tooling", "advertising"];

const ESCALATE_REASONS = [
  "off-contract line item",
  "net-new tool, not a renewal",
  "12-month prepay > one period",
  "memo: injected approval claim",
  "purpose drift vs mandate",
];
const DENY_REASONS = [
  "vendor not on allowlist",
  "amount > per-PO cap",
  "duplicate within 45d window",
  "split: sub-cap POs > tier",
  "three-way match failed",
  "approver tier not met",
];

const STYLES = {
  ALLOW: "text-verdict-allow",
  DENY: "text-verdict-deny",
  ESCALATE: "text-verdict-escalate",
};
const DOT = {
  ALLOW: "bg-verdict-allow",
  DENY: "bg-verdict-deny",
  ESCALATE: "bg-verdict-escalate",
};

let SEQ = 48120;

function makeDecision() {
  // Weighted: mostly ALLOW, with a realistic minority stopped.
  const roll = Math.random();
  let verdict, layer, reason;
  if (roll < 0.7) {
    verdict = "ALLOW";
    layer = "gate+intent";
    reason = "within mandate";
  } else if (roll < 0.88) {
    verdict = "DENY";
    layer = "gate";
    reason = DENY_REASONS[(Math.random() * DENY_REASONS.length) | 0];
  } else {
    verdict = "ESCALATE";
    layer = "intent";
    reason = ESCALATE_REASONS[(Math.random() * ESCALATE_REASONS.length) | 0];
  }
  const vendor = VENDORS[(Math.random() * VENDORS.length) | 0];
  const amt = (Math.random() * 48000 + 800);
  const now = new Date();
  return {
    key: `${SEQ}-${Math.random().toString(36).slice(2, 6)}`,
    id: `PO-${SEQ++}`,
    ts: now.toLocaleTimeString("en-GB", { hour12: false }),
    vendor,
    cat: CATS[(Math.random() * CATS.length) | 0],
    amount: `$${Math.round(amt).toLocaleString("en-US")}`,
    verdict,
    layer,
    reason,
  };
}

const SEED = Array.from({ length: 7 }, makeDecision);

export function LiveFeed() {
  const reduce = useReducedMotion();
  const [rows, setRows] = useState(SEED);
  const paused = useRef(false);

  useEffect(() => {
    if (reduce) return;
    const tick = () => {
      if (!paused.current) {
        setRows((prev) => [makeDecision(), ...prev].slice(0, 8));
      }
    };
    const iv = setInterval(tick, 1500);
    return () => clearInterval(iv);
  }, [reduce]);

  return (
    <figure
      className="panel relative overflow-hidden shadow-panel"
      onMouseEnter={() => (paused.current = true)}
      onMouseLeave={() => (paused.current = false)}
    >
      {/* header */}
      <figcaption className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="flex items-center gap-2 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-fg">
          <span className="dot bg-verdict-allow animate-blink" />
          Live decision stream
        </span>
        <span className="font-mono text-[0.68rem] text-fg-faint">mandate&nbsp;FY26-INFRA</span>
      </figcaption>

      {/* scanline */}
      {!reduce && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-12 z-10 h-12 animate-scan bg-gradient-to-b from-transparent via-live/5 to-transparent"
        />
      )}

      {/* column header */}
      <div className="grid grid-cols-[auto_1fr_auto] gap-x-3 border-b border-line-faint bg-base-sunk/40 px-4 py-1.5 font-mono text-[0.6rem] uppercase tracking-wider text-fg-dim">
        <span>time · id</span>
        <span>vendor · reason</span>
        <span className="text-right">verdict</span>
      </div>

      {/* rows */}
      <ul className="relative divide-y divide-line-faint">
        <AnimatePresence initial={false}>
          {rows.map((r) => (
            <motion.li
              key={r.key}
              layout={!reduce}
              initial={reduce ? false : { opacity: 0, backgroundColor: "#3FD2C714" }}
              animate={{ opacity: 1, backgroundColor: "#00000000" }}
              exit={reduce ? {} : { opacity: 0, height: 0 }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 px-4 py-2.5"
            >
              <div className="font-mono text-[0.7rem] leading-tight text-fg-faint">
                <div>{r.ts}</div>
                <div className="text-fg-muted">{r.id}</div>
              </div>
              <div className="min-w-0">
                <div className="truncate font-mono text-[0.78rem] text-fg">{r.vendor}</div>
                <div className="truncate font-sans text-[0.74rem] text-fg-faint">{r.reason}</div>
              </div>
              <div className="flex items-center justify-end gap-2">
                <span className={`dot ${DOT[r.verdict]}`} />
                <span className={`font-mono text-[0.72rem] font-medium tracking-wide ${STYLES[r.verdict]}`}>
                  {r.verdict}
                </span>
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>

      <div className="border-t border-line bg-base-sunk/40 px-4 py-2">
        <p className="font-mono text-[0.62rem] leading-relaxed text-fg-dim">
          Synthetic stream, illustrative. Hover to pause. Every DENY/ESCALATE writes a signed record.
        </p>
      </div>
    </figure>
  );
}
