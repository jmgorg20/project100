// Writes autoedit/graphics_catalog.json from the templates' meta: the one list the Python
// engine (validator, Director, export check) and the app read. Run: npm run graphics-catalog
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import "./templates/index.js";
import { listTemplates, FONT_STACKS, MOODS, ICON_KEYS, RENDERER_VERSION, FRAME_W, FRAME_H } from "./engine.js";

export function catalog() {
  return {
    version: 1,
    renderer: RENDERER_VERSION,
    frame: { w: FRAME_W, h: FRAME_H },
    moods: MOODS,
    fonts: Object.fromEntries(Object.entries(FONT_STACKS).map(([k, v]) => [k, v.label])),
    icons: ICON_KEYS,
    templates: listTemplates().sort((a, b) => a.id.localeCompare(b.id)),
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  // one copy for the engine, one the app bundles (src/shared); a test checks they are the same
  const here = dirname(fileURLToPath(import.meta.url));
  const text = JSON.stringify(catalog(), null, 1) + "\n";
  for (const out of [join(here, "..", "..", "autoedit", "graphics_catalog.json"), join(here, "..", "src", "shared", "graphics-catalog.json")]) {
    writeFileSync(out, text);
    console.log(`wrote ${out}`);
  }
}
