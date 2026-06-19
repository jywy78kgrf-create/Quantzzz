function FlowStrip() {
  const steps = [
    { k: "Transaction", s: "PO or invoice from the agent", tone: "ink" },
    { k: "Gate", s: "Hard limits · DENY is final", tone: "deny" },
    { k: "Judge", s: "Intent check · advisory only", tone: "escalate" },
    { k: "Verdict", s: "Allow · Deny · Escalate", tone: "allow" },
  ];
  const dot = {
    ink: "bg-ink",
    deny: "bg-verdict-deny",
    escalate: "bg-verdict-escalate",
    allow: "bg-verdict-allow",
  };
  return (
    <div className="reveal mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-sharp border border-line bg-line sm:grid-cols-4">
      {steps.map((st, i) => (
        <div key={st.k} className="relative bg-paper-raised px-5 py-5">
          <span className="font-mono text-[0.7rem] text-ink-faint">0{i + 1}</span>
          <div className="mt-2 flex items-center gap-2">
            <span className={`inline-block h-2 w-2 rounded-full ${dot[st.tone]}`} />
            <span className="font-display text-[1.15rem] text-ink">{st.k}</span>
          </div>
          <p className="mt-1.5 font-sans text-[0.82rem] leading-snug text-ink-muted">{st.s}</p>
        </div>
      ))}
    </div>
  );
}

function LayerCard({ tag, title, lead, points, footer }) {
  return (
    <article className="reveal flex flex-col rounded-sharp border border-line bg-paper-raised p-7">
      <span className="font-mono text-[0.7rem] uppercase tracking-[0.14em] text-signal">{tag}</span>
      <h3 className="mt-3 font-display text-display-md font-normal text-ink">{title}</h3>
      <p className="mt-3 font-sans text-[0.95rem] leading-relaxed text-ink-muted">{lead}</p>
      <ul className="mt-5 space-y-3 border-t border-line pt-5">
        {points.map((p) => (
          <li key={p} className="flex gap-3 font-sans text-[0.9rem] leading-relaxed text-ink-soft">
            <span aria-hidden className="mt-2 h-px w-4 shrink-0 bg-signal" />
            <span>{p}</span>
          </li>
        ))}
      </ul>
      <p className="mt-6 font-sans text-[0.82rem] italic leading-relaxed text-ink-muted">{footer}</p>
    </article>
  );
}

export function HowItWorks() {
  return (
    <section id="how" className="border-t border-line">
      <div className="shell py-section">
        <div className="max-w-prose">
          <p className="eyebrow reveal">How it works</p>
          <h2 className="mt-4 font-display text-display-lg font-normal text-ink reveal">
            Two layers, built from deliberately different materials.
          </h2>
          <p className="mt-5 font-sans text-lede text-ink-muted reveal">
            The floor is deterministic and unbypassable. The intelligence sits above it and is
            strictly advisory — it can ask a human to look, but it can never approve, and it can
            never overturn a denial.
          </p>
        </div>

        <FlowStrip />

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <LayerCard
            tag="Layer 1 — Deterministic gate"
            title="Hard limits that cannot be argued with."
            lead="Pure evaluation of the quantifiable facts. No model, no reasoning, no free text. A DENY is final and attributable."
            points={[
              "Amount caps, vendor and category allowlists, approval tiers.",
              "Duplicate, split/structuring, and rate-limit detection across the window.",
              "Three-way match: PO ↔ receipt ↔ invoice must agree.",
              "Policy lives in a mandate config — the gate code never changes per customer.",
            ]}
            footer="This layer does the heavy lifting. It is exact, and it is the part you can attest to."
          />
          <LayerCard
            tag="Layer 2 — Advisory judge"
            title="An intent check for what the numbers can’t see."
            lead="Reads the action against your mandate’s stated purpose and flags off-objective intent that clears every quantitative rule. Hardened against instructions hidden in memos."
            points={[
              "Catches off-contract purpose, scope creep, and net-new spend disguised as renewal.",
              "Treats every memo and description as untrusted — it will not follow injected instructions.",
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
