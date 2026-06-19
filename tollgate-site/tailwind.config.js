/**
 * Tollgate design tokens.
 *
 * Identity: a controllership / financial-trust register — deep warm neutrals,
 * one confident signal accent, high contrast, editorial. Deliberately NOT a
 * default SaaS look: no purple, no blob gradients, a serious serif/grotesque
 * pairing rather than system-ui.
 */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Core neutrals (warm, near-black ink on warm paper).
        ink: {
          DEFAULT: "#15120B", // primary text / dark panels
          soft: "#2A251B",
          muted: "#6E6453", // secondary text
          faint: "#9A8F79",
        },
        paper: {
          DEFAULT: "#F4F0E6", // page background
          raised: "#FBF8F0", // cards / raised surfaces
          sunk: "#ECE6D6",
        },
        line: {
          DEFAULT: "#D9D0BD", // hairlines on paper
          strong: "#C4B9A1",
          dark: "#34302568", // hairlines on dark
        },
        // One confident accent — a controlled signal vermillion ("intercept").
        signal: {
          DEFAULT: "#B3371A",
          deep: "#8E2A12",
          tint: "#E9D9CF",
        },
        // Semantic verdict colors — used ONLY in product/illustration chips.
        verdict: {
          allow: "#2E5A3C",
          escalate: "#9A6B12",
          deny: "#A3301A",
        },
      },
      fontFamily: {
        display: ['"Fraunces Variable"', "Georgia", "serif"],
        sans: ['"Geist Variable"', "system-ui", "sans-serif"],
        mono: ['"Geist Mono Variable"', "ui-monospace", "monospace"],
      },
      fontSize: {
        // A deliberate modular scale.
        eyebrow: ["0.75rem", { lineHeight: "1rem", letterSpacing: "0.14em" }],
        "display-xl": ["clamp(2.6rem, 6vw, 4.7rem)", { lineHeight: "1.02", letterSpacing: "-0.02em" }],
        "display-lg": ["clamp(2rem, 4vw, 3.1rem)", { lineHeight: "1.06", letterSpacing: "-0.015em" }],
        "display-md": ["clamp(1.5rem, 2.6vw, 2.1rem)", { lineHeight: "1.12", letterSpacing: "-0.01em" }],
        lede: ["clamp(1.1rem, 1.6vw, 1.35rem)", { lineHeight: "1.55" }],
      },
      maxWidth: {
        shell: "1200px",
        prose: "62ch",
      },
      spacing: {
        section: "clamp(4.5rem, 10vw, 9rem)",
      },
      borderRadius: {
        sharp: "3px",
      },
      boxShadow: {
        panel: "0 1px 0 0 #00000008, 0 18px 40px -28px #3a30205c",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        sweep: {
          "0%": { transform: "scaleX(0)" },
          "100%": { transform: "scaleX(1)" },
        },
      },
      animation: {
        rise: "rise 0.7s cubic-bezier(0.22,1,0.36,1) both",
        sweep: "sweep 0.9s cubic-bezier(0.22,1,0.36,1) both",
      },
    },
  },
  plugins: [],
};
