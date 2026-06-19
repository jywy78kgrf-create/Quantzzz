import { Constellation } from "./Constellation.jsx";
import { RevealGroup, RevealItem } from "./Reveal.jsx";

export function Hero() {
  return (
    <section id="top" className="relative">
      {/* constellation owns the right half, edge-to-edge, behind on mobile */}
      <div className="pointer-events-none absolute inset-0 lg:left-[44%]">
        <Constellation className="h-full w-full opacity-70 lg:opacity-100" />
      </div>

      <div className="shell relative grid min-h-[88vh] items-center gap-10 py-20 lg:grid-cols-2">
        <RevealGroup className="max-w-measure" stagger={0.1}>
          <RevealItem>
            <p className="eyebrow text-plum">
              Off-objective firewall · agentic procurement
            </p>
          </RevealItem>
          <RevealItem>
            <h1 className="headline mt-6 text-hero text-balance">
              Within every limit. Still off-objective.
            </h1>
          </RevealItem>
          <RevealItem>
            <p className="mt-7 max-w-prose font-acronym text-subheading font-normal text-ash">
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
