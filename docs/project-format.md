# Project file format (version 2)

A **Project** (`*.project.json`) is one edit: the media files it uses plus a timeline of
tracks and clips. It is the single source of truth:

- the auto edit (`python editor.py edit`) writes one next to the finished video,
- the desktop app's timeline editor opens, edits and autosaves it,
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
| `version` | `2` (version `1` files still load unchanged). A newer version is refused with "made by a newer version of the editor". |
| `name` | display name |
| `settings` | `width` 1080, `height` 1920 (vertical only; export can scale down), `fps` (24, 25, 30, 50 or 60), `background` colour for empty parts, `audio` (`normalize`, `loudness`, `true_peak`; `ducking` 0-1: lower the music while someone speaks; `denoise` 0-1: reduce steady noise in the speech), `fonts` (family names for the regular/bold/heavy caption fonts) |
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
| `video` (only one: the main track) | `video` | `in`, `out`, `volume` (0-4, 1 = as recorded), `fit` (`fill` crops to fill the frame, `blur` shows the whole picture over a blurred copy), optional `layout` (`{"type": "split" or "pip", "screen": <media id>}` combines it with a screen recording that started at the same moment). Version 2: `speed` (0.25-4), `fade_in`/`fade_out` (its sound, seconds), `crop` (see below) |
| | `image` | `fit`; version 2: `crop` |
| `overlay` (photos, B-roll, logo) | `image` or `video` | `x`, `y` (centre, pixels on the 1080x1920 frame), `width`, `height` (the picture is scaled to fit inside), `opacity` (0-1), `animation` (`none`, `pop`); `video` also needs `in`/`out`, and may have `speed` |
| `effect` | `zoom` | `amount` (1-5), `anchor_y` (0 = zoom towards the top, 0.5 = the middle; default 0.4); `ease` (seconds to grow from 100%; 0 or missing = punch-in) |
| | `grade` | `grade`: `natural_clean`, `none`, `warm`, `black_and_white`, `orange_teal`, `high_contrast`; `intensity` (0-1, default 1: blended with the original) |
| | `fx` | `effect`: `shake`, `flash` (to white), `dip` (to black), `glitch` (colour split + noise), `whip` (sideways motion blur); `intensity` (0-1, default 0.6). Flash and dip peak in the middle of the clip. Used for transitions too (a short `fx` clip centred on a cut). |
| | `trackfx` | An effect that follows a tracked point: `effect` (`glow`, `spark`, `aura`, `energy`, `clip`), `point` (`palm`, `wrist`, `thumb_tip`, `index_tip`, `middle_tip`, `ring_tip`, `pinky_tip`, `fingertips`, `face`, `body`), `hand` (`left`, `right`, `any`), `intensity`, `color` (`#rrggbb`), `size` (0.1-4), `smooth` (0-1), `fade_in`, `fade_out`; `effect: "clip"` needs `media` (your clip) and may set `blend` (`screen` for a black background, or `alpha`). See [tracking.md](tracking.md). |
| | `wipe` | A before/after wipe: `grade` (as above) on the side the divider has passed, `intensity`, `direction` (`right`, `left`, `down`, `up`), `sweep` (seconds, 0.2-3), `stop` (where the divider stays, 0.05-0.95 of the frame), `divider` (false = no white line) |
| `graphics` (pop-up words, cards...) | `graphic` | `template` (an id from `autoedit/graphics_catalog.json`), `x`, `y` (the centre, **fractions** of the frame: 0.5, 0.5 = the middle), `params` (`text` with `*word*` emphasis, `text2`, `items`, `number`, `prefix`, `suffix`, `image` (a media id), `emoji`, `icon`, `font`, `color`, `accent`, `bg`, `size` 0.4-2.5, `intensity` 0-1, `align`, `case`, `angle`), optional `attach` (`{"kind": "flash" / "whip" / "punch", "intensity"}`: a transition on the picture at its first frame), `locked` (true: not changed by the app or the AI), `director` (notes: style, mood, the spoken words). See [graphics.md](graphics.md). |
| `caption` | `caption` | `style` (name or number 1-13), `highlight_keywords` (true/false), `overrides` (size, colours, outline, `zone` `lower`/`center`/`top`/`divider`, `align`, case, words per line...), `words` (each `text`, `start`, `end` in seconds **from the start of the clip**, `highlight`) |
| `audio` (needs a `role`: `original`, `voiceover`, `music`, `sfx`) | `audio` | `in`, `out`, `volume`, `fade_in`, `fade_out` (seconds); version 2: `speed` |

