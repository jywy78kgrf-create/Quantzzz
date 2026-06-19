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

The visual identity is deliberate and lives in `tailwind.config.js` + `src/index.css`:

- **Type:** Newsreader (editorial serif, display) · IBM Plex Sans (body/UI) ·
  IBM Plex Mono (data, labels, codes). No system-ui defaults.
- **Palette:** warm near-black ink on warm paper, one confident *signal*
  vermillion accent, plus three semantic verdict colors (allow/escalate/deny)
  used only in product chips. No purple, no blob gradients.
- **Layout:** real grid discipline, hairline rules, whitespace as structure,
  high-contrast typographic hierarchy.
- **Motion:** subtle reveal-on-scroll and one hero rise only; fully disabled
  under `prefers-reduced-motion`.

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
