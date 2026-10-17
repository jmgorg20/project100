# Effects that follow you (tracked effects) · Mga epekto na sumusunod sa iyo

A glow at your fingertips when you say "power", sparks on your palm, an aura around you: the
effect **follows your hand, face or body** and fades out by itself when it cannot see you.
Everything runs on your PC, for free. *Libre at lokal ito: walang internet, walang account.*

## What you need (one time) · Kailangan (isang beses lang)

Tracking uses Google's free **MediaPipe** tracker. Two things, once:

1. **The MediaPipe package.** Open PowerShell and run:
   ```
   python -m pip install mediapipe
   ```
2. **The model files** (about 14 MB). In the app: **Effects tab → Follow my hands → Set up… →
   Download the models…**. It shows where they come from and asks you to confirm. Or on the
   command line:
   ```
   python editor.py track-models                       (lists them, downloads nothing)
   python editor.py track-models --download hand face --yes
   ```
   They go in the editor's `models\tracking` folder. The models are Google's MediaPipe models
   and have their own terms: read the model pages (linked in the dialog and printed by
   `track-models`). **This app never downloads a model by itself**, and does not include any.
   *Optional:* `pose` is a better "body" for the aura (without it the body is estimated from
   the face).

`python editor.py track-status` tells you what is still missing. Settings (all optional) are in
`config.yaml`, section `tracking:`.

## Using it · Paano gamitin

**With the AI edit.** Ask in your instruction, for example:
- *"Pag sinabi kong 'power', lagyan ng glow ang dulo ng hintuturo ko."*
- *"Aura sa paligid ko sa intro."*
- *"Sparks sa palad ko habang sinasabi ko ang 'magic'."*

The AI plans each effect with what to follow (palm, fingertips, face, body), which hand, when
(the moment you say the word), colour, strength and size. The engine then finds your hands and
face **only in the moments needed**, saves the points in the project, and places the effects on
the timeline. With Auto mode off, each one is listed for review. If tracking is not set up, the
edit still finishes and says so.

**In the editor.** Effects tab → **Follow my hands**:
1. Add **Glow**, **Sparks**, **Aura**, **Energy rings** (a pulsing core with rings) or **Your
   own clip**, at the playhead.
2. Click **Follow my hands · Sundan** once for the video (progress and Cancel; one undo step).
   Added effects have nothing to follow until you do.
3. Click the effect on the timeline to change:

| Setting | What it does |
|---|---|
| **Effect** | glow, sparks, aura, energy rings, your own clip |
| **Follows** | palm, wrist, thumb / index / middle / ring / little fingertip, **all five fingertips**, face, body |
| **Which hand** | left, right, or *whichever is found* (the hand that is found most in that moment) |
| **Strength, Size** | how bright and how big |
| **Steadiness** | 0 = follow every little movement, 1 = very smooth |
| **Colour** | any colour, or "Own colour" |
| **Fade in / out** | how the effect appears and goes away |
| start and end | drag the clip's edges on the timeline, or move it |

The panel also says **how well the point was found** in that moment ("Found in 93%"). If it was
found in under a quarter of it, you get a plain warning.

**Your own clip.** A video or picture with a **black background** (blended with "screen": black
changes nothing, light adds, like a glow or fire clip), or one with its own **transparency**
(a `.mov` with alpha, a PNG picture). It is placed on the point and scaled with **Size**. It plays
from its start and ends when it ends. Use only clips you have the right to use.

## How it works (and what it does not do) · Paano ito gumagana

- **Finding the points.** MediaPipe looks at the video (on the CPU) about 30 times per second and
  gives the places of the wrist, palm and fingertips of each hand, and the face. The points are
  saved **in the project file** (`tracking`), so the edit does not depend on MediaPipe after that.
  Where a point is saved as "not found" (confidence 0), the effect knows.
- **Following smoothly.** Short holes (up to a quarter of a second) are bridged. The path is
  smoothed with a *One Euro* filter (steady when still, quick when you move).
