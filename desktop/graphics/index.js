// Public entry: the runtime plus font loading. Templates register themselves when
// ./templates/index.js is imported.
export * from "./engine.js";

const FAMILIES = [
  ["GfxInter", [100, 400, 500, 700, 900]], ["GfxAnton", [400]], ["GfxArchivo", [400]], ["GfxBebas", [400]], ["GfxBangers", [400]],
  ["GfxOswald", [700]], ["GfxPlayfair", [800]], ["GfxCaveat", [700]], ["GfxMono", [700]],
];

/** Wait until every bundled font is ready, so text is measured with the real glyphs. */
export async function loadFontsFor(doc = document) {
  const jobs = [];
  for (const [fam, weights] of FAMILIES) for (const w of weights) jobs.push(doc.fonts.load(`${w} 40px "${fam}"`, "AaÑñ 0123 Åé"));
  await Promise.all(jobs);
  await doc.fonts.ready;
}
