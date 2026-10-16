import { describe, expect, it } from "vitest";
import { COALESCE_MS, UNDO_LIMIT, createHistory, pushHistory, redoHistory, undoHistory } from "../../src/shared/undo";
import { backupPathFor, exportPathFor, isAbsolutePath, resolveMediaPath } from "../../src/shared/paths";

describe("undo history", () => {
  it("undoes and redoes, and a new change clears redo", () => {
    let h = createHistory("a");
    h = pushHistory(h, "b");
    h = pushHistory(h, "c");
    h = undoHistory(h);
    expect(h.present).toBe("b");
    h = redoHistory(h);
    expect(h.present).toBe("c");
    h = undoHistory(undoHistory(h));
    expect(h.present).toBe("a");
    expect(undoHistory(h)).toBe(h); // nothing more to undo
    h = pushHistory(h, "x");
    expect(h.future).toEqual([]);
  });

  it("merges quick changes with the same key into one step, and keeps at most the limit", () => {
    let h = createHistory(0);
    h = pushHistory(h, 1, "volume", 1000);
    h = pushHistory(h, 2, "volume", 1500);
    h = pushHistory(h, 3, "volume", 1500 + COALESCE_MS + 1);
    expect(h.past).toEqual([0, 2]);
    for (let i = 0; i < UNDO_LIMIT + 50; i++) h = pushHistory(h, 100 + i);
    expect(h.past).toHaveLength(UNDO_LIMIT);
  });
});

describe("paths", () => {
  it("resolves media paths relative to the project, on Windows and elsewhere", () => {
    expect(isAbsolutePath("C:\\Videos\\a.mp4")).toBe(true);
    expect(isAbsolutePath("\\\\server\\share\\a.mp4")).toBe(true);
    expect(isAbsolutePath("clips/a.mp4")).toBe(false);
    expect(resolveMediaPath("C:\\My Videos\\talk.project.json", "clips\\a b.mp4")).toBe("C:\\My Videos\\clips\\a b.mp4");
    expect(resolveMediaPath("/home/u/p.project.json", "a.mp4")).toBe("/home/u/a.mp4");
    expect(resolveMediaPath("/home/u/p.project.json", "D:/x.mp4")).toBe("D:/x.mp4");
  });

  it("names exports and backups next to the project", () => {
    expect(exportPathFor("C:\\V\\talk_edited.project.json")).toBe("C:\\V\\talk_edited_export.mp4");
    expect(exportPathFor("C:\\V\\talk.project.json", 2)).toBe("C:\\V\\talk_export_2.mp4");
    expect(backupPathFor("C:\\V\\talk.project.json")).toBe("C:\\V\\talk.before-editing.project.json");
  });
});
