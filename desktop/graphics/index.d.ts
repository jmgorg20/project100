// Types for the plain-JavaScript graphics runtime (engine.js), used by the app's preview.
export interface GraphicInstance {
  tile: HTMLDivElement;
  w: number;
  h: number;
  pad: number;
  update(t: number): void;
  report: { fontPx: number | null; shrunk: boolean; broke: boolean };
  duration: number;
  destroy(): void;
}
export const RENDERER_VERSION: number;
export function instantiate(
  id: string,
  params: Record<string, unknown>,
  opts?: { doc?: Document; duration?: number; quality?: "preview" | "final" },
): GraphicInstance;
export function loadFontsFor(doc?: Document): Promise<void>;
export function listTemplates(): { id: string }[];
