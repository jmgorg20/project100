// The Templates tab: every graphics template with a live preview, search, a mood filter and
// favourites (kept on this PC). "Add" puts the template at the playhead on the Graphics track.
import { useEffect, useMemo, useRef, useState } from "react";
import "../../../graphics/fonts.css";
import "../../../graphics/templates/index.js";
import { instantiate, type GraphicInstance } from "../../../graphics/index.js";
import { CATALOG, CATEGORY_LABELS, searchTemplates, type TemplateMeta } from "../../shared/graphicsEdit";

const FAV_KEY = "autoedit.graphics.favourites";

function loadFavourites(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(FAV_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

/** A small live preview: built when it scrolls into view, it loops while visible. */
function TemplatePreview({ meta }: { meta: TemplateMeta }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let inst: GraphicInstance | null = null;
    let raf = 0;
    let t0 = 0;
    const loop = (now: number) => {
      if (!inst) return;
      if (!t0) t0 = now;
      const dur = inst.duration + 0.6;
      inst.update(((now - t0) / 1000) % dur);
      raf = requestAnimationFrame(loop);
    };
    const start = () => {
      if (inst) return;
      try {
        inst = instantiate(meta.id, meta.sample as Record<string, unknown>, { quality: "preview" });
      } catch (err) {
        console.error(`preview of ${meta.id}: ${(err as Error).message}`);
        return;
      }
      const tw = inst.w + 2 * inst.pad;
      const th = inst.h + 2 * inst.pad;
      const k = Math.min(el.clientWidth / tw, el.clientHeight / th) * 0.95;
      inst.tile.style.transformOrigin = "0 0";
      inst.tile.style.transform = `scale(${k})`;
      inst.tile.style.left = `${(el.clientWidth - tw * k) / 2}px`;
      inst.tile.style.top = `${(el.clientHeight - th * k) / 2}px`;
      el.appendChild(inst.tile);
      inst.update(meta.duration * 0.5);
      raf = requestAnimationFrame(loop);
    };
    const stop = () => {
      cancelAnimationFrame(raf);
      inst?.destroy();
      inst = null;
      t0 = 0;
    };
    const io = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver((entries) => (entries.some((e) => e.isIntersecting) ? start() : stop()))
      : null;
    if (io) io.observe(el);
    else start();
    return () => {
      io?.disconnect();
      stop();
    };
  }, [meta]);
  return <div className="tpl-preview" ref={host} aria-hidden="true" />;
}

export function TemplatesPanel({ onAdd }: { onAdd: (templateId: string) => void }) {
  const [query, setQuery] = useState("");
  const [mood, setMood] = useState("");
  const [onlyFav, setOnlyFav] = useState(false);
  const [favs, setFavs] = useState<Set<string>>(loadFavourites);
  const list = useMemo(() => searchTemplates(query, mood, onlyFav ? favs : undefined), [query, mood, onlyFav, favs]);
  const toggleFav = (id: string) => {
    const next = new Set(favs);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setFavs(next);
    try {
      localStorage.setItem(FAV_KEY, JSON.stringify([...next]));
    } catch {
      /* private mode: favourites last until the app closes */
    }
  };
  return (
    <div className="templates media-list" data-testid="templates-panel">
      <div className="tpl-tools">
        <input type="search" placeholder="Search · Hanapin" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search templates" />
        <select value={mood} onChange={(e) => setMood(e.target.value)} aria-label="Mood">
          <option value="">Any mood</option>
          {CATALOG.moods.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <label className="toggle-inline small">
          <input type="checkbox" checked={onlyFav} onChange={(e) => setOnlyFav(e.target.checked)} /> ★ only
        </label>
      </div>
      <p className="muted small">{list.length} of {CATALOG.templates.length} · Click Add to put one at the playhead.</p>
      <div className="tpl-grid">
        {list.map((t) => (
          <div key={t.id} className="tpl-card" data-testid={`tpl-${t.id}`}>
            <TemplatePreview meta={t} />
            <div className="tpl-name">
              <span title={t.tl}>{t.name}</span>
              <button className="fav" onClick={() => toggleFav(t.id)} aria-label={`${favs.has(t.id) ? "Remove from" : "Add to"} favourites: ${t.name}`} aria-pressed={favs.has(t.id)}>
                {favs.has(t.id) ? "★" : "☆"}
              </button>
            </div>
            <div className="tpl-moods">{CATEGORY_LABELS[t.category]?.label ?? t.category} · {t.moods.slice(0, 3).join(", ")}</div>
            <button className="btn small" onClick={() => onAdd(t.id)} aria-label={`Add ${t.name} at the playhead`}>Add</button>
          </div>
        ))}
        {!list.length && <p className="muted small">No template matches. Clear the search or the mood.</p>}
      </div>
    </div>
  );
}
