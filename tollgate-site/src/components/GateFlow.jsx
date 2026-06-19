import { useEffect, useRef } from "react";

/**
 * GateFlow — the product, rendered as a particle field.
 *
 * Transactions stream in from the left, funnel through a single control
 * aperture (the gate), and resolve into three lanes:
 *   • ALLOW    — pass straight through (bone)
 *   • ESCALATE — diverted up for human review (amber)
 *   • DENY     — deflected/blocked (plum, the authority color)
 *
 * This literally visualizes a firewall screening a flow. Honors
 * prefers-reduced-motion by rendering a single representative still frame.
 */

const COL = {
  flow: "#6a6a78",
  allow: "#e7eaec",
  escalate: "#ffb829",
  deny: "#8052ff",
  node: "#15846e",
};
const SHAPES = ["circle", "triangle", "diamond", "square"];

function shape(ctx, type, x, y, s) {
  switch (type) {
    case "triangle":
      ctx.beginPath();
      ctx.moveTo(x, y - s);
      ctx.lineTo(x + s, y + s);
      ctx.lineTo(x - s, y + s);
      ctx.closePath();
      ctx.fill();
      break;
    case "diamond":
      ctx.beginPath();
      ctx.moveTo(x, y - s);
      ctx.lineTo(x + s, y);
      ctx.lineTo(x, y + s);
      ctx.lineTo(x - s, y);
      ctx.closePath();
      ctx.fill();
      break;
    case "square":
      ctx.fillRect(x - s, y - s, s * 2, s * 2);
      break;
    default:
      ctx.beginPath();
      ctx.arc(x, y, s, 0, Math.PI * 2);
      ctx.fill();
  }
}

export function GateFlow({ className = "" }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let w = 0, h = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    let parts = [];
    let target = 0;

    const gateX = () => w * 0.46;
    const apY = () => h * 0.5;
    const apR = () => Math.min(h * 0.22, 150);

    const spawn = () => {
      const verdict =
        Math.random() < 0.74 ? "allow" : Math.random() < 0.6 ? "deny" : "escalate";
      return {
        x: -10 - Math.random() * 40,
        y: apY() + (Math.random() * 2 - 1) * h * 0.42,
        vx: 46 + Math.random() * 34, // px/sec
        vy: 0,
        decided: false,
        verdict,
        s: 1.1 + Math.random() * 1.7,
        shape: SHAPES[(Math.random() * SHAPES.length) | 0],
        flash: 0,
        a: 0,
        node: Math.random() < 0.04,
      };
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      target = Math.max(120, Math.min(420, Math.floor((w * h) / 1600)));
      if (reduce) {
        parts = Array.from({ length: target }, () => {
          const p = spawn();
          p.x = Math.random() * w;
          decideAt(p, p.x);
          p.a = 1;
          return p;
        });
      }
    };

    // assign post-gate motion when a particle reaches the gate
    const decideAt = (p, gx) => {
      p.decided = true;
      p.flash = 1;
      const speed = p.vx;
      if (p.verdict === "allow") {
        p.vy = (Math.random() * 2 - 1) * 10;
      } else if (p.verdict === "deny") {
        p.vx = speed * 0.45;
        p.vy = 70 + Math.random() * 60; // deflect down
      } else {
        p.vx = speed * 0.5;
        p.vy = -(70 + Math.random() * 60); // divert up
      }
      void gx;
    };

    const colorFor = (p) => {
      if (!p.decided) return p.node ? COL.node : COL.flow;
      return COL[p.verdict];
    };

    const drawGate = () => {
      const gx = gateX();
      const cy = apY();
      const r = apR();
      // vertical gate hairline
      ctx.globalAlpha = 0.16;
      ctx.strokeStyle = "#8052ff";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(gx, cy - r * 1.5);
      ctx.lineTo(gx, cy + r * 1.5);
      ctx.stroke();
      // aperture ring
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc(gx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 0.18;
      ctx.beginPath();
      ctx.arc(gx, cy, r * 0.6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    };

    const labels = () => {
      const gx = gateX();
      ctx.font = "600 10px 'Geist Variable', system-ui, sans-serif";
      ctx.textBaseline = "middle";
      const set = [
        ["ESCALATE", COL.escalate, apY() - apR() * 1.5],
        ["ALLOW", COL.allow, apY()],
        ["DENY", COL.deny, apY() + apR() * 1.5],
      ];
      for (const [t, c, y] of set) {
        ctx.globalAlpha = 0.7;
        ctx.fillStyle = c;
        ctx.fillText(t, Math.min(w - 70, gx + apR() + 26), y);
      }
      ctx.globalAlpha = 1;
    };

    let raf, last = performance.now();
    const frame = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      ctx.clearRect(0, 0, w, h);
      drawGate();

      const gx = gateX();
      const cy = apY();

      if (!reduce) {
        // maintain population
        while (parts.length < target) parts.push(spawn());
      }

      for (let i = parts.length - 1; i >= 0; i--) {
        const p = parts[i];
        if (!reduce) {
          // funnel toward aperture before the gate
          if (!p.decided) {
            p.vy += (cy - p.y) * 1.6 * dt;
            p.vy *= 0.92;
          }
          p.x += p.vx * dt;
          p.y += p.vy * dt;
          if (!p.decided && p.x >= gx) decideAt(p, gx);
          p.a = Math.min(1, p.a + dt * 3);
          if (p.flash > 0) p.flash = Math.max(0, p.flash - dt * 2.5);
          // cull
          if (p.x > w + 20 || p.y < -30 || p.y > h + 30) {
            parts.splice(i, 1);
            continue;
          }
        }

        const decidedFade = p.decided ? Math.max(0.25, 1 - (p.x - gx) / (w - gx + 1)) : 1;
        const baseA = (p.decided ? 0.95 : 0.5) * p.a * decidedFade;
        const sz = p.s + p.flash * 2.2;
        ctx.globalAlpha = Math.max(0, Math.min(1, baseA + p.flash * 0.4));
        ctx.fillStyle = colorFor(p);
        shape(ctx, p.shape, p.x, p.y, sz);
      }
      ctx.globalAlpha = 1;
      labels();
      raf = requestAnimationFrame(frame);
    };

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    raf = requestAnimationFrame(frame);

    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);

  return <canvas ref={ref} aria-hidden="true" className={className} />;
}
