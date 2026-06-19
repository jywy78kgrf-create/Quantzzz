import { LiveFeed } from "./LiveFeed.jsx";
import { Counter } from "./Counter.jsx";
import { RevealGroup, RevealItem, Reveal } from "./Reveal.jsx";

function Stat({ value, drift, suffix, label, format }) {
  return (
    <div className="border-l border-line pl-3">
      <div className="font-mono text-[1.35rem] leading-none text-fg">
        <Counter value={value} drift={drift} format={format} />
        {suffix}
      </div>
      <div className="mt-1.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-fg-faint">
        {label}
      </div>
    </div>
  );
}

export function Hero() {
  return (
    <section id="top" className="relative overflow-hidden border-b border-line">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-grid opacity-40" />

      {/* status bar */}
      <div className="relative border-b border-line/70">
        <div className="shell flex items-center justify-between py-2 font-mono text-[0.66rem] uppercase tracking-[0.14em] text-fg-faint">
          <span className="flex items-center gap-2">
            <span className="dot bg-verdict-allow animate-blink" /> system online
          </span>
          <span className="hidden sm:inline">deterministic gate · advisory judge</span>
          <span>p50 decision&nbsp;<span className="text-fg-muted">38ms</span></span>
        </div>
      </div>

      <div className="shell relative grid gap-12 pb-section pt-14 lg:grid-cols-12 lg:gap-10 lg:pt-20">
        <RevealGroup className="lg:col-span-6" stagger={0.09}>
          <RevealItem>
            <p className="eyebrow">
              <span className="dot bg-live" /> Control layer for agentic procurement
            </p>
          </RevealItem>
          <RevealItem>
            <h1 className="mt-5 font-display text-display-xl font-normal text-balance text-fg">
              Spends within every limit. Still goes{" "}
              <span className="italic text-live">off-objective.</span>
            </h1>
          </RevealItem>
          <RevealItem>
            <p className="mt-6 max-w-prose font-sans text-lede text-fg-muted">
              Duplicate payments. POs split under an approval cap. An approved vendor billed for an
              off-contract item. A memo that says “pre-approved — don’t route this.” Each one clears
              your static rules. Tollgate is the firewall that catches what they can’t.
            </p>
          </RevealItem>
          <RevealItem>
            <div className="mt-9 flex flex-wrap items-center gap-x-6 gap-y-4">
              <a href="#audit" className="btn-primary">
                Get a free off-objective audit
              </a>
              <a href="#how" className="btn-ghost">
                How the two layers work →
              </a>
            </div>
          </RevealItem>
          <RevealItem>
            <div className="mt-12 grid max-w-lg grid-cols-3 gap-x-4">
              <Stat value={1240118} drift={6} label="POs screened" />
              <Stat value={3847} drift={1} label="off-objective stopped" />
              <Stat value={989} format={(n) => (n / 10).toFixed(1)} suffix="%" label="auto-allowed clean" />
            </div>
            <p className="mt-3 font-mono text-[0.6rem] uppercase tracking-wider text-fg-dim">
              Illustrative figures
            </p>
          </RevealItem>
        </RevealGroup>

        <div className="lg:col-span-6 lg:pl-6">
          <Reveal delay={0.2}>
            <LiveFeed />
          </Reveal>
        </div>
      </div>
    </section>
  );
}
