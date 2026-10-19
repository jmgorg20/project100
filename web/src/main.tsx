import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { getLang } from "./i18n";
import "./styles.css";

document.documentElement.lang = getLang() === "tl" ? "fil" : "en";
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);

// The offline shell: the service worker keeps the app's own files (never the API's answers or videos).
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }).then((reg) => {
    reg.addEventListener("updatefound", () => {
      const next = reg.installing;
      next?.addEventListener("statechange", () => {
        if (next.state === "installed" && navigator.serviceWorker.controller) window.dispatchEvent(new Event("autoedit-update"));
      });
    });
  }).catch(() => undefined);
}
