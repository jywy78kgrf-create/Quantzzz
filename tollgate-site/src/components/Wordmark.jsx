/** Geometric mark: a lowered, striped checkpoint barrier — a control gate. */
export function Mark({ className = "h-5 w-5" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      {/* upright post + base */}
      <rect x="3" y="4" width="3" height="14" rx="0.6" fill="currentColor" />
      <rect x="1.5" y="18" width="6" height="2.4" rx="0.6" fill="currentColor" />
      {/* horizontal barrier arm, drawn as hazard segments (clearly a barrier) */}
      <rect x="7.4" y="8.2" width="3.6" height="3" rx="0.5" fill="currentColor" />
      <rect x="12" y="8.2" width="3.6" height="3" rx="0.5" fill="currentColor" />
      <rect x="16.6" y="8.2" width="3.6" height="3" rx="0.5" fill="currentColor" />
    </svg>
  );
}

export function Wordmark({ className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <Mark className="h-5 w-5 text-live" />
      <span className="font-sans text-[1.2rem] font-semibold tracking-tight text-fg">
        Tollgate
      </span>
    </span>
  );
}
