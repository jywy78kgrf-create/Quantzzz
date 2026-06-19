import { Nav } from "./components/Nav.jsx";
import { Hero } from "./components/Hero.jsx";
import { FailureModes } from "./components/FailureModes.jsx";
import { HowItWorks } from "./components/HowItWorks.jsx";
import { Trust } from "./components/Trust.jsx";
import { AuditForm } from "./components/AuditForm.jsx";
import { Footer } from "./components/Footer.jsx";
import { Grain } from "./components/Grain.jsx";
import { useReveal } from "./lib/useReveal.js";
import { useLenis } from "./lib/useLenis.js";

export default function App() {
  useReveal();
  useLenis();
  return (
    <>
      <Grain />
      <a
        href="#top"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[110] focus:rounded-sharp focus:bg-live focus:px-4 focus:py-2 focus:text-base-sunk"
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
