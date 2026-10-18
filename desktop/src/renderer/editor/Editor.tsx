// The timeline editor (CapCut-like): big preview on top, multi-track timeline below, media on
// the left and the selected clip's settings on the right. Opens a .project.json (the AI's
// result is one), saves by itself, and exports with the FFmpeg engine.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BrollFound, BrollRequest, OpenedProject, Peaks, Thumbs, TrackStatus } from "../../shared/api";
import { addTrackFx, untrackedEffects } from "../../shared/trackEdit";
import { addBroll, brollCredits, brollExclusions, replaceBroll, setBrollRequest } from "../../shared/brollEdit";
import {
  EditError, addMedia, clipEnd, deleteClips, findClip, insertMedia, mainTrack, projectDuration, setClipProps, setSpeed, setTrackFlag,
  splitAt, splitClip, type ClipPatch,
} from "../../shared/edit";
import { baseName, exportPathFor, resolveMediaPath } from "../../shared/paths";
import type { BrollMeta, Media, Project, TrackEffect } from "../../shared/types";
import { createHistory, pushHistory, redoHistory, undoHistory, type History } from "../../shared/undo";
import { FrameDialog } from "../components/Dialogs";
import { Player, mmss, type PlayerHandle } from "../components/Player";
import { api, mediaUrl } from "../lib/api";
import { addCaption, addEmoji, correctCaptions, editWordText, setCaptionLook, setCaptionWords, toggleHighlight } from "../../shared/captionEdit";
import { addFx, addGrade, addTransition, addZoom, setAudioSettings, speedRamp } from "../../shared/effectsEdit";
import { addGraphic, addWipe, anotherLook, setClipLocked, setGraphic, setWipe } from "../../shared/graphicsEdit";
import { ExportDialog } from "./ExportDialog";
import { Storyboard } from "./Storyboard";
import { freeze, setSceneLocked, setSceneText, type Scene } from "../../shared/storyboard";
import { Inspector } from "./Inspector";
import { LeftPanel } from "./LeftPanel";
import { ProjectPanel } from "./ProjectPanel";
import { Recorder } from "./Recorder";
import { TrackSetup } from "./TrackSetup";
import type { BrollAsk } from "./BrollPanel";
import { VocabularyDialog } from "./VocabularyDialog";
import { SHORTCUTS, actionFor, typingInto, type Action } from "./shortcuts";
import { Timeline } from "./Timeline";

const AUTOSAVE_MS = 700;
const MIN_PPS = 4;
const MAX_PPS = 600;

type SaveState = { state: "saved" | "saving" | "unsaved" | "error"; message?: string };

