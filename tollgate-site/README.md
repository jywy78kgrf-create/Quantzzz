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

Direction: **"void / constellation"** — a pure-black canvas with a single
saturated violet (Plum Voltage `#8052ff`) as the only filled chromatic surface,
white type that glows on the void, and a particle constellation as the brand
mark. Tokens in `tailwind.config.js` + `src/index.css`:

- **Type:** one family (Geist variable, self-hosted) doing all the work through
  weight + tracking — ultra-thin (200) huge display with negative tracking,
  opener positive tracking at body sizes. No serifs, no second family.
- **Palette:** void black, bone/ash/smoke greys, Plum Voltage (the only fill),
  amber for outlined accents/links, lichen as a constellation node color.
- **Signature element:** `Constellation` — a canvas particle field (thousands of
  2–6px triangles/circles/diamonds/squares) sampling a slowly-rotating sphere
  with ambient drift, subtle pointer parallax; depth from z-based size/alpha, no
  shadows. Renders a single still frame under `prefers-reduced-motion`.
- **Surfaces:** flat. "Cards" are just hairline borders on the void — no fills,
  shadows, gradients, or noise. Pill (24px) geometry on every interactive element.
- **Motion:** Lenis smooth-scroll + Framer Motion reveals, kept subtle.

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
