# Polish, the watch folder and quality checks · Polish, watch folder at quality checks

This is for automation (the "Robot City" workers): **the app only polishes videos; your workers
post them.** Nothing here uploads or publishes anything.

*Para ito sa automation: pinapakinis lang ng app ang video; ang mga worker ang nagpo-post.*

## One video · Isang video

```
python editor.py polish inbox\talk.mp4 --preset viral_tiktok --format auto --out outbox --json
```

- `--preset` one of `python editor.py presets` (or your own JSON preset)
- `--format` a format name (`python editor.py formats`), `auto` (the AI picks), or leave it out
  (the preset's format, else from the words)
- `--input role=file` files a format needs (e.g. `broll=clip.mp4`, `source=reacted.mp4`),
  `--item`, `--offset`, `-i "instruction"`, `--provider`, `--model`
- `--no-qc` skip the checks · `--no-retry` no automatic fix · `--max-minutes 30` no retry after this
- **Faceless Automation / Voice-over with B-roll:** the input is the voice-over, and the B-roll is
  given with `--input broll=...`.

It writes, in the output folder:

| File | |
|---|---|
| `talk.mp4` | the polished video |
| `talk.project.json` | the project (open it in the app to change anything) |
| `talk.plan.json` | the AI plan |
| `talk.json` | **the sidecar, written last**: when it is there, the video is complete |

An existing name is never overwritten (`talk_2.mp4`...). With `--json`, progress is printed as
JSON lines and the `result` line is the sidecar (a failed one is followed by an `error` line). The exit code is 0 when the status is `ok` or
`warnings`, 1 when it is `failed`.

### The sidecar · Ang sidecar

```json
{
  "status": "ok | warnings | failed",
  "input": "...", "output": "...talk.mp4", "project": "...talk.project.json",
  "preset": "viral_tiktok", "format": "talking_head", "instruction": "",
  "qc": {"passed": true, "clean": true, "failed": [], "errors": [],
         "checks": [{"id": "clipping", "label": "No clipping (sound too loud)", "ok": true,
                     "severity": "warning", "message": "Peak -1.6 dB", "details": {"peak_db": -1.6}}]},
  "retries": [{"failed": ["clipping"], "actions": ["sound: ..."], "still_failed": []}],
  "opinions": {"note": "The AI's own description of its edit. Not checked: opinions, not measurements.",
               "headline": "...", "details": ["..."]},
  "cost": {...}, "started": "...", "finished": "...", "seconds": 41.2, "error": null
}
```

- `ok`: every check passed. `warnings`: only warnings failed (e.g. a black stretch); the video
  is usable, look at `qc.failed`. `failed`: an error check failed (wrong size, wrong length,
  not a valid MP4, sound out of sync, a missing file): **do not post it**.
- **`qc` is measured; `opinions` is not.** The checks are objective. The AI's description of its
  edit is kept apart and marked as an opinion.

## Quality checks · Mga pagsusuri

| Check | Fails when | Kind |
|---|---|---|
| Size | the MP4 is not the project's width x height (1080x1920) | error |
| Length | it differs from the timeline by more than 2 frames + 0.1 s | error |
| Valid MP4 | ffprobe cannot read it, it is not MP4, it has no H.264 video or no sound, or it does not decode to the end | error |
| Sound in sync | sound and picture start or end more than 0.1 s apart | error |
| No missing files | a file the project uses is gone | error |
| No black frames | 0.5 s or more of black picture | warning |
| No unexpected silence | 1.5 s or more of silence where the captions show words | warning |
| No clipping | the sound peaks above -0.1 dBFS | warning |
| Text inside the safe area | a graphic runs off the screen or into the app buttons' area | warning |
| Nothing on the face | a graphic covers the face (face track, else the usual face area) | warning |
| Caption timing | caption words out of order or outside their caption, a caption shorter than 0.3 s, or past the end | warning |

Run them on any video: `python editor.py qc video.mp4 video.project.json`.

**Automatic fix (once, within the time limit):** clipping → loudness on, a lower limit, music and
sounds 30% quieter; graphics on the face or outside the safe area → those graphics are removed
(locked ones are kept); a damaged or wrong-size/length file → rendered again. Then the checks run
again and the sidecar lists what was done in `retries`. Black frames and silences are reported,
not "fixed" (they may be on purpose).

## The watch folder · Ang watch folder

```
python editor.py polish-watch --preset viral_tiktok --format auto
```

Folders (config.yaml, `polish:`; or `--inbox --outbox --failed --done`):

| Folder | |
|---|---|
| `robot/inbox/` | the workers drop videos (and audio, for faceless) here |
| `robot/outbox/` | `<name>.mp4`, `<name>.project.json`, `<name>.plan.json`, then `<name>.json` |
| `robot/failed/` | the original, `<name>.json` (why), `<name>.log` (what happened), and a rejected render `<name>.rejected.mp4` if the checks failed |
| `robot/done/` | the originals of polished videos |

- **Half-copied files are safe:** a file is taken only after its size and time stopped changing for
  `settle_seconds` (10), never with a temporary name (`.part`, `.tmp`, `.crdownload`,
  `.download`, `.filepart`...) or a hidden one, and only if it can be moved (Windows refuses while
  another program is still writing it). Tip for workers: copy as `name.mp4.part`, then rename.
- **Restarts are safe:** a taken file sits in `inbox/.processing/`. After a restart, a video
  already finished (its sidecar is in the outbox) is kept; an unfinished one is polished again,
  at most 3 times, then it goes to `failed/` with the reason.
- **One job at a time:** each video holds a lock file in the work folder, shared by every editor
  process on the PC (two watchers, or a watcher and a `polish` command, take turns). AI clips made
  with WanGP keep their own GPU lock. Only one watcher can use an inbox.
- **Per-video settings:** next to `talk.mp4`, a `talk.job.json` (all optional):
  ```json
  {"preset": "faceless_automation", "format": "voiceover_broll", "instruction": "Tara na!",
   "inputs": {"broll": ["clips/a.mp4", "D:/broll/b.jpg"], "items": ["Una", "Pangalawa"]}}
  ```
  Relative paths are relative to the inbox.
- `--once` looks once and stops (for Task Scheduler). A file needs two looks (it must be seen
  unchanged), so schedule it every minute or so.
- **Presets are plain JSON** (`autoedit/presets/`, yours in `presets/`), see
  [storyboard-presets.md](storyboard-presets.md).

## What was and was not tested · Ano ang nasubukan
- **Tested (automatically, Linux):** every check passing on a good video and failing on a video
  made with exactly that problem (small, short, not a video, MKV, no sound, sound 0.6 s late,
  1 s of black, silence while captions show words, clipping, a missing file, bad caption
  timing, a graphic on the face, one off the screen); the automatic fix for clipping and for a
  damaged render; no retry and no time left; polish with the real AI edit (stand-in AI) and the
  real checks; the watch folder: half-copied and temporary files wait, success, an error, a bug,
  failed checks, `job.json`, restart recovery and the 3-attempt limit, two watchers never
  polishing at the same time; the CLI.
- **Not tested:** Windows (file locking while copying, Task Scheduler), real worker programs,
  real Taglish speech, long videos and speed on your PC.
