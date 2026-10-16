import { describe, expect, it } from "vitest";
import {
  EditError, addMedia, deleteClips, findClip, insertMedia, mainBoundary, moveClip, moveMainClip, setClipProps, setSpeed, setTrackFlag,
  snap, snapMove, snapPoints, splitAt, splitClip, trimClip,
} from "../../src/shared/edit";
import type { Clip, Project } from "../../src/shared/types";

/** Like an AI edit: two main clips, captions, a zoom, a photo and music under everything. */
export function sample(): Project {
  return {
    format: "autoedit-project",
    version: 1,
    name: "t",
    settings: { width: 1080, height: 1920, fps: 30, background: "#000000" },
    media: [
      { id: "m1", kind: "video", path: "C:/Videos/talk.mp4", duration: 10, width: 720, height: 1280, has_audio: true },
      { id: "m2", kind: "image", path: "C:/Videos/photo.png", duration: 0, width: 600, height: 400 },
      { id: "m3", kind: "audio", path: "C:/Music/song.mp3", duration: 30 },
    ],
    tracks: [
      { id: "main", kind: "video", name: "Video", clips: [
        { id: "v1", type: "video", media: "m1", start: 0, duration: 2, in: 1, out: 3 },
        { id: "v2", type: "video", media: "m1", start: 2, duration: 1.5, in: 4, out: 5.5 },
      ] },
      { id: "photos", kind: "overlay", name: "Photos", clips: [
        { id: "o1", type: "image", media: "m2", start: 2.5, duration: 1, x: 540, y: 960, width: 600, height: 400 },
      ] },
      { id: "effects", kind: "effect", name: "Effects", clips: [{ id: "z1", type: "zoom", start: 1, duration: 1, amount: 1.2 }] },
      { id: "captions", kind: "caption", name: "Captions", clips: [
        { id: "t1", type: "caption", start: 0, duration: 1.2, style: "yellow_pop", words: [
          { text: "Kumusta", start: 0, end: 0.5 }, { text: "kayo", start: 0.6, end: 1.0 },
        ] },
        { id: "t2", type: "caption", start: 2.2, duration: 1.0, style: "yellow_pop", words: [{ text: "GitHub", start: 0.1, end: 0.6 }] },
      ] },
      { id: "music", kind: "audio", role: "music", name: "Music", clips: [
        { id: "a1", type: "audio", media: "m3", start: 0, duration: 3.5, in: 0, out: 3.5, volume: 0.3 },
      ] },
    ],
  };
}

const clip = (p: Project, id: string): Clip => findClip(p, id)!.clip;
const ids = (p: Project, track: string) => p.tracks.find((t) => t.id === track)!.clips.map((c) => c.id);

describe("split", () => {
  it("splits a main clip into two that play the same source", () => {
    const { project: p, rightId } = splitClip(sample(), "v1", 1.0);
    expect(clip(p, "v1")).toMatchObject({ start: 0, duration: 1, in: 1, out: 2 });
    expect(clip(p, rightId)).toMatchObject({ start: 1, duration: 1, in: 2, out: 3 });
    expect(p.version).toBe(2);
    expect(sample().tracks[0].clips).toHaveLength(2); // the input is never changed
  });

  it("splits caption words by time and refuses a split at the very edge", () => {
    const { project: p, rightId } = splitClip(sample(), "t1", 0.55);
    expect(clip(p, "t1").words!.map((w) => w.text)).toEqual(["Kumusta"]);
    expect(clip(p, rightId).words).toEqual([{ text: "kayo", start: 0.05, end: 0.45 }]);
    expect(() => splitClip(sample(), "v1", 0.01)).toThrow(EditError);
  });

  it("splits everything under the playhead, except locked tracks", () => {
    const p = splitAt(setTrackFlag(sample(), "music", "locked", true), 1.5);
    expect(ids(p, "main")).toHaveLength(3);
    expect(ids(p, "effects")).toHaveLength(2);
    expect(ids(p, "music")).toEqual(["a1"]);
  });
});

