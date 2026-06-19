import { Reveal, RevealGroup, RevealItem } from "./Reveal.jsx";

const CONTROLS = [
  {
    k: "Deny-by-default",
    d: "An action that matches no policy rule is never improvised into an approval. Unrecognized spend stops and waits for a person. The safe failure is the default.",
  },
  {
    k: "Attestable audit trail",
    d: "Every denial and escalation emits a structured, signed record — who, what, why, when — with a content hash. Each decision is reconstructable and tamper-evident.",
  },
  {
    k: "Human-in-the-loop",
    d: "The system can stop money and ask for review. It cannot release a held payment on its own. Escalations route to a named approver, preserving segregation of duties.",
  },
  {
    k: "Maps to SOX controls",
    d: "Caps, allowlists, three-way match, and approval tiers express as testable controls. The mandate is your written assertion; the log is your evidence.",
  },
];

export function Trust() {
  return (
    <section id="controls" className="shell py-section">
      <div className="grid gap-12 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <Reveal>
            <p className="eyebrow text-plum">For the controls owner</p>
          </Reveal>
          <Reveal delay={0.05}>
            <h2 className="headline mt-6 text-heading-lg text-balance">
              Built to survive an audit, not just a demo.
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="mt-6 max-w-prose font-acronym text-body font-normal leading-relaxed text-ash">
              The point of a control isn’t that it’s clever. It’s that it holds, it’s documented, and
              someone is accountable when it fires. Tollgate is designed around what a controller has
              to be able to say “yes” to.
            </p>
          </Reveal>
          <Reveal delay={0.15}>
            <div className="mt-9 flex gap-10">
              <div>
                <div className="font-acronym text-caption uppercase tracking-[0.12em] text-smoke">
                  Decision floor
                </div>
                <div className="mt-2 font-acronym text-heading-sm font-extralight text-bone">
                  Deterministic
                </div>
              </div>
              <div>
                <div className="font-acronym text-caption uppercase tracking-[0.12em] text-smoke">
                  AI authority
                </div>
                <div className="mt-2 font-acronym text-heading-sm font-extralight text-plum">
                  Advisory
                </div>
              </div>
            </div>
          </Reveal>
        </div>

        <RevealGroup className="grid gap-5 sm:grid-cols-2 lg:col-span-7" stagger={0.08}>
          {CONTROLS.map((c) => (
            <RevealItem key={c.k}>
              <div className="outline-card h-full p-7">
                <div className="h-1.5 w-1.5 rounded-full bg-plum" />
                <h3 className="mt-5 font-acronym text-subheading font-semibold text-bone">{c.k}</h3>
                <p className="mt-3 font-acronym text-body-sm leading-relaxed text-ash">{c.d}</p>
              </div>
            </RevealItem>
          ))}
        </RevealGroup>
      </div>
    </section>
  );
}
