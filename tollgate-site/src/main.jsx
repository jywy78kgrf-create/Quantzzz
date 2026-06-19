import React from "react";
import { createRoot } from "react-dom/client";

// Single family — Geist variable (100–900). Weight + tracking carry the system.
import "@fontsource-variable/geist";

import App from "./App.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