describe("delete", () => {
  it("ripples the main track and takes linked clips with it", () => {
    const p = deleteClips(sample(), ["v1"]);
    expect(clip(p, "v2").start).toBe(0);
    expect(findClip(p, "t1")).toBeNull(); // its caption was inside the deleted part
    expect(findClip(p, "z1")).toBeNull();
    expect(clip(p, "t2").start).toBeCloseTo(0.2);
    expect(clip(p, "o1").start).toBeCloseTo(0.5);
    // The music under everything loses the same 2 seconds, so it stays in sync.
    expect(clip(p, "a1")).toMatchObject({ start: 0, duration: 1.5, in: 2, out: 3.5 });
  });

  it("deletes other clips without moving anything", () => {
    const p = deleteClips(sample(), ["t1", "o1"]);
    expect(findClip(p, "t1")).toBeNull();
    expect(clip(p, "v2").start).toBe(2);
    expect(clip(p, "t2").start).toBe(2.2);
  });

  it("cuts a long clip in two when the deleted part is in its middle", () => {
    const p = deleteClips(sample(), ["v2"]);
    expect(clip(p, "a1")).toMatchObject({ start: 0, duration: 2, in: 0, out: 2 });
    const music = p.tracks.find((t) => t.id === "music")!.clips;
    expect(music).toHaveLength(1); // the music ended with v2, so only the first part is left
  });
});

describe("trim", () => {
  it("ripples a main clip's end and cuts linked clips", () => {
    const p = trimClip(sample(), "v1", "end", 1.5);
    expect(clip(p, "v1")).toMatchObject({ duration: 1.5, out: 2.5 });
    expect(clip(p, "v2").start).toBe(1.5);
    expect(clip(p, "z1")).toMatchObject({ start: 1, duration: 0.5 });
    expect(clip(p, "t2").start).toBeCloseTo(1.7);
  });

  it("trims a main clip's start: the clip stays put and plays later source", () => {
    const p = trimClip(sample(), "v1", "start", 0.5);
    expect(clip(p, "v1")).toMatchObject({ start: 0, duration: 1.5, in: 1.5, out: 3 });
    expect(clip(p, "v2").start).toBe(1.5);
    // The first caption lost its first half second: "Kumusta" (0-0.5) is gone.
    expect(clip(p, "t1").words!.map((w) => w.text)).toEqual(["kayo"]);
  });

  it("cannot extend past the start or end of the source file", () => {
    const p = trimClip(sample(), "v1", "start", -5); // only 1 s of source before 'in'
    expect(clip(p, "v1")).toMatchObject({ start: 0, duration: 3, in: 0, out: 3 });
    const q = trimClip(sample(), "v2", "end", 100); // source ends at 10 s
    expect(clip(q, "v2")).toMatchObject({ duration: 6, out: 10 });
  });

  it("keeps other clips between their neighbours, and images can stretch freely", () => {
    const p = trimClip(sample(), "t1", "end", 5);
    expect(clipEnd(clip(p, "t1"))).toBeCloseTo(2.2); // stops at the next caption
    const q = trimClip(sample(), "o1", "end", 9);
    expect(clip(q, "o1").duration).toBeCloseTo(6.5);
  });
});

const clipEnd = (c: Clip) => c.start + c.duration;

describe("move", () => {
  it("moves a clip and puts it on a new track when it would overlap", () => {
    const { project: p, trackId } = moveClip(sample(), "t1", 2.4);
    expect(trackId).not.toBe("captions");
    expect(p.tracks.find((t) => t.id === trackId)).toMatchObject({ kind: "caption" });
    const free = moveClip(sample(), "t1", 4);
    expect(free.trackId).toBe("captions");
    expect(clip(free.project, "t1").start).toBe(4);
  });

  it("refuses to move onto another kind of track or the main track", () => {
    expect(() => moveClip(sample(), "t1", 0, "music")).toThrow(EditError);
    expect(() => moveClip(sample(), "v1", 1)).toThrow(EditError);
  });

  it("reorders the main video and carries the linked clips along", () => {
    const p = moveMainClip(sample(), "v2", 0);
    expect(clip(p, "v2").start).toBe(0);
    expect(clip(p, "v1").start).toBe(1.5);
    expect(clip(p, "t2").start).toBeCloseTo(0.2); // was 0.2 s into v2
    expect(clip(p, "t1").start).toBeCloseTo(1.5); // was at the start of v1
    expect(clip(p, "o1").start).toBeCloseTo(0.5);
    expect(clip(p, "a1").start).toBe(0); // the music spans both: stays
  });
});

