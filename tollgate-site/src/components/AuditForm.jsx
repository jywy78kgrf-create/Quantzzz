import { useState } from "react";
import { Reveal } from "./Reveal.jsx";

// Replace with your Formspree form id (https://formspree.io) or any form POST
// endpoint. Until then the form posts here and the endpoint returns a clear error.
const FORM_ENDPOINT = "https://formspree.io/f/your-form-id";

const PO_VOLUMES = [
  "Under 500 / month",
  "500 – 2,000 / month",
  "2,000 – 10,000 / month",
  "Over 10,000 / month",
];

export function AuditForm() {
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    setStatus("submitting");
    setError("");
    const form = e.currentTarget;
    const data = new FormData(form);
    try {
      const res = await fetch(FORM_ENDPOINT, {
        method: "POST",
        body: data,
        headers: { Accept: "application/json" },
      });
      if (res.ok) {
        setStatus("ok");
        form.reset();
      } else {
        const body = await res.json().catch(() => ({}));
        setError(body?.errors?.[0]?.message || "Submission failed. Email audit@tollgate.example instead.");
        setStatus("error");
      }
    } catch {
      setError("Network error. Please try again, or email audit@tollgate.example.");
      setStatus("error");
    }
  }

  return (
    <section id="audit" className="shell py-section">
      <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
        <div className="lg:col-span-5">
          <Reveal>
            <p className="eyebrow text-plum">The offer</p>
          </Reveal>
          <Reveal delay={0.05}>
            <h2 className="headline mt-6 text-heading-lg text-balance">
              A free off-objective audit of your PO log.
            </h2>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="mt-6 max-w-prose font-acronym text-subheading font-normal text-ash">
              Send a sample of your purchase-order log. We replay it through the firewall and show you
              the off-objective actions that passed your current controls — duplicates, structured
              splits, off-contract charges, injected approvals.
            </p>
          </Reveal>
          <Reveal delay={0.15}>
            <ul className="mt-8 space-y-3.5">
              {[
                "No system access — you send a redacted export, we return findings.",
                "A written read-out of what slipped through and which control would have held.",
                "No obligation, no pitch deck. The findings are the product.",
              ].map((p) => (
                <li key={p} className="flex gap-3 font-acronym text-body-sm leading-relaxed text-bone">
                  <span aria-hidden className="mt-2 h-px w-4 shrink-0 bg-plum" />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </Reveal>
        </div>

        <div className="lg:col-span-7">
          <Reveal className="outline-card p-7 sm:p-9">
            {status === "ok" ? (
              <div className="flex min-h-[18rem] flex-col justify-center">
                <span className="inline-flex items-center gap-2.5 font-acronym text-caption uppercase tracking-[0.14em] text-plum">
                  <span className="h-1.5 w-1.5 rounded-full bg-plum" /> Request received
                </span>
                <h3 className="mt-4 font-acronym text-heading font-extralight text-bone">
                  Thank you — we’ll be in touch within one business day.
                </h3>
                <p className="mt-4 font-acronym text-body font-normal leading-relaxed text-ash">
                  A real person will reply with the next step and the short list of log fields we
                  need (no credentials, no system access).
                </p>
              </div>
            ) : (
              <form onSubmit={onSubmit} noValidate>
                <div className="grid gap-5 sm:grid-cols-2">
                  <div>
                    <label className="field-label" htmlFor="name">Name</label>
                    <input id="name" name="name" required autoComplete="name" className="field-input" placeholder="Jordan Avery" />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="email">Work email</label>
                    <input id="email" name="email" type="email" required autoComplete="email" className="field-input" placeholder="jordan@company.com" />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="company">Company</label>
                    <input id="company" name="company" required autoComplete="organization" className="field-input" placeholder="Company, Inc." />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="po_volume">Monthly PO volume</label>
                    <select id="po_volume" name="po_volume" required className="field-input" defaultValue="">
                      <option value="" disabled>Select a range</option>
                      {PO_VOLUMES.map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
                  <button type="submit" disabled={status === "submitting"} className="btn-primary disabled:cursor-not-allowed disabled:opacity-60">
                    {status === "submitting" ? "Sending…" : "Request my audit"}
                  </button>
                  <p className="font-acronym text-caption text-smoke">
                    Used only to schedule the audit. No list-selling.
                  </p>
                </div>

                {status === "error" && (
                  <p className="mt-5 rounded-pill border border-amber/50 px-4 py-2.5 font-acronym text-body-sm text-amber">
                    {error}
                  </p>
                )}
              </form>
            )}
          </Reveal>
        </div>
      </div>
    </section>
  );
}
