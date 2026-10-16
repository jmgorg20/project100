// Settings of the selected clip: speed, volume, fades, reframe, overlay position, effects.
// Every change goes through the pure edit functions (shared/edit.ts), so values stay valid.
import type { ReactNode } from "react";
import type { CaptionLook } from "../../shared/captionEdit";
import { allowedProps, findClip, hasSource, speedOf, type ClipPatch } from "../../shared/edit";
import { FX_INFO, GRADES, RAMPS } from "../../shared/effectsEdit";
import type { FxEffect, Project, Word } from "../../shared/types";
import { mmss } from "../components/Player";
import { CaptionEditor } from "./CaptionEditor";

export interface CaptionActions {
  onWords: (id: string, words: Word[], key: string) => void;
  onWordText: (id: string, index: number, text: string) => void;
  onHighlight: (id: string, index: number) => void;
  onEmoji: (id: string, index: number, emoji: string) => void;
  onLook: (id: string, look: CaptionLook, all: boolean) => void;
  onRetranscribe: (id: string) => void;
  busy: boolean;
}

interface InspectorProps {
  project: Project;
  selection: string[];
  /** key groups quick changes (slider drags) into one undo step. */
  onProps: (id: string, patch: ClipPatch, key: string) => void;
  onSpeed: (id: string, speed: number) => void;
  onRamp: (id: string, ramp: string) => void;
  onDelete: () => void;
  captions: CaptionActions;
  /** Shown when nothing is selected (the project's own settings). */
  empty?: ReactNode;
}

