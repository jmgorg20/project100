import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app is served by the API at /app/ (same site as the API: the session cookie stays there).
// The editing rules are the desktop app's own (desktop/src/shared), not a copy.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  resolve: { alias: { "@shared": fileURLToPath(new URL("../desktop/src/shared", import.meta.url)) } },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false, assetsInlineLimit: 0 },
  server: { proxy: { "/v1": "http://127.0.0.1:8787", "/files": "http://127.0.0.1:8787" } },
});
