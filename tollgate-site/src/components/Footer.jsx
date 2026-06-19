import { Wordmark } from "./Wordmark.jsx";

export function Footer() {
  return (
    <footer className="shell border-t border-hair py-12">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Wordmark />
          <p className="mt-4 max-w-prose font-acronym text-body-sm leading-relaxed text-smoke">
            The off-objective firewall for autonomous procurement. A deterministic control gate with
            an advisory intent check — deny-by-default, fully attestable.
          </p>
        </div>
        <div className="flex items-center gap-7 font-acronym text-body-sm tracking-[0.02em]">
          <a href="#how" className="text-smoke transition-colors hover:text-bone">How it works</a>
          <a href="#controls" className="text-smoke transition-colors hover:text-bone">Controls</a>
          <a href="#audit" className="text-smoke transition-colors hover:text-plum">Get an audit</a>
        </div>
      </div>
      <p className="mt-10 font-acronym text-caption uppercase tracking-[0.12em] text-smoke/60">
        © {new Date().getFullYear()} Tollgate · Figures shown are illustrative
      </p>
    </footer>
  );
}
