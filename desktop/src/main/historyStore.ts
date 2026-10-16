// Saves every video's version history (shared/history.ts) in one JSON file.
import * as fs from "node:fs";
import * as path from "node:path";
import { addVersion, emptyHistory, redo, undo } from "../shared/history";
import type { Version, VideoHistory } from "../shared/types";

export class HistoryStore {
  private data: Record<string, VideoHistory>;

  constructor(private file: string) {
    try {
      this.data = JSON.parse(fs.readFileSync(file, "utf-8"));
    } catch {
      this.data = {};
    }
  }

  private save(): void {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = `${this.file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(this.data, null, 1), "utf-8");
    fs.renameSync(tmp, this.file);
  }

  get(video: string): VideoHistory {
    return this.data[video] ?? emptyHistory(video);
  }

  private change(video: string, fn: (h: VideoHistory) => VideoHistory): VideoHistory {
    const next = fn(this.get(video));
    this.data[video] = next;
    this.save();
    return next;
  }

  add(video: string, version: Version): VideoHistory {
    return this.change(video, (h) => addVersion(h, version));
  }

  undo(video: string): VideoHistory {
    return this.change(video, undo);
  }

  redo(video: string): VideoHistory {
    return this.change(video, redo);
  }
}
