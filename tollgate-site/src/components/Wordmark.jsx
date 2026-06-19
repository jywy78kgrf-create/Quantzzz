/** Geometric mark: a lowered barrier/gate — a checkpoint, not a blob. */
export function Mark({ className = "h-5 w-5" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2" y="3" width="3" height="18" rx="0.5" fill="currentColor" />
      <rect
        x="5"
        y="8"
        width="17"
        height="3.2"
        rx="0.5"
        fill="currentColor"
        transform="rotate(-9 5 8)"
      />
      <circle cx="20.4" cy="6.3" r="1.5" fill="currentColor" />
    </svg>
  );
}

export function Wordmark({ className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <Mark className="h-5 w-5 text-signal" />
      <span className="font-display text-[1.35rem] font-medium tracking-tight text-ink">
        Tollgate
      </span>
    </span>
  );
}
