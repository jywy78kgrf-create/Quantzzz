import { Reveal } from "./Reveal.jsx";

function FlowStrip() {
  const steps = [
    { k: "Transaction", s: "PO or invoice from the agent", dot: "bg-fg-muted" },
    { k: "Deterministic gate", s: "Hard limits · DENY is final", dot: "bg-verdict-deny" },
    { k: "Advisory judge", s: "Intent check · escalate only", dot: "bg-verdict-escalate" },
    { k: "Verdict", s: "Allow · Deny · Escalate", dot: "bg-verdict-allow" },
  ];
  return (
    <Reveal className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-sharp border border-line bg-line sm:grid-cols-4">
      {steps.map((st, i) => (
        <div key={st.k} className="bg-base-raised px-5 py-5">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[0.66rem] text-fg-dim">{`0${i + 1}`}</span>
            <span className={`dot ${st.dot}`} />
          </div>
          <div className="mt-3 font-sans text-[1.05rem] font-medium text-fg">{st.k}</div>
          <p className="mt-1 font-mono text-[0.72rem] leading-snug text-fg-faint">{st.s}</p>
        </div>
      ))}
    </Reveal>
  );
}

function LayerCard({ tag, dot, title, lead, points, footer }) {
  return (
    <Reveal className="flex h-full flex-col rounded-sharp border border-line bg-base-raised p-7">
      <span className="flex items-center gap-2 font-mono text-[0.66rem] uppercase tracking-[0.14em] text-fg-faint">
        <span className={`dot ${dot}`} /> {tag}
      </span>
      <h3 className="mt-4 font-display text-display-md font-normal text-fg">{title}</h3>
      <p className="mt-3 font-sans text-[0.95rem] leading-relaxed text-fg-muted">{lead}</p>
      <ul className="mt-5 space-y-3 border-t border-line pt-5">
        {points.map((p) => (
          <li key={p} className="flex gap-3 font-sans text-[0.9rem] leading-relaxed text-fg">
            <span aria-hidden className="mt-2 h-px w-4 shrink-0 bg-live" />
            <span>{p}</span>
          </li>
        ))}
      </ul>
      <p className="mt-6 font-sans text-[0.82rem] italic leading-relaxed text-fg-muted">{footer}</p>
    </Reveal>
  );
}

export function HowItWorks() {
  return (
    <section id="how" className="border-b border-line bg-grid">
      <div className="shell py-section">
        <div className="max-w-prose">
          <Reveal>
            <p className="eyebrow"><span className="dot bg-live" /> Architecture</p>
          </Reveal>
          <Reveal delay={0.05}>
            <h2 className="mt-4 font-display text-display-lg font-normal text-balance text-fg">
              Two layers, deliberately different materials.
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="mt-5 font-sans text-lede text-fg-muted">
              The floor is deterministic and unbypassable. The intelligence sits above it and is
              strictly advisory — it can ask a human to look, but it can never approve, and it can
              never overturn a denial.
            </p>
          </Reveal>
        </div>

        <FlowStrip />

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <LayerCard
            tag="Layer 1 — Deterministic gate"
            dot="bg-verdict-deny"
            title="Hard limits that cannot be argued with."
            lead="Pure evaluation of the quantifiable facts. No model, no reasoning, no free text. A DENY is final and attributable."
            points={[
              "Amount caps, vendor and category allowlists, approval tiers.",
              "Duplicate, split/structuring, and rate-limit detection across the window.",
              "Three-way match: PO ↔ receipt ↔ invoice must agree.",
              "Policy lives in a mandate config — the gate code never changes per customer.",
            ]}
            footer="This layer does the heavy lifting. It is exact, and it is the part you attest to."
          />
          <LayerCard
            tag="Layer 2 — Advisory judge"
            dot="bg-verdict-escalate"
            title="An intent check for what the numbers can’t see."
            lead="Reads the action against your mandate’s stated purpose and flags off-objective intent that clears every quantitative rule. Hardened against instructions hidden in memos."
            points={[
              "Catches off-contract purpose, scope creep, and net-new spend posing as renewal.",
              "Treats every memo as untrusted — it will not follow injected instructions.",
              "Returns one of two outcomes: pass, or escalate to a human. Never approve.",
              "Advisory by design: it cannot loosen a single deterministic control.",
            ]}
            footer="We don’t ask you to trust the AI with the decision. We ask it only to raise a hand."
          />
        </div>
      </div>
    </section>
  );
}