- **When it is lost, it fades out instead of jumping.** The effect stays where the point was and
  fades out over 0.4 s. When the point is found again it fades back in; if that happens while it
  is still fading, it glides to the new place instead of jumping.
- **Cuts, speed, reframe, zoom.** The point is read at the *source* time of each frame, so cuts
  and sped-up clips follow correctly; the position goes through the main clip's crop / reframe and
  through zoom effects.
- **Drawing.** Glow, sparks, aura and energy rings are drawn by the editor with plain maths
  (deterministic: the same project gives the same pixels), at half size, then added to the picture
  with the **screen** blend (it only adds light, never darkens).
- **The preview** in the editor is a lighter, browser-drawn version: the *place* and the
  fading follow the same rules as the export, the *look* is similar (use **Exact frame**).
- Hands and the face are *located*, not recognised: nothing here identifies a person, and there
  is no face swap, deepfake or lip-sync.
- Not supported: a split-screen / picture-in-picture layout (those clips have no effect), and
  stills or gaps on the main track.

## Troubleshooting · Mga problema

| Problem | What to do |
|---|---|
| "Tracking needs the free MediaPipe package" | `python -m pip install mediapipe`, then restart the app |
| "MediaPipe could not start" on Linux | `sudo apt install libegl1 libgles2` (Windows: install the *Microsoft Visual C++ Redistributable*) |
| The effect is on the wrong hand | MediaPipe's left/right follows its own convention. Choose the other hand, "whichever is found", or set `swap_hands: true` in `config.yaml` |
| "Found in only 10%" | Better light, the hand fully in view, not too fast; closed fists and fingers hiding each other are hard |
| It trembles | Raise **Steadiness** |
| It lags behind a fast hand | Lower **Steadiness** |
| Nothing shows in the export | The video was not followed (the Export window says so): click **Follow my hands** |

## Command line

```
python editor.py track output\myvideo_ai.project.json          (the moments its effects need)
python editor.py track myvideo.mp4 --output points.json --ranges 2-5.5,9-12
python editor.py track-status
python editor.py track-models [--download hand face pose --yes]
```

Saved tracks are reused (`work\cache\tracks`), so running the same video again does not track it
again.

## What was and was not verified

**Verified (automatically, on Linux):**
- Following a point (gaps, smoothing, fading out, gliding back, cuts), with synthetic tracks. The
  TypeScript copy used by the preview gives the same numbers as the engine (to 1e-9).
- Reading MediaPipe's results and running the detector over a video, with a **stand-in MediaPipe**
  (the exact calls, time ranges, cancel, clear errors) and with a fake package in a separate
  process (the app's main process runs the real engine).
- Drawing, **measured on the rendered pixels**: the glow, sparks, aura (a ring), energy rings and
  your own clip (black background and alpha) land on a marker in the picture through fill, 2
  reframes, a wide video (fill and blurred), punch-in and smooth zoom, a cut and a 2x clip; they
  only add light; colour, strength, size and fades; fading out when the point is lost; the same
  picture in the export as in the exact frame.
- The preview's glow lands within about 10 px of the engine's frames, and fades the same way.
- Project files: the format is checked (and old projects still load), random edits including
  tracked effects always give projects the engine accepts.
- **The real MediaPipe** (version 1.1.1, the official models, CPU) ran once through the app's
  code on **one real photograph** (Google's public MediaPipe sample picture of two hands and a
  face, turned into a 3-second video): both hands, the face and the body were found, and the
  effects were drawn on the right fingertips and around the face. That is a *plumbing* check
  (about 7 s for 3 s of video, CPU only), not a quality test.

**NOT verified:**
- **Real footage.** How well MediaPipe follows hands in real talking videos (motion blur, fast
  hands, hands near the face, dark rooms, long videos), whether "left" and "right" come out the
  right way round for your camera, and how the effects *look* on your footage and platform.
  The one photo above is not a talking video.
- Windows, a GPU, and speed on your PC. (Here: about 15 ms per frame to draw an effect; about
  7 s to track 3 s of video.)
- The preview's *look* matches the export only roughly (it is an approximation by design).
