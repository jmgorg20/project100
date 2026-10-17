// Settings of a selected graphic (words, colours, font, size, position, emphasis, lock,
// another look) or of a before/after wipe.
import { useState } from "react";
import { ATTACH_LABELS, CATALOG, WIPE_DIRECTIONS, alternatives, templateMeta, type GraphicPatch, type WipePatch } from "../../shared/graphicsEdit";
import { GRADES } from "../../shared/effectsEdit";
import type { AttachKind, Clip, GraphicParams, Project } from "../../shared/types";
import { mmss } from "../components/Player";

export interface GraphicActions {
  onChange: (id: string, patch: GraphicPatch, key: string) => void;
  onWipe: (id: string, patch: WipePatch, key: string) => void;
  onLock: (id: string, locked: boolean) => void;
  onAnotherLook: (id: string) => void;
  /** Ask the engine for a new graphic for the same words (AI if a key is set, else rules). */
  onRegenerate: (id: string, useAi: boolean) => void;
  busy: boolean;
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="insp-field">
      <span className="insp-label">{label}</span>
      {children}
    </label>
  );
}

function Range({ label, value, min, max, step, format, onChange }: { label: string; value: number; min: number; max: number; step: number; format: (v: number) => string; onChange: (v: number) => void }) {
  return (
    <label className="insp-field">
      <span className="insp-label">
        {label} <span className="insp-value">{format(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
    </label>
  );
}

export function GraphicInspector({ project, clip, actions, onDelete }: { project: Project; clip: Clip; actions: GraphicActions; onDelete: () => void }) {
  const [ai, setAi] = useState(true);
  if (clip.type === "wipe") return <WipeInspector clip={clip} actions={actions} onDelete={onDelete} />;
  const meta = templateMeta(clip.template);
  const p: GraphicParams = clip.params ?? {};
  const locked = Boolean(clip.locked);
  const set = (params: GraphicParams, key: string) => actions.onChange(clip.id, { params }, `${key}:${clip.id}`);
  const fields = new Set([...(meta?.fields ?? []), ...(meta?.inputs.map((i) => i.key) ?? [])]);
  const defaults: GraphicParams = { color: "#ffffff", accent: "#ffd23f", bg: "#111827", ...(meta?.defaults ?? {}) };
  const options = [meta, ...alternatives(project, clip.id)].filter(Boolean);
  return (
    <div className="inspector" data-testid="inspector">
      <div className="insp-head">
        <h3>Graphic: {meta?.name ?? clip.template}</h3>
        <span className="muted small">{meta?.tl}</span>
      </div>
      <p className="muted small insp-times">
        {mmss(clip.start)} – {mmss(clip.start + clip.duration)} · {clip.duration.toFixed(2)} s
        {clip.director?.words ? ` · on “${clip.director.words}”` : ""}
      </p>
      {clip.director && (
        <p className="muted small" data-testid="director-note">
          AI {clip.director.style?.replace(/_/g, " ")} · mood {clip.director.mood}{clip.director.reason ? ` · ${clip.director.reason}` : ""}
        </p>
      )}
      <label className="toggle-inline">
        <input type="checkbox" checked={locked} onChange={(e) => actions.onLock(clip.id, e.target.checked)} aria-label="Lock this graphic" data-testid="lock" /> Lock · I-lock
        <span className="muted small"> (no moving or changing; the AI keeps it)</span>
      </label>
      <fieldset disabled={locked} className="insp-fieldset">
        <section className="insp-section">
          <h3>Look · Itsura</h3>
          <Field label="Template">
            <select value={clip.template} onChange={(e) => actions.onChange(clip.id, { template: e.target.value }, `template:${clip.id}`)} aria-label="Template">
              {options.map((o) => (
                <option key={o!.id} value={o!.id}>{o!.name}</option>
              ))}
            </select>
          </Field>
          <div className="seg-row">
            <button className="btn small" onClick={() => actions.onAnotherLook(clip.id)} data-testid="another-look" title="The next template of the same kind (never the same as its neighbours)">Another look</button>
            <button className="btn small" onClick={() => actions.onRegenerate(clip.id, ai)} disabled={actions.busy} data-testid="regenerate">{actions.busy ? "Working…" : "Regenerate"}</button>
            <label className="toggle-inline small"><input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} /> ask the AI</label>
          </div>
        </section>
        <section className="insp-section">
          <h3>Words · Mga salita</h3>
          {fields.has("text") && (
            <Field label="Text (write *word* to make it stand out)">
              <textarea rows={2} value={p.text ?? ""} maxLength={meta?.maxChars ? meta.maxChars + 20 : 200} onChange={(e) => set({ text: e.target.value }, "text")} aria-label="Text" data-testid="graphic-text" />
              {meta && (p.text ?? "").replace(/\*/g, "").length > meta.maxChars && <span className="warn small">Longer than this graphic is made for ({meta.maxChars} letters): it will be cut.</span>}
            </Field>
          )}
          {fields.has("text2") && <Field label="Second line / label"><input value={p.text2 ?? ""} onChange={(e) => set({ text2: e.target.value }, "text2")} aria-label="Second text" /></Field>}
          {fields.has("items") && (
            <Field label="Items (one per line)">
              <textarea rows={3} value={(p.items ?? []).join("\n")} onChange={(e) => set({ items: e.target.value.split("\n") }, "items")} aria-label="Items" />
            </Field>
          )}
          {fields.has("number") && (
            <div className="seg-row">
              <Field label="Number"><input type="number" value={p.number ?? 0} onChange={(e) => set({ number: Number(e.target.value) }, "number")} aria-label="Number" /></Field>
              <Field label="Before"><input value={p.prefix ?? ""} size={3} onChange={(e) => set({ prefix: e.target.value }, "prefix")} aria-label="Prefix" /></Field>
              <Field label="After"><input value={p.suffix ?? ""} size={3} onChange={(e) => set({ suffix: e.target.value }, "suffix")} aria-label="Suffix" /></Field>
            </div>
          )}
          {fields.has("emoji") && <Field label="Emoji"><input value={p.emoji ?? ""} onChange={(e) => set({ emoji: e.target.value }, "emoji")} aria-label="Emoji" /></Field>}
          {fields.has("icon") && (
            <Field label="Icon">
              <select value={p.icon ?? ""} onChange={(e) => set({ icon: e.target.value }, "icon")} aria-label="Icon">
                {CATALOG.icons.map((i) => <option key={i} value={i}>{i}</option>)}
              </select>
            </Field>
          )}
          {fields.has("image") && (
            <Field label="Picture">
              <select value={p.image ?? ""} onChange={(e) => set({ image: e.target.value }, "image")} aria-label="Picture">
                <option value="">(none: a colour)</option>
                {project.media.filter((m) => m.kind === "image").map((m) => <option key={m.id} value={m.id}>{m.name ?? m.id}</option>)}
              </select>
            </Field>
          )}
        </section>
        <section className="insp-section">
          <h3>Colour, font, size · Kulay at laki</h3>
          <div className="seg-row">
            {(["color", "accent", "bg"] as const).filter((k) => fields.has(k)).map((k) => (
              <Field key={k} label={{ color: "Text", accent: "Accent", bg: "Background" }[k]}>
                <input type="color" value={p[k] ?? defaults[k]} onChange={(e) => set({ [k]: e.target.value }, k)} aria-label={`${k} colour`} />
              </Field>
            ))}
          </div>
          {fields.has("font") && (
            <Field label="Font">
              <select value={p.font ?? ""} onChange={(e) => set({ font: e.target.value }, "font")} aria-label="Font">
                <option value="">The template's own</option>
                {Object.entries(CATALOG.fonts).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </Field>
          )}
          <Range label="Size" value={p.size ?? 1} min={0.4} max={2.5} step={0.05} format={pct} onChange={(v) => set({ size: v }, "size")} />
          <Range label="Intensity" value={p.intensity ?? 0.7} min={0} max={1} step={0.05} format={pct} onChange={(v) => set({ intensity: v }, "intensity")} />
          {fields.has("angle") && <Range label="Points to (angle)" value={p.angle ?? 0} min={-180} max={180} step={5} format={(v) => `${v}°`} onChange={(v) => set({ angle: v }, "angle")} />}
        </section>
        <section className="insp-section">
          <h3>Place · Puwesto</h3>
          <Range label="Across" value={clip.x ?? 0.5} min={0} max={1} step={0.01} format={pct} onChange={(v) => actions.onChange(clip.id, { x: v }, `x:${clip.id}`)} />
          <Range label="Up / down" value={clip.y ?? 0.5} min={0} max={1} step={0.01} format={pct} onChange={(v) => actions.onChange(clip.id, { y: v }, `y:${clip.id}`)} />
          <Field label="On the picture when it starts">
            <select
              value={clip.attach?.kind ?? ""}
              onChange={(e) => actions.onChange(clip.id, { attach: e.target.value ? { kind: e.target.value as AttachKind, intensity: clip.attach?.intensity ?? 0.6 } : null }, `attach:${clip.id}`)}
              aria-label="Emphasis transition"
            >
              <option value="">Nothing</option>
              {(Object.keys(ATTACH_LABELS) as AttachKind[]).map((k) => <option key={k} value={k}>{ATTACH_LABELS[k]}</option>)}
            </select>
          </Field>
        </section>
      </fieldset>
      <button className="btn small danger" onClick={onDelete} disabled={locked}>Delete</button>
    </div>
  );
}

function WipeInspector({ clip, actions, onDelete }: { clip: Clip; actions: GraphicActions; onDelete: () => void }) {
  const set = (patch: WipePatch, key: string) => actions.onWipe(clip.id, patch, `${key}:${clip.id}`);
  return (
    <div className="inspector" data-testid="inspector">
      <div className="insp-head"><h3>Before / after wipe</h3></div>
      <p className="muted small">A line sweeps across; the side it has passed gets the colour look.</p>
      <Field label="Colour look (the after side)">
        <select value={clip.grade} onChange={(e) => set({ grade: e.target.value }, "grade")} aria-label="Wipe grade">
          {GRADES.filter((g) => g !== "none").map((g) => <option key={g} value={g}>{g.replace(/_/g, " ")}</option>)}
        </select>
      </Field>
      <Field label="Direction">
        <select value={clip.direction ?? "right"} onChange={(e) => set({ direction: e.target.value as WipePatch["direction"] }, "direction")} aria-label="Wipe direction">
          {WIPE_DIRECTIONS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </Field>
      <Range label="Strength" value={clip.intensity ?? 1} min={0} max={1} step={0.05} format={pct} onChange={(v) => set({ intensity: v }, "intensity")} />
      <Range label="Sweep time" value={clip.sweep ?? 0.8} min={0.2} max={3} step={0.1} format={(v) => `${v.toFixed(1)} s`} onChange={(v) => set({ sweep: v }, "sweep")} />
      <Range label="Stops at" value={clip.stop ?? 0.5} min={0.05} max={0.95} step={0.05} format={pct} onChange={(v) => set({ stop: v }, "stop")} />
      <label className="toggle-inline"><input type="checkbox" checked={clip.divider !== false} onChange={(e) => set({ divider: e.target.checked }, "divider")} /> White divider line</label>
      <button className="btn small danger" onClick={onDelete}>Delete</button>
    </div>
  );
}
