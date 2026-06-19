import { useState } from "react";

// Replace with your Formspree form id (https://formspree.io) or any form POST
// endpoint. Until then the form posts here and Formspree returns a clear error.
const FORM_ENDPOINT = "https://formspree.io/f/your-form-id";

const PO_VOLUMES = [
  "Under 500 / month",
  "500 – 2,000 / month",
  "2,000 – 10,000 / month",
  "Over 10,000 / month",
];

export function AuditForm() {
  const [status, setStatus] = useState("idle"); // idle | submitting | ok | error
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
        setError(
          body?.errors?.[0]?.message ||
            "Something went wrong submitting the form. Email audit@tollgate.example instead.",
        );
        setStatus("error");
      }
    } catch {
      setError("Network error. Please try again, or email audit@tollgate.example.");
      setStatus("error");
    }
  }

  return (
    <section id="audit" className="border-t border-line">
      <div className="shell py-section">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="lg:col-span-5">
            <p className="eyebrow reveal">The offer</p>
            <h2 className="reveal mt-4 font-display text-display-lg font-normal text-ink">
              Get a free off-objective audit of your PO log.
            </h2>
            <p className="reveal mt-5 max-w-prose font-sans text-lede text-ink-muted">
              Send us a sample of your purchase-order log. We replay it through the firewall
              and show you the off-objective actions that passed your current controls —
              duplicates, structured splits, off-contract charges, injected approvals.
            </p>
            <ul className="reveal mt-7 space-y-3">
              {[
                "No system access — you send a redacted export, we return findings.",
                "A written read-out of what slipped through and which control would have held.",
                "No obligation, no pitch deck. The findings are the product.",
              ].map((p) => (
                <li
                  key={p}
                  className="flex gap-3 font-sans text-[0.92rem] leading-relaxed text-ink-soft"
                >
                  <span aria-hidden className="mt-2 h-px w-4 shrink-0 bg-signal" />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="lg:col-span-7">
            <div className="reveal rounded-sharp border border-line bg-paper-raised p-7 shadow-panel sm:p-9">
              {status === "ok" ? (
                <div className="flex min-h-[18rem] flex-col justify-center">
                  <span className="font-mono text-[0.7rem] uppercase tracking-[0.14em] text-verdict-allow">
                    Request received
                  </span>
                  <h3 className="mt-3 font-display text-display-md font-normal text-ink">
                    Thank you — we’ll be in touch within one business day.
                  </h3>
                  <p className="mt-3 font-sans text-[0.95rem] leading-relaxed text-ink-muted">
                    We’ll reply from a real person with the next step and a short list of the
                    log fields we need (no credentials, no system access).
                  </p>
                </div>
              ) : (
                <form onSubmit={onSubmit} noValidate>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div className="sm:col-span-1">
                      <label className="field-label" htmlFor="name">
                        Name
                      </label>
                      <input
                        id="name"
                        name="name"
                        required
                        autoComplete="name"
                        className="field-input"
                        placeholder="Jordan Avery"
                      />
                    </div>
                    <div className="sm:col-span-1">
                      <label className="field-label" htmlFor="email">
                        Work email
                      </label>
                      <input
                        id="email"
                        name="email"
                        type="email"
                        required
                        autoComplete="email"
                        className="field-input"
                        placeholder="jordan@company.com"
                      />
                    </div>
                    <div className="sm:col-span-1">
                      <label className="field-label" htmlFor="company">
                        Company
                      </label>
                      <input
                        id="company"
                        name="company"
                        required
                        autoComplete="organization"
                        className="field-input"
                        placeholder="Company, Inc."
                      />
                    </div>
                    <div className="sm:col-span-1">
                      <label className="field-label" htmlFor="po_volume">
                        Approx. monthly PO volume
                      </label>
                      <select id="po_volume" name="po_volume" required className="field-input" defaultValue="">
                        <option value="" disabled>
                          Select a range
                        </option>
                        {PO_VOLUMES.map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-3">
                    <button
                      type="submit"
                      disabled={status === "submitting"}
                      className="btn-primary disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {status === "submitting" ? "Sending…" : "Request my audit"}
                    </button>
                    <p className="font-mono text-[0.68rem] leading-relaxed text-ink-faint">
                      We use this only to schedule the audit. No list-selling.
                    </p>
                  </div>

                  {status === "error" && (
                    <p className="mt-4 rounded-sharp border border-verdict-deny/30 bg-verdict-deny/5 px-3.5 py-2.5 font-sans text-[0.85rem] text-verdict-deny">
                      {error}
                    </p>
                  )}
                </form>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
