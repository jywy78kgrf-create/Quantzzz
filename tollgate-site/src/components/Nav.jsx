import { useEffect, useState } from "react";
import { Wordmark } from "./Wordmark.jsx";

const LINKS = [
  { href: "#failures", label: "Failure modes" },
  { href: "#how", label: "How it works" },
  { href: "#controls", label: "Controls" },
];

export function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`sticky top-0 z-50 border-b transition-colors duration-300 ${
        scrolled ? "border-line bg-base/80 backdrop-blur-md" : "border-transparent"
      }`}
    >
      <div className="shell flex h-16 items-center justify-between">
        <a href="#top" aria-label="Tollgate home">
          <Wordmark />
        </a>
        <nav className="hidden items-center gap-8 md:flex">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="font-mono text-[0.78rem] uppercase tracking-wider text-fg-muted transition-colors hover:text-fg"
            >
              {l.label}
            </a>
          ))}
          <a href="#audit" className="btn-primary px-4 py-2 text-[0.8rem]">
            Get an audit
          </a>
        </nav>
        <a href="#audit" className="btn-primary px-4 py-2 text-[0.8rem] md:hidden">
          Get an audit
        </a>
      </div>
    </header>
  );
}
