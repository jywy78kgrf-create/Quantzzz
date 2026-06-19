/**
 * Tollgate design tokens — "control room" direction.
 *
 * A fraud/controls operations console: near-black, dense, technical. Restrained
 * cool accent (teal = live/active), verdict colors (allow/escalate/deny) that
 * glow on dark, film grain, mono numerals. The opposite of the airy AI default.
 */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        base: {
          DEFAULT: "#0A0C0E", // page
          raised: "#101418", // panels
          high: "#161B21", // raised within panels
          sunk: "#070809",
        },
        line: {
          DEFAULT: "#212931",
          strong: "#303a44",
          faint: "#171c21",
        },
        fg: {
          DEFAULT: "#E7EAEC", // primary text
          muted: "#9aa4ad",
          faint: "#5f6a73",
          dim: "#3f474e",
        },
        // Brand / "live" accent.
        live: {
          DEFAULT: "#3FD2C7",
          deep: "#1f9d94",
          glow: "#3FD2C733",
        },
        // Decision colors (glow on dark).
        verdict: {
          allow: "#48C78E",
          escalate: "#E6B450",
          deny: "#F0616D",
        },
      },
      fontFamily: {
        display: ['"Fraunces Variable"', "Georgia", "serif"],
        sans: ['"Geist Variable"', "system-ui", "sans-serif"],
        mono: ['"Geist Mono Variable"', "ui-monospace", "monospace"],
      },
      fontSize: {
        micro: ["0.68rem", { lineHeight: "1rem", letterSpacing: "0.16em" }],
        eyebrow: ["0.72rem", { lineHeight: "1rem", letterSpacing: "0.22em" }],
        "display-xl": ["clamp(2.6rem, 6vw, 4.9rem)", { lineHeight: "1.0", letterSpacing: "-0.025em" }],
        "display-lg": ["clamp(2rem, 4vw, 3.2rem)", { lineHeight: "1.05", letterSpacing: "-0.02em" }],
        "display-md": ["clamp(1.45rem, 2.6vw, 2.05rem)", { lineHeight: "1.12", letterSpacing: "-0.015em" }],
        lede: ["clamp(1.05rem, 1.5vw, 1.3rem)", { lineHeight: "1.55" }],
      },
      maxWidth: { shell: "1240px", prose: "60ch" },
      spacing: { section: "clamp(4.5rem, 10vw, 8.5rem)" },
      borderRadius: { sharp: "4px" },
      boxShadow: {
        panel: "0 1px 0 0 #ffffff08 inset, 0 24px 60px -32px #000000cc",
        glow: "0 0 0 1px #3FD2C733, 0 0 24px -6px #3FD2C755",
      },
      keyframes: {
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
        scan: { "0%": { transform: "translateY(-100%)" }, "100%": { transform: "translateY(900%)" } },
        ticker: { "0%": { transform: "translateY(8px)", opacity: "0" }, "100%": { transform: "translateY(0)", opacity: "1" } },
      },
      animation: {
        blink: "blink 1.4s steps(1) infinite",
        scan: "scan 7s linear infinite",
        ticker: "ticker 0.5s cubic-bezier(0.22,1,0.36,1) both",
      },
    },
  },
  plugins: [],
};