describe("speed", () => {
  it("makes a main clip shorter and squeezes its captions", () => {
    const p = setSpeed(sample(), "v1", 2);
    expect(clip(p, "v1")).toMatchObject({ duration: 1, in: 1, out: 3, speed: 2 });
    expect(clip(p, "v2").start).toBe(1);
    expect(clip(p, "t1")).toMatchObject({ start: 0, duration: 0.6 });
    expect(clip(p, "t1").words![1]).toMatchObject({ start: 0.3, end: 0.5 });
    expect(clip(p, "t2").start).toBeCloseTo(1.2);
    const back = setSpeed(p, "v1", 1);
    expect(clip(back, "v1").speed).toBeUndefined();
  });

  it("refuses a speed that does not fit before the next clip", () => {
    const p = moveClip(sample(), "a1", 0).project;
    const q = insertMedia(p, "m3", 4, "music").project;
    expect(() => setSpeed(q, "a1", 0.5)).toThrow(/Not enough room/);
    expect(() => setSpeed(sample(), "t1", 2)).toThrow(EditError);
  });
});

describe("settings", () => {
  it("clamps values and refuses settings a clip does not have", () => {
    let p = setClipProps(sample(), "v1", { volume: 9, fade_in: 5, crop: { zoom: 9, x: -1, y: 0.5 } });
    expect(clip(p, "v1")).toMatchObject({ volume: 4, fade_in: 2, crop: { zoom: 4, x: 0, y: 0.5 } });
    p = setClipProps(p, "v1", { crop: { zoom: 1, x: 0.5, y: 0.5 }, fade_in: 0 });
    expect(clip(p, "v1").crop).toBeUndefined();
    expect(clip(p, "v1").fade_in).toBeUndefined();
    expect(() => setClipProps(sample(), "o1", { fade_in: 1 })).toThrow(/no fade_in/);
    expect(() => setClipProps(setTrackFlag(sample(), "main", "locked", true), "v1", { volume: 1 })).toThrow(/locked/);
  });
});

describe("adding media", () => {
  it("reuses a file that is already in the project", () => {
    const { project: p, ids: got } = addMedia(sample(), [
      { id: "x", kind: "video", path: "c:\\videos\\TALK.mp4", duration: 10 },
      { id: "x", kind: "audio", path: "C:/Music/new.mp3", duration: 5 },
    ]);
    expect(got).toEqual(["m1", "m4"]);
    expect(p.media).toHaveLength(4);
  });

  it("inserts a video on the main track at the nearest boundary and moves the rest", () => {
    expect(mainBoundary(sample(), 1.9)).toBe(2);
    const { project: p, clipId } = insertMedia(sample(), "m1", 1.9);
    expect(clip(p, clipId)).toMatchObject({ start: 2, duration: 10, in: 0, out: 10 });
    expect(clip(p, "v2").start).toBe(12);
    expect(clip(p, "t2").start).toBeCloseTo(12.2);
  });

  it("puts sounds and pictures on their tracks without overlapping", () => {
    const { project: p, clipId } = insertMedia(sample(), "m3", 1);
    const where = findClip(p, clipId)!.track;
    expect(where).toMatchObject({ kind: "audio", role: "music" });
    expect(where.id).not.toBe("music"); // the music track is busy at 1 s
    const pic = insertMedia(sample(), "m2", 5, "photos");
    expect(clip(pic.project, pic.clipId)).toMatchObject({ type: "image", start: 5, duration: 3, width: 1080, height: 1920 });
    expect(() => insertMedia(sample(), "m2", 0, "music")).toThrow(EditError);
  });
});

describe("snapping", () => {
  it("snaps to the nearest edge or the playhead within the threshold", () => {
    const points = snapPoints(sample(), 1.73, ["t1"]);
    expect(points).toContain(1.73);
    expect(points).not.toContain(1.2); // t1's own end is skipped
    expect(snap(1.95, points, 0.1)).toEqual({ t: 2, snapped: 2 });
    expect(snap(5.5, points, 0.1).snapped).toBeNull();
    expect(snapMove(0.93, 1.04, points, 0.1)).toEqual({ start: 0.96, snapped: 2 }); // its end is nearer to 2
  });
});
