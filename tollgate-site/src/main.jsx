import React from "react";
import { createRoot } from "react-dom/client";

// Self-hosted variable fonts (no Google CDN). Fraunces = editorial display,
// Geist = precise grotesque body, Geist Mono = tabular data.
import "@fontsource-variable/fraunces";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";

import App from "./App.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
