# Video formats · Mga uri ng video

A **format** is a ready-made way to build a short video: Reaction, Listicle, Clone yourself, Green
screen and so on. You pick one (or let the AI pick), add the files it needs, and the AI edit builds
the video. The result is a normal project: every piece (your clips, the other video, the cut-outs,
the numbers, the sounds) is a clip on the timeline that you can change.

*Ang **format** ay handang paraan ng paggawa ng maikling video: Reaction, Listicle, Clone ng sarili,
Green screen, atbp. Pumili ka (o hayaan ang AI), idagdag ang kailangang files, at gagawin ng AI edit
ang video. Lahat ay nasa timeline at puwede mong baguhin.*

## The 13 formats · Ang 13 format

| Format | What you give it | What it does |
|---|---|---|
| **Talking head** | your video | The normal edit: cuts, zooms, captions. |
| **Yap** | your video, optional B-roll | Fast cuts, dense captions (few words per line), your B-roll every few seconds. |
| **Screenshare** | your video + a screen recording | The screen on top, you below. |
| **Split screen** | your video + a second video | Two videos stacked, captions on the divider. |
| **Reaction** | your video + the video you react to | The other video fills the screen, you in a corner window with a moving colour border; emoji pop on your reactions ("grabe", "wow", "naku"). |
| **Voice-over with B-roll** | a voice-over (audio) + B-roll clips/photos | No face: your B-roll is cut to the sentences of your voice-over, with captions. |
| **Listicle** | your video, optional item texts | Numbered cards pop up when you say "una / pangalawa / number 3 / first...", with a pop sound. |
| **Ranking / countdown** | your video, optional item texts | Big animated numbers counting down, with a tick sound. |
| **Before / After** | your video | A wipe from "before" to "after" on the word "after"/"ngayon". |
| **Clone yourself** | your video + 1-2 more takes | You two or three times in one frame (see below). |
| **Green screen** | your video + a background picture/video | The background is replaced (see below). |
| **Comparison A vs B** | your video, optional second video | A "A vs B" card when you compare two things; a split screen if you give a second video. |
| **Educational explainer** | your video, optional screenshots | Callouts on key terms and your screenshots in a frame. |

`python editor.py formats` lists them with the files each needs.

### Clone yourself · Clone ng sarili
- Record 2 or 3 takes **with the camera not moving** (tripod; same zoom, same light). Talk to the
  other "you" in each take.
- The first video is the base. In each extra take you are cut out (a free person-segmentation
  model on your PC) and laid over the base. The edges are cleaned up (small specks removed, a soft
  edge). No generative AI is used; it is plain compositing.
- If the camera moved, the clones will look misplaced. Re-record with the camera still.

*I-record ang 2-3 take nang **hindi gumagalaw ang camera**. Ikaw ay ihihiwalay sa bawat dagdag na take
at ipapatong sa una. Walang generative AI, simpleng compositing lang.*

### Green screen
- With a **real green (or blue) screen**, the colour is keyed out (FFmpeg `chromakey` plus spill
  removal). This is the cleanest result.
- **Without** a green screen, the person model is used to cut you out. Expect softer, less exact
  edges around hair and hands.
- In the editor, select the clip to change the key strength and the soft edge.

### The person model (Clone and Green screen without a green screen)
The cut-out uses MediaPipe's free **selfie segmenter** (under 1 MB). It is never downloaded on its
own: run `python -m pip install mediapipe`, read the model page that
`python editor.py track-models` shows, then `python editor.py track-models --download segment --yes`.
Without it, Clone and Green screen without a green screen stop with a clear message (a real green
screen still works). The masks are cached, so a second export does not redo them.

## How a format is chosen · Paano napipili ang format
1. **You force it:** pick it in the app (AI panel → **Video format**) or `--format NAME`.
2. **From your words:** "reaction", "top 5", "countdown", "clone", "green screen", "vs",
   "before and after", "screenshare"... (English and Taglish keywords).
3. **From your files:** e.g. a screen recording given → Screenshare.
4. **The AI picks** only when you choose **Let the AI pick** (`--format auto`). Its answer must pass
   a schema; it is asked once more if it fails, then Talking head is used.
5. Otherwise: Talking head.

The summary says which format was used and why.

## In the app · Sa app
AI panel → **Video format · Uri ng video**. Choose a format, then **Choose…** for each file it
needs (the button tells you what). Listicle/Ranking have a box for the items (one per line);
formats with a second video have a "starts later by" box if the two recordings are not in sync.
**Edit with AI** stays off until every needed file is there.

In the editor, select your main clip to change a split/corner window (size, corner, moving border,
offset), or a cut-out to change the key. The live preview shows only your video for these; use
**Exact frame** to see the real layout.

## From the command line
```
python editor.py formats
python editor.py ai-edit me.mp4 --format reaction --input source=clip.mp4 --offset source=1.5
python editor.py ai-edit me.mp4 --format listicle --item "Mag-ipon" --item "Mag-invest"
python editor.py ai-edit take1.mp4 --format clone --input takes=take2.mp4 --input takes=take3.mp4
python editor.py ai-edit me.mp4 --format green_screen --input background=beach.jpg
python editor.py ai-edit voice.wav --voiceover --input broll=a.mp4 --input broll=b.jpg
python editor.py ai-edit me.mp4 -i "top 3 tips, countdown" --format auto
```

## Adding your own format · Pagdagdag ng sariling format
A format is one JSON file in `autoedit/formats/`, checked against `format.schema.json`. It lists:
`inputs` (roles and kinds of file), `keywords`, `edit` settings (cut preset, zoom, cuts on/off),
`captions` (style, zone, words per line), `graphics` (Director style), an extra `instruction` for
the AI, and `steps` built from a fixed set of operations: `layout`, `broll_files`, `reactions`,
`items`, `wipe`, `versus`, `callouts`, `cutouts`, `background`, `voiceover_broll`. A new format made
from these needs **no code change**: drop the file in and it appears in the app (after
`npm run engine-data`) and in `python editor.py formats`.

The pop-up graphics formats use (numbered items, rank numbers, A vs B, callouts, screenshot frame)
are ordinary graphics templates (see [graphics.md](graphics.md)); the sounds (pop, ding, whoosh,
tick) are made on your PC with FFmpeg, so there is nothing to download and nothing copyrighted.

## What was and was not tested · Ano ang nasubukan
- **Tested (automatically, Linux):** all 13 specs valid; choosing (forced, words, files, AI with
  retry and fallback); a JSON-only new format; split ratio and offset, corner window and moving
  border measured on rendered frames; Clone with a stand-in segmenter; Green screen keyed on a real
  green frame and with the person path; mask clean-up; Listicle, Ranking, wipe, A vs B, explainer,
  Yap, voice-over; the CLI and the app's format menu.
- **Not tested:** the real MediaPipe segmenter on real footage (how clean the edges are), real
  Taglish speech, Windows, and speed on your PC. These are clean templates, not "Hollywood quality".
