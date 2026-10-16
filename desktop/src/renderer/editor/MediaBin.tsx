// The project's files: import more, then drag one onto a track or add it at the playhead.
import type { Thumbs } from "../../shared/api";
import type { Project } from "../../shared/types";
import { mmss } from "../components/Player";

const KIND_ICON: Record<string, string> = { video: "🎬", image: "🖼", audio: "🎵" };

export function MediaBin({ project, thumbs, url, onImport, onAdd, busy }: {
  project: Project;
  thumbs: Record<string, Thumbs>;
  url: (p: string) => string;
  onImport: () => void;
  onAdd: (mediaId: string, where: "main" | "overlay" | "audio") => void;
  busy: boolean;
}) {
  return (
    <div className="media-bin" data-testid="media-bin">
      <div className="panel-head">
        <h2>Media</h2>
        <button className="btn small" onClick={onImport} disabled={busy}>{busy ? "Adding…" : "Import"}</button>
      </div>
      <div className="media-list">
        {project.media.length === 0 && (
          <p className="muted small">
            Import videos, pictures or music, then drag them onto the timeline.
            <br />
            Mag-import ng video, litrato o musika.
          </p>
        )}
        {project.media.map((m) => {
          const th = thumbs[m.id];
          return (
            <div
              key={m.id}
              className="media-item"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData("application/x-autoedit-media", m.id);
                e.dataTransfer.effectAllowed = "copy";
              }}
              data-testid="media-item"
              title={m.path}
            >
              <div className="media-thumb">
                {th?.files.length ? <img src={url(th.files[0])} alt="" draggable={false} /> : <span aria-hidden="true">{KIND_ICON[m.kind]}</span>}
              </div>
              <div className="media-meta">
                <div className="media-name">{m.name ?? m.path.split(/[\\/]/).pop()}</div>
                <div className="muted small">{m.kind === "image" ? "picture" : mmss(m.duration)}</div>
              </div>
              <div className="media-actions">
                {m.kind !== "audio" && (
                  <button className="btn small ghost" onClick={() => onAdd(m.id, "main")} title="Insert into the main video at the playhead" aria-label={`Add ${m.name} to the main video`}>＋ Video</button>
                )}
                {m.kind !== "audio" && (
                  <button className="btn small ghost" onClick={() => onAdd(m.id, "overlay")} title="Put on top of the video (B-roll) at the playhead" aria-label={`Add ${m.name} as B-roll`}>＋ B-roll</button>
                )}
                {(m.kind === "audio" || m.has_audio) && (
                  <button className="btn small ghost" onClick={() => onAdd(m.id, "audio")} title="Add as music/sound at the playhead" aria-label={`Add ${m.name} as sound`}>＋ Sound</button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
