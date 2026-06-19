/**
 * Tollgate design tokens — "Dala" void/constellation system.
 *
 * Pure black canvas, white type that glows on the void, a single saturated
 * violet (Plum Voltage) as the only filled chromatic surface. Ultra-thin display
 * type, pill geometry, hairline borders. No shadows, gradients, or noise — depth
 * comes from color contrast and negative space. Single family (Geist) does all
 * the work via weight + tracking.
 */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        void: "#000000",
        bone: "#ffffff",
        ash: "#bdbdbd",
        smoke: "#9a9a9a",
        plum: { DEFAULT: "#8052ff", soft: "#8052ff1a", line: "#8052ff55" },
        amber: "#ffb829",
        lichen: "#15846e",
        hair: "#ffffff1a", // hairline border on the void
      },
      fontFamily: {
        // Display = Space Grotesk (character); body/UI = Geist (clean).
        display: ['"Space Grotesk Variable"', '"Geist Variable"', "system-ui", "sans-serif"],
        sans: ['"Geist Variable"', "Inter", "system-ui", "sans-serif"],
        acronym: ['"Geist Variable"', "Inter", "system-ui", "sans-serif"],
      },
      fontSize: {
        caption: ["0.75rem", { lineHeight: "1.5", letterSpacing: "0.05em" }],
        "body-sm": ["0.875rem", { lineHeight: "1.5", letterSpacing: "0.02em" }],
        body: ["1rem", { lineHeight: "1.5", letterSpacing: "0.025em" }],
        subheading: ["1.125rem", { lineHeight: "1.5", letterSpacing: "0.025em" }],
        eyebrow: ["0.75rem", { lineHeight: "1", letterSpacing: "0.16em" }],
        "heading-sm": ["1.5rem", { lineHeight: "1.3", letterSpacing: "0.021em" }],
        heading: ["clamp(1.9rem, 3.4vw, 2.25rem)", { lineHeight: "1.15", letterSpacing: "-0.01em" }],
        "heading-lg": ["clamp(2.4rem, 5vw, 3rem)", { lineHeight: "1.05", letterSpacing: "-0.04em" }],
        display: ["clamp(3rem, 7vw, 4.9rem)", { lineHeight: "0.9", letterSpacing: "-0.04em" }],
        hero: ["clamp(3.4rem, 9vw, 7rem)", { lineHeight: "0.84", letterSpacing: "-0.045em" }],
      },
      fontWeight: {
        extralight: "200",
        normal: "400",
        semibold: "600",
        bold: "700",
      },
      maxWidth: { shell: "1200px", prose: "60ch", measure: "30rem" },
      spacing: {
        section: "clamp(4rem, 9vw, 7.5rem)",
        18: "4.5rem",
        30: "7.5rem",
      },
      borderRadius: { pill: "24px", card: "24px" },
      keyframes: {
        drift: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-6px)" } },
        fadein: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
      },
      animation: {
        drift: "drift 7s ease-in-out infinite",
        fadein: "fadein 1.2s ease both",
      },
    },
  },
  plugins: [],
};
