import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import { initObservability } from "@/observability";

// Initialise error tracking (Sentry) + analytics (PostHog) before render.
initObservability();

// Global safety net: log uncaught errors so they never disappear silently.
// Production-safe — does not surface raw stacks to users (ErrorBoundary handles UI).
if (typeof window !== "undefined") {
    window.addEventListener("error", (event) => {
        if (window.console) console.error("[window.onerror]", event.error || event.message);
    });
    window.addEventListener("unhandledrejection", (event) => {
        if (window.console) console.error("[unhandledrejection]", event.reason);
    });
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
