import { Reveal } from "./Reveal.jsx";

function LayerCard({ tag, dotClass, title, lead, points, footer }) {
  return (
    <Reveal className="outline-card flex h-full flex-col p-8">
      <span className="inline-flex items-center gap-2.5 font-acronym text-caption uppercase tracking-[0.14em] text-smoke">
        <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} /> {tag}
      </span>
      <h3 className="mt-5 font-acronym text-heading font-extralight text-bone">{title}</h3>
      <p className="mt-4 font-acronym text-body font-normal leading-relaxed text-ash">{lead}</p>
      <ul className="mt-6 space-y-3.5 border-t border-hair pt-6">
        {points.map((p) => (
          <li key={p} className="flex gap-3 font-acronym text-body-sm leading-relaxed text-bone">
            <span aria-hidden className="mt-2 h-px w-4 shrink-0 bg-plum" />
            <span>{p}</span>
          </li>
        ))}
      </ul>
      <p className="mt-7 font-acronym text-body-sm italic leading-relaxed text-smoke">{footer}</p>
    </Reveal>
  );
}

export function HowItWorks() {
  return (
    <section id="how" className="shell py-section">
      <div className="max-w-prose">
        <Reveal>
          <p className="eyebrow text-plum">Architecture</p>
        </Reveal>
        <Reveal delay={0.05}>
          <h2 className="headline mt-6 text-heading-lg text-balance">
            Two layers, deliberately different materials.
          </h2>
        </Reveal>
        <Reveal delay={0.1}>
          <p className="mt-6 font-acronym text-subheading font-normal text-ash">
            The floor is deterministic and unbypassable. The intelligence sits above it and is
            strictly advisory — it can ask a human to look, but it can never approve, and it can
            never overturn a denial.
          </p>
        </Reveal>
      </div>

      <div className="mt-14 grid gap-5 lg:grid-cols-2">
        <LayerCard
          tag="Layer 1 — Deterministic gate"
          dotClass="bg-bone"
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
          dotClass="bg-plum"
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
    </section>
  );
}
