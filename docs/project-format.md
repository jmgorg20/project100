# Project file format (version 1)

A **Project** (`*.project.json`) is one edit: the media files it uses plus a timeline of
tracks and clips. It is the single source of truth:

- the auto edit (`python editor.py edit`) writes one next to the finished video,
- the desktop app (coming in the next phases) opens, edits and autosaves it,
- the FFmpeg engine renders it: `python editor.py render my.project.json`.

The exact rules are in [`autoedit/project.schema.json`](../autoedit/project.schema.json)
(JSON Schema 2020-12, shared by the Python engine and the app). A full example is in
[`examples/project.json`](../examples/project.json). Check any file with:

```
python editor.py validate my.project.json
```

## Top level

| Key | Meaning |
|---|---|
| `format` | always `"autoedit-project"` |
| `version` | `1`. A newer version is refused with "made by a newer version of the editor". |
| `name` | display name |
| `settings` | `width` 1080, `height` 1920 (version 1 is vertical only; export can scale down), `fps` (24, 25, 30, 50 or 60), `background` colour for empty parts, `audio` loudness settings, `fonts` (family names for the regular/bold/heavy caption fonts) |
| `media` | the files: `id`, `kind` (`video`, `image`, `audio`), `path` (absolute, or relative to the project file), `duration` (seconds, 0 for images), `width`, `height`, `has_audio` |
| `tracks` | the timeline, drawn bottom to top in list order |
| `transcript` | optional: the word timings of a video (`media`, `language`, `words` with source-file times). Used by the AI. |
| `meta` | free-form notes (who made the file, settings used) |

## Tracks and clips

Every clip has an `id` (unique in the project), `start` and `duration` (seconds on the
timeline). Clips that use a file have `media`, and those that play part of a file have
`in`/`out` (seconds in the source file; `out - in` must equal `duration`). Clips on the same
track may not overlap; use another track of the same kind instead.

| Track `kind` | Clip `type` | Clip settings |
|---|---|---|
| `video` (only one: the main track) | `video` | `in`, `out`, `volume` (0-4, 1 = as recorded), `fit` (`fill` crops to fill the frame, `blur` shows the whole picture over a blurred copy), optional `layout` (`{"type": "split" or "pip", "screen": <media id>}` combines it with a screen recording that started at the same moment) |
| | `image` | `fit` |
| `overlay` (photos, B-roll, logo) | `image` or `video` | `x`, `y` (centre, pixels on the 1080x1920 frame), `width`, `height` (the picture is scaled to fit inside), `opacity` (0-1), `animation` (`none`, `pop`); `video` also needs `in`/`out` |
| `effect` | `zoom` | `amount` (1-5), `anchor_y` (0 = zoom towards the top, 0.5 = the middle; default 0.4) |
| | `grade` | `grade`: `natural_clean`, `none`, `warm`, `black_and_white`, `orange_teal`, `high_contrast` |
| `caption` | `caption` | `style` (name or number 1-13), `highlight_keywords` (true/false), `overrides` (size, colours, outline, `zone` `lower`/`center`/`top`/`divider`, `align`, case, words per line...), `words` (each `text`, `start`, `end` in seconds **from the start of the clip**, `highlight`) |
| `audio` (needs a `role`: `original`, `voiceover`, `music`, `sfx`) | `audio` | `in`, `out`, `volume`, `fade_in`, `fade_out` (seconds) |

Tracks can be `muted` (sound off), `hidden` (picture off) and `locked` (an editing hint for
the app; the renderer ignores it).

## Timing rules (what you see is what renders)

- **Picture:** a clip covers frames `round(start × fps)` up to, but not including,
  `round((start + duration) × fps)`. Source `in` points snap to the nearest frame.
  Empty parts of the main track are filled with the background colour.
- **Sound:** audio clips start sample-accurately at `start`.
- **Captions:** each caption clip shows its words (word-by-word highlighting as before) and
  disappears at the clip's end. Subtitle times are in hundredths of a second (as in any
  .ass file): a caption edge can be up to 5 ms away from the exact clip time.
- The video is as long as the last clip on any track.

## How it is rendered

One FFmpeg command, in this order:

1. **Main track.** Clips that play one file forwards with no gap and the same volume and
   framing are decoded together in one pass (like the original editor). Reordered clips,
   other files, stills and gaps become separate pieces joined with `concat`.
2. **Zoom** effect clips, then **colour grade** clips (on overlapping clips, the later
   track wins).
3. **Overlay** tracks, in track order (later tracks on top).
4. **Captions** (on top of everything).
5. **Sound:** the main track's sound plus `original`/`voice-over` tracks form the speech;
   if `settings.audio.normalize` is on, the speech is evened out to `loudness` LUFS; then
   `music` and `sfx` tracks are mixed in at their own volume and a limiter stops clipping.
6. Export size (1080x1920, 720x1280 or 540x960), H.264 + AAC, 48 kHz.

## Command line (also used by the desktop app)

```
python editor.py edit inbox\talk.mp4 --project-only      # make the project, do not render
python editor.py render output\talk_edited.project.json [--height 1280] [--crf 23] [--speed fast]
python editor.py frame output\talk_edited.project.json --time 12.5    # exact frame -> PNG
python editor.py validate output\talk_edited.project.json
```

Add `--json` (before the command) to get progress as JSON lines on stdout, one object per
line, with ordinary messages on stderr:

```
{"type": "stage", "stage": "render", "label": "rendering the video"}
{"type": "progress", "stage": "render", "percent": 42.5}
{"type": "result", "output": "C:\\...\\talk_edited_render.mp4"}
{"type": "error", "message": "..."}        (exit code 1)
{"type": "cancelled"}                      (exit code 130)
```

With `--stdin-control`, writing `cancel` to stdin, or closing stdin, stops FFmpeg and
deletes the unfinished file. A render writes to `<name>.part.mp4` and renames it only when
it finished, so a failed or cancelled render never leaves a broken video behind.
`render` and `frame` refuse to write over one of the project's own media files.

## Known limits and differences (version 1)

- **Vertical 1080x1920 only**, and frame rates 24/25/30/50/60 (the sound is cut in
  one-frame blocks to stay in sync, which needs a whole number of samples per frame).
- **Reordered clips decode their file from the start.** Each piece of the main track that
  goes back in the same file is a separate decode, so a heavily rearranged long video
  renders slower (correct, just slower). Every piece is also an FFmpeg input, so hundreds
  of rearranged pieces would make a very long command.
- **Sound inside overlay video clips is not used** (as before: B-roll clips are silent).
- **Loudness with an intro:** the speech loudness is now evened out over the whole
  timeline, including an intro/outro. Before, the intro was added after. With a silent
  intro image the first second of speech can come out about 2 dB louder than before.
  Without an intro/outro the result is identical to the previous version (checked
  sample by sample).
- **Mono files** (voice-over, music, sound effects) are spread to both speakers at -3 dB,
  FFmpeg's standard; the original editor did the same for sound effects.
- Media paths written by `editor.py edit` are absolute, so moving the media files breaks
  the project (`render` lists the missing files).
