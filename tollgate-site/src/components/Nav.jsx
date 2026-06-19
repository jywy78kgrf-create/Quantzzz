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
      className={`sticky top-0 z-50 transition-colors duration-300 ${
        scrolled ? "border-b border-hair bg-void/80 backdrop-blur-md" : ""
      }`}
    >
      <div className="shell flex h-16 items-center justify-between">
        <a href="#top" aria-label="Tollgate home">
          <Wordmark />
        </a>
        <nav className="hidden items-center gap-9 md:flex">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} className="nav-link">
              {l.label}
            </a>
          ))}
          <a href="#audit" className="btn-primary">Get an audit</a>
        </nav>
        <a href="#audit" className="btn-primary md:hidden">Get an audit</a>
      </div>
    </header>
  );
}