**Tracking (optional, top level `tracking`).** Where the speaker's hands, face and body are in
a video, saved so tracked effects can follow them without any tracker running:

```json
"tracking": {"m1": {"fps": 30, "start": 0.0, "source": "mediapipe 1.1.1",
  "points": {"right_index_tip": {"x": [0.41, 0.42], "y": [0.52, 0.52], "c": [0.93, 0.95]},
             "face": {"x": [0.5], "y": [0.3], "c": [0.9], "s": [0.28]}}}}
```

The key is a media id (a video). Sample `i` is at `start + i / fps` seconds of that video; `x`, `y`
are 0-1 across the frame (y down), `c` is the confidence (0 = not found), `s` an optional size
(share of the frame width). Names: `left_` / `right_` + `wrist`, `palm`, `thumb_tip`, `index_tip`,
`middle_tip`, `ring_tip`, `pinky_tip`, and `face`, `body`.

**Speed (version 2).** A clip with `speed` plays `out - in` seconds of its file in
`(out - in) / speed` seconds, so `out - in = duration × speed`. The sound keeps its pitch
(FFmpeg `atempo`). Allowed: 0.25 to 4.

**Crop / reframe (version 2)**, for `fill` on the main track: `{"zoom": 1-4, "x": 0-1,
"y": 0-1}`. The picture is scaled to cover 1080·zoom × 1920·zoom, then the 1080×1920 window
is taken at `x`, `y` of the spare room (0 = left/top, 0.5 = centre, 1 = right/bottom).
Without `crop` (or `{"zoom": 1, "x": 0.5, "y": 0.5}`) it is the usual centred fill. `blur`
and split/picture-in-picture layouts ignore `crop`.

**B-roll source (optional, any overlay clip).** `broll` says where the picture came from, so
the editor can show the credit and licence, label AI-made content, and find another or
regenerate it. The renderer ignores it.

```json
"broll": {"source": "pexels", "kind": "video", "prompt": "a jeepney on a busy street",
          "search": "jeepney street", "style": "realistic", "position": "full",
          "ai_generated": false, "stock_id": "pexels-123", "author": "Ana",
          "page": "https://www.pexels.com/video/123/", "license": "Pexels License",
          "license_url": "https://www.pexels.com/license/",
          "credit": "Video by Ana on Pexels (https://www.pexels.com/video/123/)"}
```

`source` is required: `library` (your B-roll folder), `pexels`, `pixabay`, `ai` (made with
WanGP; then `ai_generated` is true and `tier` says which), or `file` (chosen by hand).
`style`: `realistic`, `cartoon`, `drawing`, `low_poly`, `stylized_3d`, `anime`. See
[broll.md](broll.md).

Tracks can be `muted` (sound off), `hidden` (picture off) and `locked` (an editing hint for
the app; the renderer ignores it). Any clip can also be `locked` (the storyboard's **Lock scene**
sets it): the app and the AI leave it as it is.

`meta.storyboard` (optional): `starts`, the scene start times the storyboard keeps once you edit a
scene, and `approved` (true after **Approve all**). `meta.preset` and `meta.format` name the preset
and format an AI edit used. See [storyboard-presets.md](storyboard-presets.md).

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
   track wins), then **fx** clips (shake, flash, dip, glitch, whip) in track order.
3. **Overlay** tracks, in track order (later tracks on top).
4. **Captions** (on top of everything).
5. **Sound:**
   - The main track's sound plus the `original`/`voice-over` tracks form the speech.
   - With `denoise`, FFmpeg's `afftdn` lowers steady noise. Its noise floor is measured in
     the pauses of the speech files.
   - If `settings.audio.normalize` is on, the speech is evened out to `loudness` LUFS.
   - The `music` tracks are mixed and, with `ducking`, compressed whenever the speech is
     louder than a whisper (`sidechaincompress`, keyed by the speech).
   - Then the music and `sfx` are mixed in at their own volume, and a limiter stops clipping.
6. Export size (1080x1920, 720x1280 or 540x960), H.264 + AAC, 48 kHz.

## Command line (also used by the desktop app)

```
python editor.py edit inbox\talk.mp4 --project-only      # make the project, do not render
python editor.py render output\talk_edited.project.json [--height 1280] [--crf 23] [--speed fast]
python editor.py frame output\talk_edited.project.json --time 12.5    # exact frame -> PNG
python editor.py validate output\talk_edited.project.json
python editor.py broll output\talk_edited.project.json --clip o3   # B-roll: find another (broll.md)
python editor.py track output\talk_edited.project.json              # follow hands/face for tracked effects (tracking.md)
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
