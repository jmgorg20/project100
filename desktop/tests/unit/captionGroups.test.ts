import { describe, expect, it } from "vitest";
import engineData from "../../src/shared/engine-data.json";
import { chunkWords, type CaptionStyle } from "../../src/renderer/lib/timeline";
import type { Word } from "../../src/shared/types";
import real from "./fixtures/realclip_words.json";
import expected from "./fixtures/realclip_captions.json";

// The real Windows run's words (no punctuation): the preview groups them exactly like the engine
// (expected = captions.chunk_words on the same words, tests/data/realclip/groq_words.json).
const words: Word[] = real.words.map((w) => ({ text: w.word, start: w.start, end: w.end }) as Word);
const style = (name: string) => (engineData.styles as unknown as CaptionStyle[]).find((s) => s.name === name)!;
const texts = (groups: Word[][][]) => groups.map((g) => g.map((l) => l.map((w) => w.text)));

describe("caption groups (preview = export)", () => {
  for (const name of ["editorial_card", "bold_caps"] as const) {
    it(`${name}: the same captions as the engine`, () => {
      expect(texts(chunkWords(words, style(name)))).toEqual((expected as Record<string, string[][][]>)[name]);
    });
  }
  it("never mixes two sentences and never leaves 'analytics' alone", () => {
    const groups = texts(chunkWords(words, style("editorial_card"))).map((g) => g.flat().join(" "));
    expect(groups).toContain("i-check ang analytics");
    expect(groups.some((g) => g.includes("video") && g.includes("Tatyo"))).toBe(false);
  });
});
