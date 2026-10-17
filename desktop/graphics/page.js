// The page the frame renderer drives (Playwright in tests / the command line, an offscreen
// Electron window in the app). It builds one graphic and draws it at any time on request.
import "./templates/index.js";
import { instantiate, listTemplates, loadFontsFor, RENDERER_VERSION } from "./index.js";

let current = null;

window.gfx = {
  version: RENDERER_VERSION,
  list: () => listTemplates(),
  /** Build a graphic; resolves with its size once fonts are ready. */
  async prepare({ id, params, duration, quality }) {
    await loadFontsFor(document);
    if (current) current.destroy();
    current = instantiate(id, params, { duration, quality: quality || "final" });
    const r = current.tile.getBoundingClientRect();
    return { w: current.w, h: current.h, pad: current.pad, tileW: Math.round(r.width), tileH: Math.round(r.height), report: current.report, duration: current.duration };
  },
  /** Draw the graphic at t seconds (synchronous: the screenshot that follows sees it). */
  seek(t) {
    current.update(t);
    return true;
  },
  clear() { if (current) current.destroy(); current = null; },
};
window.gfxReady = true;
