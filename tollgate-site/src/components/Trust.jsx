import { ShieldHalf, FileSignature, UserCheck, Landmark } from "lucide-react";
import { Reveal, RevealGroup, RevealItem } from "./Reveal.jsx";

const CONTROLS = [
  {
    Icon: ShieldHalf,
    k: "Deny-by-default",
    d: "An action that matches no policy rule is never improvised into an approval. Unrecognized spend stops and waits for a person. The safe failure is the default.",
  },
  {
    Icon: FileSignature,
    k: "Attestable audit trail",
    d: "Every denial and escalation emits a structured, signed record — who, what, why, when — with a content hash. Each decision is reconstructable and tamper-evident.",
  },
  {
    Icon: UserCheck,
    k: "Human-in-the-loop",
    d: "The system can stop money and ask for review. It cannot release a held payment on its own. Escalations route to a named approver, preserving segregation of duties.",
  },
  {
    Icon: Landmark,
    k: "Controls you can map to SOX",
    d: "Caps, allowlists, three-way match, and approval tiers express as testable controls. The mandate is your written assertion; the log is your evidence.",
  },
];

export function Trust() {
  return (
    <section id="controls" className="border-b border-line bg-base-sunk">
      <div className="shell py-section">
        <div className="grid gap-12 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <Reveal>
              <p className="eyebrow"><span className="dot bg-live" /> For the controls owner</p>
            </Reveal>
            <Reveal delay={0.05}>
              <h2 className="mt-4 font-display text-display-lg font-normal text-balance text-fg">
                Built to survive an audit, not just a demo.
              </h2>
            </Reveal>
            <Reveal delay={0.1}>
              <p className="mt-5 max-w-prose font-sans text-[1.02rem] leading-relaxed text-fg-muted">
                The point of a control isn’t that it’s clever. It’s that it holds, it’s documented,
                and someone is accountable when it fires. Tollgate is designed around what a
                controller has to be able to say “yes” to.
              </p>
            </Reveal>
            <Reveal delay={0.15}>
              <dl className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-sharp border border-line bg-line">
                <div className="bg-base-raised p-5">
                  <dt className="font-mono text-[0.64rem] uppercase tracking-wider text-fg-faint">
                    Decision floor
                  </dt>
                  <dd className="mt-1 font-display text-display-md text-fg">Deterministic</dd>
                </div>
                <div className="bg-base-raised p-5">
                  <dt className="font-mono text-[0.64rem] uppercase tracking-wider text-fg-faint">
                    AI authority
                  </dt>
                  <dd className="mt-1 font-display text-display-md text-live">Advisory</dd>
                </div>
              </dl>
            </Reveal>
          </div>

          <RevealGroup className="grid gap-px self-start overflow-hidden rounded-sharp border border-line bg-line sm:grid-cols-2 lg:col-span-7" stagger={0.07}>
            {CONTROLS.map((c) => (
              <RevealItem key={c.k} className="bg-base-raised p-6">
                <c.Icon className="h-5 w-5 text-live" strokeWidth={1.5} aria-hidden />
                <h3 className="mt-4 font-sans text-[1.15rem] font-medium text-fg">{c.k}</h3>
                <p className="mt-2.5 font-sans text-[0.9rem] leading-relaxed text-fg-muted">{c.d}</p>
              </RevealItem>
            ))}
          </RevealGroup>
        </div>
      </div>
    </section>
  );
}
