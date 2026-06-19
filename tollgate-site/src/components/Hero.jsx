import { GateFlow } from "./GateFlow.jsx";
import { RevealGroup, RevealItem } from "./Reveal.jsx";

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden">
      {/* the gate field owns the right side, edge-to-edge */}
      <div className="pointer-events-none absolute inset-y-0 right-0 left-0 lg:left-[42%]">
        <GateFlow className="h-full w-full opacity-60 lg:opacity-100" />
      </div>

      <div className="shell relative grid min-h-[90vh] items-center gap-10 py-20 lg:grid-cols-[minmax(0,52%)_1fr]">
        <RevealGroup className="max-w-[34rem]" stagger={0.1}>
          <RevealItem>
            <p className="eyebrow text-plum">Off-objective firewall · agentic procurement</p>
          </RevealItem>
          <RevealItem>
            <h1 className="headline mt-7 text-display leading-[0.95] text-balance">
              Within every limit.
              <br />
              <span className="whitespace-nowrap text-plum">Still off-objective.</span>
            </h1>
          </RevealItem>
          <RevealItem>
            <p className="mt-7 max-w-[30rem] font-sans text-subheading font-normal leading-relaxed text-ash">
              Duplicate payments. POs split under an approval cap. An approved vendor billed for an
              off-contract item. A memo that says “pre-approved — don’t route this.” Each clears your
              static rules. Tollgate is the control layer that catches what they can’t.
            </p>
          </RevealItem>
          <RevealItem>
            <div className="mt-9 flex flex-wrap items-center gap-3.5">
              <a href="#audit" className="btn-primary">Get a free off-objective audit</a>
              <a href="#how" className="btn-outline">How it works</a>
            </div>
          </RevealItem>
        </RevealGroup>

        <div className="hidden lg:block" />
      </div>
    </section>
  );
}