export function Editor({ path, onClose, startIn = "timeline" }: { path: string; onClose: () => void; startIn?: "timeline" | "storyboard" }) {
  const [view, setView] = useState<"timeline" | "storyboard">(startIn);
  const [sceneBusy, setSceneBusy] = useState<string | null>(null);
  const [opened, setOpened] = useState<OpenedProject | null>(null);
  const [history, setHistory] = useState<History<Project> | null>(null);
  const [draft, setDraft] = useState<Project | null>(null);
  const [selection, setSelection] = useState<string[]>([]);
  const [playhead, setPlayhead] = useState(0);
  const [pps, setPps] = useState(60);
  const [snapping, setSnapping] = useState(true);
  const [save, setSave] = useState<SaveState>({ state: "saved" });
  const [toast, setToast] = useState<string | null>(null);
  const [peaks, setPeaks] = useState<Record<string, Peaks>>({});
  const [thumbs, setThumbs] = useState<Record<string, Thumbs>>({});
  const [showExport, setShowExport] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [importing, setImporting] = useState(false);
  const [showRecorder, setShowRecorder] = useState(false);
  const [showVocab, setShowVocab] = useState(false);
  const [retranscribing, setRetranscribing] = useState(false);
  const [folders, setFolders] = useState({ music: "", sfx: "", broll: "" });
  const [stockKeys, setStockKeys] = useState<string[]>([]);
  useEffect(() => {
    api.getSettings().then((st) => {
      setFolders({ music: st.musicFolder ?? "", sfx: st.sfxFolder ?? "", broll: st.brollFolder ?? "" });
      api.keysStatus().then((k) => setStockKeys(st.useStock === false ? [] : (["pexels", "pixabay"] as const).filter((x) => k[x]?.set).map((x) => (x === "pexels" ? "Pexels" : "Pixabay"))));
    });
  }, []);
  type BrollTarget = { kind: "new"; at: number; duration: number; position: "full" | "top" | "center" } | { kind: "clip"; clipId: string };
  const [brollTask, setBrollTask] = useState<{ id: string; label: string; percent?: number; target: BrollTarget } | null>(null);
  const brollTaskRef = useRef<typeof brollTask>(null);
  brollTaskRef.current = brollTask;

  // ---- tracking: follow the speaker's hands / face (the engine saves the points in the project file)
  const [trackStatus, setTrackStatus] = useState<TrackStatus | null>(null);
  const [trackTask, setTrackTask] = useState<{ id: string; label: string; percent?: number } | null>(null);
  const [showTrackSetup, setShowTrackSetup] = useState(false);
  const trackTaskRef = useRef<typeof trackTask>(null);
  trackTaskRef.current = trackTask;
  useEffect(() => {
    api.trackStatus().then((r) => !("error" in r) && setTrackStatus(r));
  }, []);
  const [frame, setFrame] = useState<{ url?: string; error?: string } | null>(null);
  const [playing, setPlaying] = useState(false);
  const playerRef = useRef<PlayerHandle>(null);
  const requested = useRef(new Set<string>());
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedProject = useRef<Project | null>(null);

  const project = draft ?? history?.present ?? null;
  const fps = project?.settings.fps ?? 30;
  const url = useCallback((p: string) => mediaUrl(resolveMediaPath(path, p)), [path]);

  // ---- open
  useEffect(() => {
    let alive = true;
    api.openProject(path).then((o) => {
      if (!alive) return;
      setOpened(o);
      if (o.project) {
        setHistory(createHistory(o.project));
        savedProject.current = o.project;
        const total = projectDuration(o.project);
        setPps(Math.max(MIN_PPS, Math.min(120, 900 / Math.max(total, 1))));
      }
    });
    return () => {
      alive = false;
    };
  }, [path]);

  // ---- waveforms and filmstrips (made by the engine, cached)
  useEffect(() => {
    if (!project) return;
    for (const m of project.media) {
      if (requested.current.has(m.id)) continue;
      requested.current.add(m.id);
      const file = resolveMediaPath(path, m.path);
      if (m.kind === "audio" || (m.kind === "video" && m.has_audio !== false)) {
        api.peaks(file).then((r) => !("error" in r) && setPeaks((x) => ({ ...x, [m.id]: r })));
      }
      if (m.kind !== "audio") api.thumbs(file).then((r) => !("error" in r) && setThumbs((x) => ({ ...x, [m.id]: r })));
    }
  }, [project, path]);

  // ---- saving (by itself, shortly after each change)
  const saveNow = useCallback(async (): Promise<string | null> => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = null;
    const current = history?.present;
    if (!current || current === savedProject.current) return null;
    setSave({ state: "saving" });
    const r = await api.saveProject(path, current);
    if (r.ok) {
      savedProject.current = current;
      setSave({ state: "saved" });
      return null;
    }
    setSave({ state: "error", message: r.error });
    return r.error ?? "Could not save.";
  }, [history, path]);

  useEffect(() => {
    if (!history || history.present === savedProject.current) return;
    setSave({ state: "unsaved" });
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void saveNow(), AUTOSAVE_MS);
  }, [history, saveNow]);

  const close = async () => {
    const problem = await saveNow();
    if (problem && !window.confirm(`${problem}\n\nClose anyway? Your last changes are not saved.`)) return;
    onClose();
  };

  // ---- editing
  // The latest history, updated at once (several edits in one event chain correctly).
  const histRef = useRef<History<Project> | null>(null);
  histRef.current = history;
  const commit = useCallback((next: History<Project>) => {
    histRef.current = next;
    setHistory(next);
  }, []);
  const apply = useCallback(
    (fn: (p: Project) => Project, key?: string) => {
      const h = histRef.current;
      if (!h) return;
      try {
        commit(pushHistory(h, fn(h.present), key));
      } catch (err) {
        if (!(err instanceof EditError)) throw err;
        setToast(err.message);
      }
    },
    [commit],
  );

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  // Forget a selection whose clips are gone (after undo, delete...).
  useEffect(() => {
    if (project) setSelection((sel) => (sel.every((id) => findClip(project, id)) ? sel : sel.filter((id) => findClip(project, id))));
  }, [project]);

  const seek = useCallback((t: number) => {
    playerRef.current?.seek(t);
    setPlayhead(Math.max(0, t));
  }, []);

  const split = () => {
    if (!project) return;
    const t = playhead;
    const under = selection.filter((id) => {
      const f = findClip(project, id);
      return f && t > f.clip.start && t < clipEnd(f.clip);
    });
    apply((p) => (under.length ? under.reduce((q, id) => splitClip(q, id, t).project, p) : splitAt(p, t)));
  };

  const remove = () => {
    if (!selection.length) return;
    apply((p) => deleteClips(p, selection));
    setSelection([]);
  };

  const editPoints = useMemo(() => {
    const pts = new Set<number>([0]);
    for (const c of project ? mainTrack(project)?.clips ?? [] : []) {
      pts.add(c.start);
      pts.add(clipEnd(c));
    }
    return [...pts].sort((a, b) => a - b);
  }, [project]);

  const zoomTo = useCallback((next: number) => setPps(Math.max(MIN_PPS, Math.min(MAX_PPS, next))), []);

  const run = useCallback(
    (action: Action) => {
      if (!project) return;
      const total = projectDuration(project);
      const frameT = Math.round(playhead * fps) / fps;
      switch (action) {
        case "play":
          playerRef.current?.toggle();
          break;
        case "split":
          split();
          break;
        case "delete":
          remove();
          break;
        case "undo":
          if (histRef.current) commit(undoHistory(histRef.current));
          break;
        case "redo":
          if (histRef.current) commit(redoHistory(histRef.current));
          break;
        case "frameBack":
          seek(frameT - 1 / fps);
          break;
        case "frameForward":
          seek(frameT + 1 / fps);
          break;
        case "secondBack":
          seek(playhead - 1);
          break;
        case "secondForward":
          seek(playhead + 1);
          break;
        case "prevEdit":
          seek([...editPoints].reverse().find((x) => x < playhead - 1e-3) ?? 0);
          break;
        case "nextEdit":
          seek(editPoints.find((x) => x > playhead + 1e-3) ?? total);
          break;
        case "home":
          seek(0);
          break;
        case "end":
          seek(total);
          break;
        case "zoomIn":
          zoomTo(pps * 1.5);
          break;
        case "zoomOut":
          zoomTo(pps / 1.5);
          break;
        case "zoomFit":
          zoomTo((document.querySelector(".tl-scroll")?.clientWidth ?? 900) / Math.max(1, total + 1));
          break;
        case "snapping":
          setSnapping((s) => !s);
          break;
        case "save":
          void saveNow();
          break;
        case "export":
          setShowExport(true);
          break;
        case "deselect":
          setSelection([]);
          break;
        case "help":
          setShowHelp((h) => !h);
          break;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [project, playhead, fps, selection, editPoints, pps, saveNow],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (showExport || frame || showRecorder || showVocab || typingInto(e.target)) return;
      const action = actionFor(e);
      if (!action) return;
      e.preventDefault();
      run(action);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, showExport, frame, showRecorder, showVocab]);

  // ---- media
  const importFiles = async (paths: string[]) => {
    if (!paths.length) return;
    setImporting(true);
    const r = await api.mediaInfo(paths);
    setImporting(false);
    if (r.errors.length) setToast(r.errors.map((e) => `${baseName(e.path)}: ${e.message}`).join("\n"));
    if (r.media.length) apply((p) => addMedia(p, r.media).project);
  };

  const addAt = (mediaId: string, where: "main" | "overlay" | "audio" | string, at = playhead) => {
    let added: string | null = null;
    apply((p) => {
      let trackId: string | undefined = where;
      if (where === "main") trackId = mainTrack(p)?.id;
      else if (where === "overlay") trackId = p.tracks.find((t) => t.kind === "overlay")?.id;
      else if (where === "audio") trackId = p.tracks.find((t) => t.kind === "audio" && t.role === "music")?.id ?? p.tracks.find((t) => t.kind === "audio")?.id;
      const r = insertMedia(p, mediaId, at, trackId);
      added = r.clipId;
      return r.project;
    });
    if (added) setSelection([added]);
  };

  /** A file from your music/sound folders or a new recording: add it on its sound track. */
  const addSoundFile = async (file: string, role: "music" | "sfx" | "voiceover") => {
    const r = await api.mediaInfo([file]);
    if (!r.media.length) {
      setToast(r.errors[0]?.message ?? `Could not read ${baseName(file)}.`);
      return;
    }
    let added: string | null = null;
    apply((p) => {
      const withMedia = addMedia(p, r.media);
      const q = withMedia.project;
      const track = q.tracks.find((t) => t.kind === "audio" && t.role === role && !t.locked);
      const target = track ? q : { ...q, tracks: [...q.tracks, { id: `${role}_${Date.now() % 100000}`, kind: "audio" as const, role, name: role === "sfx" ? "Sound effects" : role === "voiceover" ? "Voice-over" : "Music", clips: [] }] };
      const trackId = (track ?? target.tracks[target.tracks.length - 1]).id;
      const ins = insertMedia(target, withMedia.ids[0], playhead, trackId);
      added = ins.clipId;
      return ins.project;
    });
    if (added) setSelection([added]);
  };

  const chooseFolder = async (kind: "music" | "sfx") => {
    const folder = await api.pickFolder(kind === "music" ? "Your music folder" : "Your sound-effects folder");
    if (!folder) return;
    await api.setSettings(kind === "music" ? { musicFolder: folder } : { sfxFolder: folder });
    setFolders((f) => ({ ...f, [kind]: folder }));
  };

  const withNewClip = (fn: (p: Project) => { project: Project; clipId: string }) => {
    let added: string | null = null;
    apply((p) => {
      const r = fn(p);
      added = r.clipId;
      return r.project;
    });
    if (added) setSelection([added]);
  };

  // ---- B-roll: found or made by the engine, then put on the timeline (one undo step)
  // What "find another" already showed on each clip (this session), so it moves on.
  const brollTried = useRef(new Map<string, Set<string>>());
  const placeBroll = (found: BrollFound, target: BrollTarget) => {
    if (target.kind === "clip") {
      const before = histRef.current ? findClip(histRef.current.present, target.clipId) : null;
      const tried = brollTried.current.get(target.clipId) ?? new Set<string>();
      const old = before && histRef.current?.present.media.find((m) => m.id === before.clip.media);
      if (old) tried.add(old.path);
      if (before?.clip.broll?.stock_id) tried.add(before.clip.broll.stock_id);
      tried.add(found.media.path);
      if (found.broll.stock_id) tried.add(found.broll.stock_id);
      brollTried.current.set(target.clipId, tried);
      apply((p) => replaceBroll(p, target.clipId, found.media, found.broll));
      setSelection([target.clipId]);
    } else withNewClip((p) => addBroll(p, found.media, found.broll, target.at, target.duration, target.position));
    const notes = found.notes.filter((n) => !n.startsWith("Not done: AI pictures, clips and voice-over"));
    setToast(`B-roll: ${found.broll.source === "ai" ? "made with AI" : found.broll.source === "library" ? "from your folder" : found.broll.credit ?? "added"}.${notes.length ? `\n${notes.join("\n")}` : ""}`);
  };

  useEffect(
    () =>
      api.onBroll((u) => {
        const task = brollTaskRef.current;
        if (!task || u.taskId !== task.id) return;
        if (!u.done) {
          setBrollTask({ ...task, label: u.label ?? task.label, percent: u.label ? undefined : u.percent ?? task.percent });
          return;
        }
        setBrollTask(null);
        if (u.result) placeBroll(u.result, task.target);
        else if (!u.cancelled) setToast(u.error ?? "No B-roll was found or made.");
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const startBroll = async (request: Omit<BrollRequest, "projectPath">, target: BrollTarget) => {
    if (brollTaskRef.current) return;
    const id = await api.startBroll({ ...request, projectPath: path });
    setBrollTask({ id, label: "Finding B-roll", target });
  };

  const askBroll = (ask: BrollAsk) =>
    void startBroll({ ...ask, exclude: project ? brollExclusions(project) : [], newVersion: false }, { kind: "new", at: playhead, duration: ask.duration, position: ask.position });

  const againBroll = (clipId: string, mode: "another" | "ai", quality: "draft" | "final" = "final") => {
    if (!project) return;
    const f = findClip(project, clipId);
    if (!f) return;
    const meta: BrollMeta = f.clip.broll ?? { source: "file" };
    void startBroll(
      {
        kind: meta.kind ?? (f.clip.type === "video" ? "video" : "image"), prompt: meta.prompt ?? "", search: meta.search ?? "", style: meta.style ?? "realistic",
        source: mode === "ai" ? "ai" : "auto", duration: f.clip.duration, position: meta.position ?? "full", quality,
        exclude: [...new Set([...brollExclusions(project, clipId), ...(brollTried.current.get(clipId) ?? [])])], newVersion: true,
      },
      { kind: "clip", clipId },
    );
  };

  /** A picture/video you chose: as a new B-roll clip, or in place of a B-roll clip's file. */
  const brollFromFile = async (file: string, target: BrollTarget, source: "library" | "file") => {
    const r = await api.mediaInfo([file]);
    const media: Media | undefined = r.media[0];
    if (!media) return setToast(r.errors[0]?.message ?? `Could not read ${baseName(file)}.`);
    if (media.kind === "audio") return setToast("That is a sound file. Choose a picture or a video.");
    const old = target.kind === "clip" && project ? findClip(project, target.clipId)?.clip.broll : undefined;
    const words = (media.name ?? baseName(file)).replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
    const meta: BrollMeta = { source, kind: media.kind === "video" ? "video" : "image", prompt: old?.prompt ?? words, search: old?.search ?? words, style: old?.style ?? "realistic", ai_generated: false };
    if (target.kind === "new") target = { ...target, duration: media.kind === "video" ? Math.min(media.duration, target.duration) : target.duration };
    placeBroll({ file, media, broll: meta, notes: [] }, target);
  };

  const chooseBrollFolder = async () => {
    const folder = await api.pickFolder("Your B-roll folder");
    if (!folder) return;
    await api.setSettings({ brollFolder: folder });
    setFolders((f) => ({ ...f, broll: folder }));
  };

  useEffect(
    () =>
      api.onTrack(async (u) => {
        const task = trackTaskRef.current;
        if (!task || u.taskId !== task.id) return;
        if (!u.done) {
          setTrackTask({ ...task, label: u.label ?? task.label, percent: u.percent ?? task.percent });
          return;
        }
        setTrackTask(null);
        if (u.cancelled) return;
        if (u.error) return setToast(u.error);
        // The engine saved the points in the project file: read it back (one undo step).
        const o = await api.openProject(path);
        if (!o.project) return setToast(o.error ?? "Could not read the tracked project.");
        savedProject.current = o.project;
        if (histRef.current) commit(pushHistory(histRef.current, o.project));
        savedProject.current = histRef.current?.present ?? o.project;
        const found = Object.entries(u.found ?? {}).filter(([, v]) => v >= 0.25).map(([k, v]) => `${k.replace(/_/g, " ")} ${Math.round(v * 100)}%`);
        setToast(found.length ? `Followed: ${found.join(", ")} of the tracked time.` : "Followed, but no hand or face was found. Is the speaker visible and well lit?");
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [path],
  );

  const followHands = async () => {
    if (trackTaskRef.current) return;
    const problem = await saveNow();
    if (problem) return setToast(problem);
    const id = await api.startTrack(path);
    setTrackTask({ id, label: "Following your hands and face" });
  };

  const addTracked = async (effect: TrackEffect) => {
    let media: string | undefined;
    if (effect === "clip") {
      // Your own effect clip: a video or picture (black background, or with its own alpha).
      const files = await api.pickMedia();
      if (!files.length) return;
      const r = await api.mediaInfo(files.slice(0, 1));
      const m = r.media.find((x) => x.kind !== "audio");
      if (!m) return setToast(r.errors[0]?.message ?? "Choose a video or picture file for your effect.");
      const added = addMedia(histRef.current!.present, [m]);
      media = added.ids[0];
      apply((p) => addMedia(p, [m]).project);
    }
    withNewClip((p) => addTrackFx(p, effect, playhead, { media }));
    if (project && !project.tracking) setToast("Added. Now click “Follow my hands in this video” so the effect has something to follow.");
  };

  const retranscribe = async (id: string) => {
    if (!project) return;
    const f = findClip(project, id);
    if (!f) return;
    const problem = await saveNow();
    if (problem) return setToast(problem);
    setRetranscribing(true);
    const r = await api.retranscribe(path, f.clip.start, f.clip.start + f.clip.duration);
    setRetranscribing(false);
    if (!r.project) return setToast(r.error ?? "Could not transcribe that part again.");
    savedProject.current = r.project; // the engine saved it
    if (histRef.current) commit(pushHistory(histRef.current, r.project));
    savedProject.current = histRef.current?.present ?? r.project;
    setToast(`Listened again: ${r.words ?? 0} words. Undo (Ctrl+Z) brings the old captions back.`);
  };

  const [regenerating, setRegenerating] = useState(false);
  /** A new graphic for the same words, made by the engine's Director (one undo step). */
  const regenerateGraphic = async (id: string, useAi: boolean) => {
    const problem = await saveNow();
    if (problem) return setToast(problem);
    setRegenerating(true);
    const settings = await api.getSettings();
    const r = await api.graphicsRegenerate(path, id, useAi, settings.provider);
    setRegenerating(false);
    if (!r.project) return setToast(r.error ?? "Could not make another graphic.");
    savedProject.current = r.project;
    if (histRef.current) commit(pushHistory(histRef.current, r.project));
    savedProject.current = histRef.current?.present ?? r.project;
  };

  const regenerateScene = async (id: string, useAi: boolean) => {
    const problem = await saveNow();
    if (problem) return setToast(problem);
    setSceneBusy(id);
    const settings = await api.getSettings();
    const r = await api.storyboardRegenerate(path, id, useAi, settings.provider);
    setSceneBusy(null);
    if (!r.project) return setToast(r.error ?? "Could not regenerate this scene.");
    if (r.notes?.length) setToast(r.notes[0]);
    savedProject.current = r.project;
    if (histRef.current) commit(pushHistory(histRef.current, r.project));
    savedProject.current = histRef.current?.present ?? r.project;
  };

  const replaceSceneFootage = async (scene: Scene) => {
    const files = await api.pickMedia();
    if (!files.length || !project) return;
    const overlay = scene.clips.find((id) => findClip(project, id)?.track.kind === "overlay");
    await brollFromFile(files[0], overlay ? { kind: "clip", clipId: overlay } : { kind: "new", at: scene.start, duration: scene.duration, position: "full" }, "file");
  };

  const approveAll = () => {
    apply((p) => {
      const q = freeze(p);
      return { ...q, meta: { ...q.meta, storyboard: { ...(q.meta?.storyboard as object), approved: true } } };
    });
    setShowExport(true);
  };

  const exactFrame = async () => {
    const problem = await saveNow();
    if (problem) {
      setFrame({ error: problem });
      return;
    }
    setFrame({});
    const r = await api.renderFrame(path, playhead);
    setFrame(r.path ? { url: mediaUrl(r.path) } : { error: r.error ?? "The frame could not be rendered." });
  };

  // ---- render
  if (!opened || (!project && !opened.error)) {
    return (
      <div className="editor loading" data-testid="editor">
        <p className="muted">Opening {baseName(path)}… · Binubuksan…</p>
      </div>
    );
  }
  if (opened.error || !project || !history) {
    return (
      <div className="editor loading" data-testid="editor">
        <div className="card" role="alert" style={{ maxWidth: 560 }}>
          <h3>This project could not be opened</h3>
          <p className="error" style={{ whiteSpace: "pre-wrap" }}>{opened.error}</p>
          <button className="btn" onClick={onClose}>Back</button>
        </div>
      </div>
    );
  }

  const total = projectDuration(project);
  const saveText = { saved: "Saved · Naka-save", saving: "Saving…", unsaved: "Saving soon…", error: "Not saved!" }[save.state];

  return (
    <div
      className="editor"
      data-testid="editor"
      onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()}
      onDrop={(e) => {
        if (!e.dataTransfer.files.length) return;
        e.preventDefault();
        void importFiles([...e.dataTransfer.files].map((f) => api.pathForFile(f)));
      }}
    >
      <header className="ed-top">
        <button className="btn small ghost" onClick={close} aria-label="Back to the AI edit">← Back</button>
        <div className="ed-title">
          <strong title={path}>{project.name || baseName(path)}</strong>
          <span className="muted small">Timeline editor · I-edit nang mano-mano</span>
        </div>
        <span className="spacer" />
        <button className="btn small ghost" onClick={() => run("undo")} disabled={!history.past.length} aria-label="Undo" title="Undo (Ctrl+Z)">↶</button>
        <button className="btn small ghost" onClick={() => run("redo")} disabled={!history.future.length} aria-label="Redo" title="Redo (Ctrl+Shift+Z)">↷</button>
        <span className={`save-state ${save.state}`} role="status" title={save.message} data-testid="save-state">{saveText}</span>
        <button className="btn small ghost" onClick={() => setShowHelp(true)} aria-label="Keyboard shortcuts">?</button>
        <button className="btn small" onClick={() => setView((v) => (v === "storyboard" ? "timeline" : "storyboard"))} data-testid="toggle-storyboard" aria-pressed={view === "storyboard"}>
          {view === "storyboard" ? "Timeline" : "Storyboard"}
        </button>
        <button className="btn small primary" onClick={() => setShowExport(true)} data-testid="export">Export</button>
      </header>

      <LeftPanel
        project={project}
        thumbs={thumbs}
        url={url}
        busy={importing}
        onImport={async () => importFiles(await api.pickMedia())}
        onAdd={(id, where) => addAt(id, where)}
        onAddLibrary={(file, kind) => void addSoundFile(file, kind)}
        folders={folders}
        onChooseFolder={chooseFolder}
        broll={{
          folder: folders.broll,
          stockKeys,
          task: brollTask?.target.kind === "new" ? brollTask : null,
          onAsk: askBroll,
          onCancel: () => brollTask && void api.cancelBroll(brollTask.id),
          onAddFile: (file) => void brollFromFile(file, { kind: "new", at: playhead, duration: 3, position: "full" }, "library"),
          onChooseFolder: () => void chooseBrollFolder(),
        }}
        effects={{
          onFx: (fx) => withNewClip((p) => addFx(p, fx, playhead)),
          onTransition: (fx) => withNewClip((p) => addTransition(p, fx, playhead)),
          onZoom: (kind) => withNewClip((p) => addZoom(p, kind, playhead)),
          tracked: {
            status: trackStatus,
            task: trackTask,
            hasTracking: Boolean(project && Object.keys(project.tracking ?? {}).length),
            untracked: project ? untrackedEffects(project).length : 0,
            onAdd: (effect) => void addTracked(effect),
            onFollow: () => void followHands(),
            onCancel: () => trackTask && void api.cancelTrack(trackTask.id),
            onSetup: () => setShowTrackSetup(true),
          },
          onWipe: () => withNewClip((p) => addWipe(p, playhead)),
          onGraphic: (id) => withNewClip((p) => addGraphic(p, id, playhead)),
          onGrade: (grade, whole) =>
            withNewClip((p) => addGrade(p, grade, whole ? undefined : mainTrack(p)?.clips.find((c) => playhead >= c.start && playhead < clipEnd(c))?.id)),
        }}
      />

      <main className="ed-preview" aria-label="Preview">
        <Player ref={playerRef} project={project} videoPath={null} mediaUrl={url} keepTime compact onTime={setPlayhead} onPlaying={setPlaying} onCaptionClick={(id) => setSelection([id])} onGraphicClick={(id) => setSelection([id])} selection={selection} />
        <div className="ed-transport">
          <button className="btn small" onClick={() => run("play")} aria-label={playing ? "Pause" : "Play"} data-testid="play">{playing ? "❚❚" : "▶"}</button>
          <span className="time" data-testid="time">{mmss(playhead)} / {mmss(total)}</span>
          <button className="btn small ghost" onClick={exactFrame} title="The real frame from the engine, as it will export">Exact frame</button>
        </div>
      </main>

      <aside className="ed-inspector" aria-label="Clip settings">
        <Inspector
          project={project}
          selection={selection}
          onProps={(id, patch: ClipPatch, key) => apply((p) => setClipProps(p, id, patch), key)}
          onSpeed={(id, sp) => apply((p) => setSpeed(p, id, sp), `speed:${id}`)}
          onRamp={(id, ramp) => apply((p) => speedRamp(p, id, ramp as never))}
          onDelete={remove}
          graphics={{
            busy: regenerating,
            onChange: (id, patch, key) => apply((p) => setGraphic(p, id, patch), key),
            onWipe: (id, patch, key) => apply((p) => setWipe(p, id, patch), key),
            onLock: (id, locked) => apply((p) => setClipLocked(p, id, locked)),
            onAnotherLook: (id) => apply((p) => anotherLook(p, id)),
            onRegenerate: (id, useAi) => void regenerateGraphic(id, useAi),
          }}
          tracked={{ ready: Boolean(trackStatus?.available), busy: Boolean(trackTask), onFollow: () => void followHands(), onSetup: () => setShowTrackSetup(true) }}
          broll={{
            task: brollTask?.target.kind === "clip" ? brollTask : null,
            onCancel: () => brollTask && void api.cancelBroll(brollTask.id),
            onFindAnother: (id) => againBroll(id, "another"),
            onRegenerate: (id, quality) => againBroll(id, "ai", quality),
            onReplaceFile: async (id) => {
              const files = await api.pickMedia();
              if (files.length) await brollFromFile(files[0], { kind: "clip", clipId: id }, "file");
            },
            onDescribe: (id, patch, key) => apply((p) => setBrollRequest(p, id, patch), key),
          }}
          captions={{
            busy: retranscribing,
            onWords: (id, words, key) => apply((p) => setCaptionWords(p, id, words), `${key}:${id}`),
            onWordText: (id, i, text) => apply((p) => editWordText(p, id, i, text)),
            onHighlight: (id, i) => apply((p) => toggleHighlight(p, id, i)),
            onEmoji: (id, i, e) => apply((p) => addEmoji(p, id, i, e)),
            onLook: (id, look, all) => apply((p) => setCaptionLook(p, all ? "all" : [id], look), `look:${all ? "all" : id}`),
            onRetranscribe: (id) => void retranscribe(id),
          }}
          empty={
            <ProjectPanel
              project={project}
              onAudio={(patch, key) => apply((p) => setAudioSettings(p, patch), `audio:${key}`)}
              onVocabulary={() => setShowVocab(true)}
              onAddCaption={(text) => withNewClip((p) => addCaption(p, playhead, text))}
              onRecord={() => setShowRecorder(true)}
            />
          }
        />
      </aside>

      {view === "storyboard" ? (
        <section className="ed-timeline ed-storyboard">
          <Storyboard
            project={project}
            actions={{
              busyScene: sceneBusy,
              onSeek: seek,
              onLock: (id, locked) => apply((p) => setSceneLocked(p, id, locked)),
              onText: (id, text) => apply((p) => setSceneText(p, id, text)),
              onRegenerate: (id, useAi) => void regenerateScene(id, useAi),
              onReplace: (scene) => void replaceSceneFootage(scene),
              onApproveAll: approveAll,
              onTimeline: () => setView("timeline"),
            }}
          />
        </section>
      ) : (
      <section className="ed-timeline" aria-label="Timeline">
        <div className="tl-toolbar">
          <button className="btn small" onClick={split} title="Split at the playhead (S)" data-testid="split">✂ Split</button>
          <button className="btn small" onClick={remove} disabled={!selection.length} title="Delete (Del)" data-testid="delete">🗑 Delete</button>
          <span className="spacer" />
          <label className="toggle-inline" title="Snap clips to edges and the playhead (N)">
            <input type="checkbox" checked={snapping} onChange={(e) => setSnapping(e.target.checked)} aria-label="Snapping" /> Snapping
          </label>
          <button className="btn small ghost" onClick={() => run("zoomOut")} aria-label="Zoom out">−</button>
          <input type="range" min={Math.log(MIN_PPS)} max={Math.log(MAX_PPS)} step={0.01} value={Math.log(pps)} onChange={(e) => zoomTo(Math.exp(Number(e.target.value)))} aria-label="Timeline zoom" className="zoom-slider" />
          <button className="btn small ghost" onClick={() => run("zoomIn")} aria-label="Zoom in">+</button>
          <button className="btn small ghost" onClick={() => run("zoomFit")} title="Fit the whole video (Ctrl+0)">Fit</button>
        </div>
        <Timeline
          project={project}
          selection={selection}
          playhead={playhead}
          pps={pps}
          snapping={snapping}
          peaks={peaks}
          thumbs={thumbs}
          url={url}
          onSelect={setSelection}
          onSeek={seek}
          onDraft={setDraft}
          onCommit={(p) => apply(() => p)}
          onError={setToast}
          onZoom={(next) => zoomTo(next)}
          onDropMedia={(id, at, trackId) => addAt(id, trackId ?? "main", at)}
          onTrackFlag={(id, flag, value) => apply((p) => setTrackFlag(p, id, flag, value))}
        />
      </section>
      )}

      {toast && (
        <div className="toast" role="alert" data-testid="toast">
          {toast}
        </div>
      )}
      {showExport && (
        <ExportDialog projectPath={path} defaultOutput={exportPathFor(path)} fps={fps} beforeExport={saveNow} onClose={() => setShowExport(false)} broll={brollCredits(project)} untracked={untrackedEffects(project).length} graphics={project.tracks.filter((t) => t.kind === "graphics").reduce((n, t) => n + t.clips.length, 0)} />
      )}
      {showHelp && <ShortcutsHelp onClose={() => setShowHelp(false)} />}
      {showTrackSetup && trackStatus && <TrackSetup status={trackStatus} onStatus={setTrackStatus} onClose={() => setShowTrackSetup(false)} />}
      {showRecorder && (
        <Recorder
          startAt={mmss(playhead)}
          onClose={() => setShowRecorder(false)}
          onUse={async (data, extension) => {
            const r = await api.saveRecording(path, data, extension);
            if (!r.path) return setToast(r.error ?? "Could not save the recording.");
            await addSoundFile(r.path, "voiceover");
            setShowRecorder(false);
          }}
        />
      )}
      {showVocab && (
        <VocabularyDialog
          onClose={() => setShowVocab(false)}
          onApply={(corrections) => {
            let changed = 0;
            apply((p) => {
              const r = correctCaptions(p, corrections);
              changed = r.changed;
              return r.project;
            });
            setToast(changed ? `Fixed ${changed} caption${changed === 1 ? "" : "s"}.` : "No caption needed fixing.");
          }}
        />
      )}
      {frame && (
        <FrameDialog
          previewNote="This is the true frame from the FFmpeg engine at the playhead: what the export will look like."
          imageUrl={frame.url}
          error={frame.error}
          onClose={() => setFrame(null)}
        />
      )}
    </div>
  );
}

function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-label="Keyboard shortcuts">
        <h2>Keyboard shortcuts</h2>
        <table className="shortcuts">
          <tbody>
            {SHORTCUTS.map(([keys, what, tl]) => (
              <tr key={keys}>
                <td><kbd>{keys}</kbd></td>
                <td>{what}<br /><span className="muted small">{tl}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
