/** Line-drawn geometric mark — a faceted gate/aperture, stroke ~1.5. */
export function Mark({ className = "h-5 w-5" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
      <path d="M12 2.5 21 7v10l-9 4.5L3 17V7z" />
      <path d="M12 2.5v19" opacity="0.55" />
      <path d="M3 7l9 4.5L21 7" opacity="0.55" />
    </svg>
  );
}

export function Wordmark({ className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <Mark className="h-[1.15rem] w-[1.15rem] text-plum" />
      <span className="font-acronym text-[1.05rem] font-semibold tracking-[0.04em] text-bone">
        Tollgate
      </span>
    </span>
  );
}
