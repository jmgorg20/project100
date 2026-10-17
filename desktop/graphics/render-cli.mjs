// Command line: node render-cli.mjs jobs.json
// jobs.json = { "ffmpeg": "path", "jobs": [ ...see capture.mjs ] }. Prints one JSON line per event:
//   {"type":"progress","done":10,"total":90}  {"type":"job","key":"..."}  {"type":"done"}
// Used by autoedit/graphics.py when it has to draw graphics itself (no app running).
import { readFileSync } from "node:fs";
import { renderJobs } from "./capture.mjs";

const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));
const ctl = new AbortController();
process.on("SIGTERM", () => ctl.abort());
process.on("SIGINT", () => ctl.abort());
const say = (o) => process.stdout.write(JSON.stringify(o) + "\n");
try {
  await renderJobs(spec.jobs, {
    ffmpeg: spec.ffmpeg || undefined,
    signal: ctl.signal,
    onProgress: (e) => (e.finished ? say({ type: "job", key: e.job.key }) : say({ type: "progress", done: e.done, total: e.total })),
  });
  say({ type: "done" });
} catch (e) {
  say({ type: "error", message: String(e && e.message || e) });
  process.exit(ctl.signal.aborted ? 130 : 1);
}
