import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";

/**
 * Counts up to `value` when scrolled into view, then (optionally) keeps ticking
 * up slowly by `drift` per second to feel live. Tabular mono numerals.
 */
export function Counter({ value, drift = 0, format = (n) => n.toLocaleString("en-US"), className = "" }) {
  const reduce = useReducedMotion();
  const ref = useRef(null);
  const [n, setN] = useState(reduce ? value : 0);

  useEffect(() => {
    if (reduce) return;
    const el = ref.current;
    if (!el) return;
    let raf;
    let started = false;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !started) {
          started = true;
          const start = performance.now();
          const dur = 1400;
          const tick = (t) => {
            const p = Math.min(1, (t - start) / dur);
            const eased = 1 - Math.pow(1 - p, 3);
            setN(Math.round(value * eased));
            if (p < 1) raf = requestAnimationFrame(tick);
            else if (drift > 0) startDrift();
          };
          raf = requestAnimationFrame(tick);
        }
      },
      { threshold: 0.4 },
    );
    let driftTimer;
    const startDrift = () => {
      driftTimer = setInterval(() => {
        setN((prev) => prev + Math.max(1, Math.round(drift * (0.4 + Math.random()))));
      }, 1000);
    };
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
      clearInterval(driftTimer);
    };
  }, [value, drift, reduce]);

  return (
    <span ref={ref} className={`font-mono tabular-nums ${className}`}>
      {format(n)}
    </span>
  );
}
