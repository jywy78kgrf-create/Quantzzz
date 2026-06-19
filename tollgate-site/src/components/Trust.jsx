import { ShieldHalf, FileSignature, UserCheck, Landmark } from "lucide-react";

const CONTROLS = [
  {
    Icon: ShieldHalf,
    k: "Deny-by-default",
    d: "An action that matches no policy rule is never improvised into an approval. Unrecognized spend stops and waits for a person. The safe failure is the default failure.",
  },
  {
    Icon: FileSignature,
    k: "Attestable audit trail",
    d: "Every denial and escalation emits a structured, signed record — who, what, why, when — with a content hash. After the fact, each decision is reconstructable and tamper-evident.",
  },
  {
    Icon: UserCheck,
    k: "Human-in-the-loop",
    d: "The system can stop money and can ask for review. It cannot release a held payment on its own. Escalations route to a named approver, preserving segregation of duties.",
  },
  {
    Icon: Landmark,
    k: "Controls you can map to SOX",
    d: "Caps, allowlists, three-way match, and approval tiers express as testable controls. The mandate is your written assertion; the log is your evidence.",
  },
];

export function Trust() {
  return (
    <section id="controls" className="border-t border-line bg-ink text-paper">
      <div className="shell py-section">
        <div className="grid gap-12 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <p className="reveal font-mono text-eyebrow uppercase tracking-[0.14em] text-signal">
              For the controls owner
            </p>
            <h2 className="reveal mt-4 font-display text-display-lg font-normal text-paper">
              Built to survive an audit, not just a demo.
            </h2>
            <p className="reveal mt-5 max-w-prose font-sans text-[1.02rem] leading-relaxed text-paper/70">
              The point of a control isn’t that it’s clever. It’s that it holds, it’s
              documented, and someone is accountable when it fires. Tollgate is designed
              around the things a controller has to be able to say “yes” to.
            </p>
            <dl className="reveal mt-8 grid grid-cols-2 gap-6 border-t border-line-dark pt-7">
              <div>
                <dt className="font-mono text-[0.7rem] uppercase tracking-wider text-paper/45">
                  Decision floor
                </dt>
                <dd className="mt-1 font-display text-display-md text-paper">Deterministic</dd>
              </div>
              <div>
                <dt className="font-mono text-[0.7rem] uppercase tracking-wider text-paper/45">
                  AI authority
                </dt>
                <dd className="mt-1 font-display text-display-md text-paper">Advisory only</dd>
              </div>
            </dl>
          </div>

          <div className="lg:col-span-7">
            <div className="grid gap-px overflow-hidden rounded-sharp border border-line-dark bg-line-dark sm:grid-cols-2">
              {CONTROLS.map((c) => (
                <div key={c.k} className="reveal bg-ink p-6">
                  <c.Icon className="h-5 w-5 text-signal" strokeWidth={1.5} aria-hidden />
                  <h3 className="mt-4 font-display text-[1.3rem] font-normal text-paper">{c.k}</h3>
                  <p className="mt-2.5 font-sans text-[0.9rem] leading-relaxed text-paper/65">
                    {c.d}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
