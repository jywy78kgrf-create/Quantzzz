import { useEffect, useRef } from "react";

const PALETTE = [
  // weighted: mostly bone/ash, a pulse of plum, sparks of amber, nodes of lichen
  ...Array(58).fill("#ffffff"),
  ...Array(16).fill("#bdbdbd"),
  ...Array(15).fill("#8052ff"),
  ...Array(6).fill("#ffb829"),
  ...Array(5).fill("#15846e"),
];

const SHAPES = ["circle", "triangle", "diamond", "square"];

function drawShape(ctx, type, x, y, s) {
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

/**
 * A drifting particle constellation: thousands of micro-shapes that sample a
 * slowly-rotating sphere (the dense "intelligence" core) plus an ambient permeable
 * drift at the edges. Depth comes from z-based size/alpha — no shadows. Honors
 * prefers-reduced-motion (renders a single still frame).
 */
export function Constellation({ className = "" }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let w = 0;
    let h = 0;
    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    let particles = [];
    const GOLDEN = Math.PI * (3 - Math.sqrt(5));

    const build = () => {
      const count = Math.min(1500, Math.floor((w * h) / 700));
      const sphereN = Math.floor(count * 0.72);
      particles = [];
      for (let i = 0; i < count; i++) {
        const onSphere = i < sphereN;
        let sx = 0, sy = 0, sz = 0;
        if (onSphere) {
          const y = 1 - (i / (sphereN - 1)) * 2;
          const r = Math.sqrt(Math.max(0, 1 - y * y));
          const th = i * GOLDEN;
          sx = Math.cos(th) * r;
          sy = y;
          sz = Math.sin(th) * r;
        } else {
          // ambient drift: gaussian-ish cloud, wider than the sphere
          const a = Math.random() * Math.PI * 2;
          const rad = 0.6 + Math.pow(Math.random(), 0.6) * 1.7;
          sx = Math.cos(a) * rad;
          sy = (Math.random() * 2 - 1) * 1.4;
          sz = Math.sin(a) * rad;
        }
        particles.push({
          sx, sy, sz,
          onSphere,
          shape: SHAPES[(Math.random() * SHAPES.length) | 0],
          color: PALETTE[(Math.random() * PALETTE.length) | 0],
          base: 0.8 + Math.random() * 1.8,
          tw: Math.random() * Math.PI * 2, // twinkle phase
          tws: 0.4 + Math.random() * 0.8,
        });
      }
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      build();
    };

    let mx = 0, my = 0, tmx = 0, tmy = 0;
    const onMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      tmx = (e.clientX - rect.left) / rect.width - 0.5;
      tmy = (e.clientY - rect.top) / rect.height - 0.5;
    };

    let raf;
    let t = 0;
    const render = () => {
      t += reduce ? 0 : 0.0016;
      mx += (tmx - mx) * 0.05;
      my += (tmy - my) * 0.05;
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2 + mx * 26;
      const cy = h / 2 + my * 26;
      const R = Math.min(w, h) * 0.42;
      const ay = t; // rotate around Y
      const ax = 0.32 + my * 0.25; // slight tilt
      const cosY = Math.cos(ay), sinY = Math.sin(ay);
      const cosX = Math.cos(ax), sinX = Math.sin(ax);

      for (const p of particles) {
        // rotate Y
        let x = p.sx * cosY + p.sz * sinY;
        let z = -p.sx * sinY + p.sz * cosY;
        let y = p.sy;
        // tilt X
        const y2 = y * cosX - z * sinX;
        const z2 = y * sinX + z * cosX;
        y = y2;
        z = z2;

        const persp = 1 / (1.9 - z * 0.6); // front bigger
        const px = cx + x * R * persp;
        const py = cy + y * R * persp;

        const depth = (z + 1.4) / 2.8; // 0..1
        const twinkle = reduce ? 1 : 0.6 + 0.4 * Math.sin(t * 6 * p.tws + p.tw);
        let alpha = (p.onSphere ? 0.35 + depth * 0.65 : 0.12 + depth * 0.4) * twinkle;
        const size = p.base * persp * (p.onSphere ? 1 : 0.85);

        ctx.globalAlpha = Math.max(0, Math.min(1, alpha));
        ctx.fillStyle = p.color;
        drawShape(ctx, p.shape, px, py, size);
      }
      ctx.globalAlpha = 1;
      if (!reduce) raf = requestAnimationFrame(render);
    };

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    if (!reduce) window.addEventListener("pointermove", onMove);
    render();

    return () => {
      ro.disconnect();
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return <canvas ref={canvasRef} aria-hidden="true" className={className} />;
}
