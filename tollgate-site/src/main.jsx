import React from "react";
import { createRoot } from "react-dom/client";

// Display = Space Grotesk (characterful geometric); body/UI = Geist. Self-hosted.
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/geist";

import App from "./App.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
