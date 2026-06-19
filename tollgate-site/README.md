# Tollgate — marketing landing page

A single static marketing page for **Tollgate**, an off-objective firewall for
autonomous procurement agents. Its only job: get a qualified finance / AP /
controllership buyer to book a free *PO-log off-objective audit*. It is a
credibility and lead-capture instrument — **not** an app (no dashboard, no auth,
no application logic).

## Stack

- React 18 + Vite + Tailwind CSS (static build).
- One outbound dependency at runtime: a form POST to a form endpoint.
- Deploys to Vercel or Netlify with zero config (`vercel.json` / `netlify.toml`).

## Develop / build

```bash
cd tollgate-site
npm install
npm run dev        # local dev server
npm run build      # production build -> dist/
npm run preview    # serve the production build
```

## Design system (committed tokens)

Direction: a **fraud/controls operations console** — near-black, dense,
technical. Tokens live in `tailwind.config.js` + `src/index.css`:

- **Type:** Fraunces (editorial serif display) · Geist (grotesque body) ·
  Geist Mono (all data/labels/console), self-hosted via Fontsource.
- **Palette:** near-black base with raised panels and hairlines, a single cool
  *live* teal accent, and three verdict colors (allow/escalate/deny) that glow
  on dark — used only in the decision stream and status chips.
- **Signature element:** `LiveFeed` — a real-time decision stream that ticks new
  transactions and resolves each to ALLOW / DENY / ESCALATE (synthetic,
  illustrative; hover to pause). Plus animated mono counters and a film-grain
  overlay (`Grain`) for texture.
- **Motion:** Lenis smooth-scroll + Framer Motion reveals; the feed ticks and a
  scanline sweeps. All motion disabled under `prefers-reduced-motion`.
- **Layout:** grid discipline, hairline-divided panels, mono numerals, status
  bar — built to read like a monitoring console, not a generic SaaS page.

## Lead capture

The form (name, work email, company, monthly PO volume) posts to a
[Formspree](https://formspree.io) endpoint. **Set your real endpoint** in
`src/components/AuditForm.jsx`:

```js
const FORM_ENDPOINT = "https://formspree.io/f/your-form-id";
```

Any endpoint accepting a `multipart/form-data` POST and returning JSON works
(Formspree, Basin, or a one-line serverless function). Success and error states
are handled client-side; no backend is required.

## Honesty notes

No pricing, no fake logos, no invented testimonials or metrics. The only numbers
shown are explicitly marked *illustrative*. Copy describes the real two-layer
design: a deterministic gate (hard, unbypassable) plus an advisory intent judge
that can escalate to a human but never approve.