function Slider({ label, hint, value, min, max, step, format, onChange, testId }: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
  testId?: string;
}) {
  return (
    <label className="insp-field">
      <span className="insp-label">
        {label} {hint && <span className="muted small">· {hint}</span>}
        <span className="insp-value">{format(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} data-testid={testId} />
    </label>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="insp-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

const SPEEDS = [0.5, 1, 1.5, 2, 3];
const pct = (v: number) => `${Math.round(v * 100)}%`;
const secs = (v: number) => `${v.toFixed(1)} s`;

export function Inspector({ project, selection, onProps, onSpeed, onRamp, onDelete, captions, empty }: InspectorProps) {
  if (selection.length > 1) {
    return (
      <div className="inspector" data-testid="inspector">
        <p className="muted">{selection.length} clips selected · {selection.length} clip ang napili</p>
        <button className="btn small danger" onClick={onDelete}>Delete them</button>
      </div>
    );
  }
  const found = selection.length ? findClip(project, selection[0]) : null;
  if (!found && empty) {
    return (
      <div className="inspector" data-testid="inspector">
        {empty}
      </div>
    );
  }
  if (!found) {
    return (
      <div className="inspector empty" data-testid="inspector">
        <h3>Nothing selected</h3>
        <p className="muted small">
          Click a clip on the timeline to change its speed, volume, fades or framing.
          <br />
          I-click ang isang clip para baguhin ito.
        </p>
        <p className="muted small">Press <kbd>?</kbd> for keyboard shortcuts.</p>
      </div>
    );
  }
  const { track, clip } = found;
  const allowed = allowedProps(track, clip);
  const m = project.media.find((x) => x.id === clip.media);
  const set = (patch: ClipPatch, key: string) => onProps(clip.id, patch, `${key}:${clip.id}`);
  const kindName =
    track.kind === "video"
      ? "Main video clip"
      : track.kind === "overlay"
        ? "B-roll / photo"
        : track.kind === "audio"
          ? `Sound (${track.name ?? track.role})`
          : track.kind === "caption"
            ? "Caption"
            : clip.type === "zoom"
              ? clip.ease
                ? "Smooth zoom"
                : "Punch-in zoom"
              : clip.type === "fx"
                ? `Effect: ${FX_INFO[clip.effect as FxEffect]?.label ?? clip.effect}`
                : "Colour grade";
  const crop = { zoom: clip.crop?.zoom ?? 1, x: clip.crop?.x ?? 0.5, y: clip.crop?.y ?? 0.5 };
  const maxFade = Math.min(5, clip.duration);

  return (
    <div className="inspector" data-testid="inspector">
      <div className="insp-head">
        <h3>{kindName}</h3>
        <span className="muted small" title={m?.path}>{m?.name ?? (clip.type === "caption" ? "" : clip.id)}</span>
      </div>
      <p className="muted small insp-times">
        {mmss(clip.start)} – {mmss(clip.start + clip.duration)} · {clip.duration.toFixed(2)} s
        {hasSource(clip) ? ` · source ${mmss(clip.in ?? 0)}–${mmss(clip.out ?? 0)}` : ""}
      </p>

      {hasSource(clip) && (
        <Section title="Speed · Bilis">
          <div className="seg-row" role="group" aria-label="Speed presets">
            {SPEEDS.map((s) => (
              <button key={s} className={`btn small${speedOf(clip) === s ? " primary" : ""}`} onClick={() => onSpeed(clip.id, s)}>
                {s}x
              </button>
            ))}
          </div>
          <Slider label="Speed" value={speedOf(clip)} min={0.25} max={4} step={0.05} format={(v) => `${v.toFixed(2)}x`} onChange={(v) => onSpeed(clip.id, v)} testId="speed" />
          <p className="muted small">The sound keeps its pitch. Main clips: what comes after moves to fit.</p>
          {track.kind === "video" && clip.type === "video" && (
            <label className="insp-field">
              <span className="insp-label">Speed ramp</span>
              <select value="" onChange={(e) => e.target.value && onRamp(clip.id, e.target.value)} aria-label="Speed ramp">
                <option value="">Choose a ramp…</option>
                {Object.entries(RAMPS).map(([k, r]) => (
                  <option key={k} value={k}>{r.label}</option>
                ))}
              </select>
            </label>
          )}
        </Section>
      )}

      {allowed.has("volume") && (
        <Section title="Sound · Tunog">
          <Slider label="Volume" value={clip.volume ?? 1} min={0} max={4} step={0.05} format={pct} onChange={(v) => set({ volume: v }, "volume")} testId="volume" />
          {(clip.volume ?? 1) > 1 && <p className="muted small">Above 100% the preview plays at 100%; the export is louder.</p>}
          <Slider label="Fade in" value={clip.fade_in ?? 0} min={0} max={maxFade} step={0.1} format={secs} onChange={(v) => set({ fade_in: v }, "fade_in")} testId="fade-in" />
          <Slider label="Fade out" value={clip.fade_out ?? 0} min={0} max={maxFade} step={0.1} format={secs} onChange={(v) => set({ fade_out: v }, "fade_out")} testId="fade-out" />
        </Section>
      )}

      {allowed.has("crop") && (
        <Section title="Frame · Pag-frame (9:16)">
          <label className="insp-field">
            <span className="insp-label">Fit</span>
            <select value={clip.fit ?? "fill"} onChange={(e) => set({ fit: e.target.value as "fill" | "blur" }, "fit")} aria-label="Fit">
              <option value="fill">Fill the screen (crop the sides)</option>
              <option value="blur">Show all, blurred background</option>
            </select>
          </label>
          {(clip.fit ?? "fill") === "fill" && (
            <>
              <Slider label="Zoom" value={crop.zoom} min={1} max={4} step={0.05} format={pct} onChange={(v) => set({ crop: { ...crop, zoom: v } }, "crop")} testId="crop-zoom" />
              <Slider label="Left ↔ right" value={crop.x} min={0} max={1} step={0.01} format={pct} onChange={(v) => set({ crop: { ...crop, x: v } }, "crop")} testId="crop-x" />
              <Slider label="Up ↕ down" value={crop.y} min={0} max={1} step={0.01} format={pct} onChange={(v) => set({ crop: { ...crop, y: v } }, "crop")} testId="crop-y" />
              <button className="btn small ghost" onClick={() => set({ crop: { zoom: 1, x: 0.5, y: 0.5 } }, "crop-reset")}>Reset framing</button>
            </>
          )}
        </Section>
      )}

      {allowed.has("x") && (
        <Section title="Position · Puwesto">
          <Slider label="Left ↔ right" value={clip.x ?? 540} min={0} max={1080} step={1} format={(v) => `${Math.round(v)}`} onChange={(v) => set({ x: v }, "x")} />
          <Slider label="Up ↕ down" value={clip.y ?? 960} min={0} max={1920} step={1} format={(v) => `${Math.round(v)}`} onChange={(v) => set({ y: v }, "y")} />
          <Slider label="Size" value={(clip.width ?? 1080) / 1080} min={0.1} max={1.5} step={0.01} format={pct}
            onChange={(v) => {
              const ratio = (clip.height ?? 1920) / (clip.width ?? 1080);
              set({ width: 1080 * v, height: 1080 * v * ratio }, "size");
            }} testId="overlay-size" />
          <Slider label="Opacity" value={clip.opacity ?? 1} min={0} max={1} step={0.01} format={pct} onChange={(v) => set({ opacity: v }, "opacity")} />
          <label className="insp-field">
            <span className="insp-label">Animation</span>
            <select value={clip.animation ?? "none"} onChange={(e) => set({ animation: e.target.value as "none" | "pop" }, "animation")} aria-label="Animation">
              <option value="none">None</option>
              <option value="pop">Pop in</option>
            </select>
          </label>
        </Section>
      )}

      {allowed.has("amount") && (
        <Section title="Zoom">
          <Slider label="Amount" value={clip.amount ?? 1.2} min={1} max={2.5} step={0.01} format={pct} onChange={(v) => set({ amount: v }, "amount")} />
          <Slider label="Towards" hint="top ↔ bottom" value={clip.anchor_y ?? 0.4} min={0} max={1} step={0.01} format={pct} onChange={(v) => set({ anchor_y: v }, "anchor")} />
          <Slider label="Zoom in over" hint="0 = punch-in" value={clip.ease ?? 0} min={0} max={Math.min(3, clip.duration)} step={0.05} format={secs} onChange={(v) => set({ ease: v }, "ease")} testId="zoom-ease" />
        </Section>
      )}

      {allowed.has("grade") && (
        <Section title="Colour · Kulay">
          <select value={clip.grade} onChange={(e) => set({ grade: e.target.value }, "grade")} aria-label="Colour grade">
            {GRADES.map((g) => (
              <option key={g} value={g}>{g.replace(/_/g, " ")}</option>
            ))}
          </select>
          <Slider label="Strength" value={clip.intensity ?? 1} min={0} max={1} step={0.01} format={pct} onChange={(v) => set({ intensity: v }, "intensity")} testId="intensity" />
        </Section>
      )}

      {allowed.has("effect") && (
        <Section title="Effect · Epekto">
          <select value={clip.effect} onChange={(e) => set({ effect: e.target.value as FxEffect }, "effect")} aria-label="Effect">
            {(Object.keys(FX_INFO) as FxEffect[]).map((k) => (
              <option key={k} value={k}>{FX_INFO[k].label} · {FX_INFO[k].tl}</option>
            ))}
          </select>
          <Slider label="Strength" value={clip.intensity ?? 0.6} min={0} max={1} step={0.01} format={pct} onChange={(v) => set({ intensity: v }, "intensity")} testId="intensity" />
          <p className="muted small">Drag the clip's edges on the timeline to make it longer or shorter.</p>
        </Section>
      )}

      {clip.type === "caption" && (
        <CaptionEditor
          clip={clip}
          busy={captions.busy}
          onWords={(words, key) => captions.onWords(clip.id, words, key)}
          onWordText={(i, text) => captions.onWordText(clip.id, i, text)}
          onHighlight={(i) => captions.onHighlight(clip.id, i)}
          onEmoji={(i, e) => captions.onEmoji(clip.id, i, e)}
          onLook={(l, all) => captions.onLook(clip.id, l, all)}
          onRetranscribe={() => captions.onRetranscribe(clip.id)}
        />
      )}

      <div className="insp-actions">
        <button className="btn small danger" onClick={onDelete}>Delete clip</button>
      </div>
    </div>
  );
}
