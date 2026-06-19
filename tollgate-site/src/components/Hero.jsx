import { VerdictLedger } from "./VerdictLedger.jsx";

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden">
      {/* faint editorial grid lines, not decoration-for-decoration's-sake */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.5]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #d9d0bd55 1px, transparent 1px)",
          backgroundSize: "calc(100%/3) 100%",
          maskImage: "linear-gradient(to bottom, #000 0, transparent 70%)",
        }}
      />
      <div className="shell relative grid gap-12 pt-16 pb-section lg:grid-cols-12 lg:gap-10 lg:pt-24">
        <div className="lg:col-span-7">
          <p className="eyebrow animate-rise">Control layer for agentic procurement</p>
          <h1 className="mt-5 max-w-[18ch] font-display text-display-xl font-normal text-ink animate-rise">
            Your agents stay <span className="italic text-signal">within every limit</span> and
            still spend off-objective.
          </h1>
          <p className="mt-6 max-w-prose font-sans text-lede text-ink-muted animate-rise">
            Duplicate payments. POs split to slip under an approval cap. An approved vendor
            billed for an off-contract item. A memo that says “pre-approved — don’t route this.”
            Every one passes your static approval rules. Tollgate is the control layer that
            catches what those rules can’t.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-4 animate-rise">
            <a href="#audit" className="btn-primary">
              Get a free off-objective audit of your PO log
            </a>
            <a href="#how" className="btn-ghost">
              See how the two layers work
            </a>
          </div>
          <p className="mt-7 font-mono text-[0.72rem] uppercase tracking-[0.12em] text-ink-faint">
            Deny-by-default · Full audit trail · Human-in-the-loop
          </p>
        </div>

        <div className="lg:col-span-5 lg:pt-10">
          <div className="reveal">
            <VerdictLedger />
          </div>
        </div>
      </div>
    </section>
  );
}
