// Edit one caption: its words (text, timing, highlight), emoji, style, place and size,
// and "Listen again" (re-transcribe this part).
import { useState } from "react";
import data from "../../shared/engine-data.json";
import { EMOJI, type CaptionLook } from "../../shared/captionEdit";
import type { Clip, Word } from "../../shared/types";

export const STYLES = data.styles.map((s) => ({ name: s.name, description: s.description, size: s.size }));

export function CaptionEditor({ clip, busy, onWords, onWordText, onHighlight, onEmoji, onLook, onRetranscribe, punctuation = "remove", onPunctuation }: {
  clip: Clip;
  busy: boolean;
  onWords: (words: Word[], key: string) => void;
  onWordText: (index: number, text: string) => void;
  onHighlight: (index: number) => void;
  onEmoji: (index: number, emoji: string) => void;
  onLook: (look: CaptionLook, all: boolean) => void;
  onRetranscribe: () => void;
  punctuation?: "remove" | "keep";
  onPunctuation?: (mode: "remove" | "keep") => void;
}) {
  const words = clip.words ?? [];
  const [picked, setPicked] = useState(0);
  const [applyAll, setApplyAll] = useState(false);
  const style = STYLES.find((s) => s.name === clip.style) ?? STYLES[1];
  const zone = (clip.overrides?.zone as string | undefined) ?? "auto";
  const size = (clip.overrides?.size as number | undefined) ?? style.size;
  const look = (l: CaptionLook) => onLook(l, applyAll);

  return (
    <div className="caption-editor" data-testid="caption-editor">
      <section className="insp-section">
        <h3>Words · Mga salita</h3>
        <p className="muted small" style={{ margin: 0 }}>Click a word to type over it. ★ highlights it.</p>
        <div className="word-list">
          {words.map((w, i) => (
            <div key={`${i}-${w.text}`} className={`word-row${i === picked ? " picked" : ""}`} onFocus={() => setPicked(i)}>
              <input
                type="text"
                defaultValue={w.text}
                aria-label={`Word ${i + 1}`}
                onBlur={(e) => e.target.value !== w.text && onWordText(i, e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              />
              <input
                type="number"
                step={0.05}
                min={0}
                max={clip.duration}
                value={w.start.toFixed(2)}
                aria-label={`Word ${i + 1} starts`}
                title="Starts at (seconds into the caption)"
                onChange={(e) => onWords(words.map((x, k) => (k === i ? { ...x, start: Number(e.target.value) } : x)), `w-start-${i}`)}
              />
              <button className={`btn small ghost star${w.highlight ? " on" : ""}`} aria-pressed={Boolean(w.highlight)} aria-label={`Highlight word ${i + 1}`} onClick={() => onHighlight(i)}>
                ★
              </button>
            </div>
          ))}
        </div>
        <div className="emoji-row" role="group" aria-label="Add an emoji to the chosen word">
          {EMOJI.map((e) => (
            <button key={e} className="btn small ghost emoji" onClick={() => onEmoji(picked, e)} aria-label={`Add ${e}`}>
              {e}
            </button>
          ))}
        </div>
        <button className="btn small" onClick={onRetranscribe} disabled={busy} title="Send this part of the video to the transcriber again (with your vocabulary)">
          {busy ? "Listening…" : "↻ Listen again · Pakinggan ulit"}
        </button>
      </section>

      <section className="insp-section">
        <h3>Look · Itsura</h3>
        <label className="toggle-inline small">
          <input type="checkbox" checked={applyAll} onChange={(e) => setApplyAll(e.target.checked)} /> Change every caption
        </label>
        <label className="insp-field">
          <span className="insp-label">Style</span>
          <select value={style.name} onChange={(e) => look({ style: e.target.value })} aria-label="Caption style">
            {STYLES.map((s, i) => (
              <option key={s.name} value={s.name}>
                {i + 1}. {s.name.replace(/_/g, " ")} — {s.description}
              </option>
            ))}
          </select>
        </label>
        <label className="insp-field">
          <span className="insp-label">Place</span>
          <select value={zone} onChange={(e) => look({ zone: e.target.value as CaptionLook["zone"] })} aria-label="Caption place">
            <option value="auto">The style's own place</option>
            <option value="lower">Lower part</option>
            <option value="center">Middle</option>
            <option value="top">Top</option>
          </select>
        </label>
        <label className="insp-field">
          <span className="insp-label">
            Size <span className="insp-value">{size}px</span>
          </span>
          <input type="range" min={24} max={200} step={1} value={size} onChange={(e) => look({ size: Number(e.target.value) })} aria-label="Caption size" />
        </label>
        <label className="toggle-inline small">
          <input type="checkbox" checked={clip.highlight_keywords !== false} onChange={(e) => look({ highlight_keywords: e.target.checked })} /> Show ★ highlights in colour
        </label>
        {onPunctuation && (
          <label className="toggle-inline small">
            <input type="checkbox" checked={punctuation === "keep"} data-testid="keep-punctuation" onChange={(e) => onPunctuation(e.target.checked ? "keep" : "remove")} /> Show punctuation (, . ! ?) in every caption
          </label>
        )}
      </section>
    </div>
  );
}
