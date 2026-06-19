import { Wordmark } from "./Wordmark.jsx";

export function Footer() {
  return (
    <footer className="bg-base-sunk">
      <div className="shell flex flex-col gap-6 py-12 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Wordmark />
          <p className="mt-3 max-w-prose font-sans text-[0.85rem] leading-relaxed text-fg-muted">
            The off-objective firewall for autonomous procurement. A deterministic control gate with
            an advisory intent check — deny-by-default, fully attestable.
          </p>
        </div>
        <div className="flex items-center gap-6 font-mono text-[0.74rem] uppercase tracking-wider text-fg-muted">
          <a href="#how" className="transition-colors hover:text-fg">How it works</a>
          <a href="#controls" className="transition-colors hover:text-fg">Controls</a>
          <a href="#audit" className="transition-colors hover:text-live">Get an audit</a>
        </div>
      </div>
      <div className="shell border-t border-line py-5">
        <p className="font-mono text-[0.64rem] uppercase tracking-[0.1em] text-fg-dim">
          © {new Date().getFullYear()} Tollgate · Figures shown are illustrative
        </p>
      </div>
    </footer>
  );
}
