import { Nav } from "./components/Nav.jsx";
import { Hero } from "./components/Hero.jsx";
import { FailureModes } from "./components/FailureModes.jsx";
import { HowItWorks } from "./components/HowItWorks.jsx";
import { Trust } from "./components/Trust.jsx";
import { AuditForm } from "./components/AuditForm.jsx";
import { Footer } from "./components/Footer.jsx";
import { useReveal } from "./lib/useReveal.js";

export default function App() {
  useReveal();
  return (
    <>
      <a
        href="#top"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-sharp focus:bg-ink focus:px-4 focus:py-2 focus:text-paper"
      >
        Skip to content
      </a>
      <Nav />
      <main>
        <Hero />
        <FailureModes />
        <HowItWorks />
        <Trust />
        <AuditForm />
      </main>
      <Footer />
    </>
  );
}
