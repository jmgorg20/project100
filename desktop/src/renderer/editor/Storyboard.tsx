// The storyboard: the edit as scenes, before rendering. Each card shows a scene's purpose, length,
// source, words, transition, music/sounds and colour; you can approve everything, give one
// scene's graphics another look, replace its footage, change its words or lock it. It is a view
// of the timeline (shared/storyboard.ts): every change is an ordinary timeline edit.
import { useState } from "react";
import { scenes, type Scene } from "../../shared/storyboard";
import type { Project } from "../../shared/types";

const mmss = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
const TRANSITIONS: Record<string, string> = { start: "Start", cut: "Cut", flash: "Flash", whip: "Whip", punch: "Punch-in", wipe: "Wipe", shake: "Shake", glitch: "Glitch" };
const MOODS: Record<string, string> = { none: "As shot", natural_clean: "Natural", warm: "Warm", black_and_white: "Black & white", orange_teal: "Teal & orange", high_contrast: "High contrast" };

export interface StoryboardActions {
  busyScene: string | null;
  onSeek(t: number): void;
  onLock(id: string, locked: boolean): void;
  onText(id: string, text: string): void;
  onRegenerate(id: string, useAi: boolean): void;
  onReplace(scene: Scene): void;
  onApproveAll(): void;
  onTimeline(): void;
}

function SceneCard({ scene, actions }: { scene: Scene; actions: StoryboardActions }) {
  const [editing, setEditing] = useState<string | null>(null);
  const busy = actions.busyScene === scene.id;
  const music = [scene.music.join(", "), scene.sfx ? `${scene.sfx} sound${scene.sfx > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ") || "—";
  return (
    <article className={`sb-card${scene.locked ? " locked" : ""}`} data-testid={`scene-${scene.id}`} aria-label={`Scene ${scene.index}`}>
      <header className="row">
        <button className="btn small ghost" onClick={() => actions.onSeek(scene.start)} title="Play from here">▶ {scene.index}</button>
        <span className={`chip purpose-${scene.purpose}`}>{scene.purpose_label} · {scene.purpose_tl}</span>
        <span className="spacer" />
        <span className="muted small">{mmss(scene.start)} · {scene.duration.toFixed(1)} s</span>
        {scene.locked && <span title="Locked">🔒</span>}
      </header>
      {editing === null ? (
        <p className="sb-text" data-testid="scene-text">{scene.text || <span className="muted">(no words)</span>}</p>
      ) : (
        <textarea aria-label={`Words of scene ${scene.index}`} value={editing} rows={3} onChange={(e) => setEditing(e.target.value)} autoFocus />
      )}
      <dl className="sb-facts small">
        <dt>Source</dt><dd>{[...scene.sources, ...scene.broll.map((b) => `B-roll: ${b}`)].join(" · ") || "—"}</dd>
        <dt>Graphics</dt><dd data-testid="scene-graphics">{scene.graphics.map((g) => g.template).join(", ") || "—"}</dd>
        <dt>Transition</dt><dd>{TRANSITIONS[scene.transition] ?? scene.transition}</dd>
        <dt>Music / SFX</dt><dd>{music}</dd>
        <dt>Colour</dt><dd>{MOODS[scene.mood] ?? scene.mood}</dd>
      </dl>
      <div className="row wrap" style={{ gap: 6 }}>
        {editing === null ? (
          <button className="btn small" disabled={scene.locked || !scene.text} onClick={() => setEditing(scene.text)}>Edit words</button>
        ) : (
          <>
            <button className="btn small primary" onClick={() => { actions.onText(scene.id, editing); setEditing(null); }}>Save words</button>
            <button className="btn small ghost" onClick={() => setEditing(null)}>Cancel</button>
          </>
        )}
        <button className="btn small" disabled={scene.locked || busy} onClick={() => actions.onRegenerate(scene.id, false)} title="Another look for this scene's graphics (simple rules, no AI cost)">
          {busy ? "Working…" : "Regenerate"}
        </button>
        <button className="btn small ghost" disabled={scene.locked || busy} onClick={() => actions.onRegenerate(scene.id, true)} title="Ask the AI for this scene's graphics">with AI</button>
        <button className="btn small" disabled={scene.locked} onClick={() => actions.onReplace(scene)} title="Put another clip or picture over this scene">Replace footage</button>
        <button className="btn small ghost" onClick={() => actions.onLock(scene.id, !scene.locked)} aria-pressed={scene.locked}>{scene.locked ? "Unlock" : "Lock"}</button>
      </div>
    </article>
  );
}

export function Storyboard({ project, actions }: { project: Project; actions: StoryboardActions }) {
  const list = scenes(project);
  const approved = Boolean((project.meta?.storyboard as { approved?: boolean } | undefined)?.approved);
  return (
    <section className="storyboard" data-testid="storyboard" aria-label="Storyboard">
      <div className="row sb-head">
        <div>
          <h2>Storyboard · Mga eksena</h2>
          <p className="muted small">
            {list.length} scenes. Check each one before rendering. Everything here is also on the timeline as normal clips.
            {approved ? " Approved." : ""}
          </p>
        </div>
        <span className="spacer" />
        <button className="btn small ghost" onClick={actions.onTimeline}>Timeline</button>
        <button className="btn small primary" onClick={actions.onApproveAll} data-testid="approve-all">Approve all &amp; render · Aprubahan lahat</button>
      </div>
      <div className="sb-grid">
        {list.map((s) => <SceneCard key={`${s.id}-${s.start}`} scene={s} actions={actions} />)}
      </div>
    </section>
  );
}
