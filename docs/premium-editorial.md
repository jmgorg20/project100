# PREMIUM EDITORIAL VIRAL · Pang-magasin na edit

A premium magazine look for talking videos (vertical 9:16), planned **scene by scene**. It uses
fast but smooth jump cuts, punch-in zooms, cream caption cards and serif headlines. Keywords are
highlighted, and your own screenshots float over a dimmed, vignetted background. It also adds UI
panels, checklists, a countdown, search-bar typing, storyboard pages, mosaic grids, colour-palette
cards, picture-in-picture and black-and-white transitions. Something new appears every 2–4
seconds, timed to your words.

*Premium na itsura ng magasin, eksena por eksena. Bagong idea kada 2–4 segundo, sabay sa
sinasabi mo. Sarili mong files lang ang gamit.*

## Quick start · Mabilis na simula

- **App:**
  1. In the AI panel, pick **Preset → PREMIUM EDITORIAL VIRAL · …**.
  2. Add your video. Under **Photos**, add your screenshots, photos and logo.
  3. Press **Edit with AI**.
- **Command line:**

  ```
  python editor.py ai-edit me.mp4 --preset premium_editorial_viral --photos shot1.png shot2.png
  python editor.py polish me.mp4 --preset premium_editorial_viral --input photos=shot1.png
  ```

- **An existing project:**

  ```
  python editor.py graphics my.project.json --style premium_editorial --files shot1.png shot2.png
  ```

- **Integration API:** `"preset": "premium_editorial_viral"`. Your pictures go in the job's
  `photos` input.

**Your name and handle.** These go on the profile card. Put them in `config.yaml`:

```yaml
editorial:
  name: "Juan Cruz"
  handle: "@juancruz"
  brand: "JuanCo"          # under your logo
```

- **Without a name, there is no profile card.** Nothing is ever made up.
- **Your logo:** a picture whose file name contains `logo`.
- **Your photo on the profile card:** a picture whose name contains `avatar`, `profile` or
  `headshot`.

## What the preset sets · Ang itinatakda ng preset

| | |
|---|---|
| Cuts | `fast` pacing (pauses and fillers cut) with the jump-cut punch-in zoom |
| Captions | style 14 `editorial_card`: ink words on a cream rounded card with a soft shadow, the spoken word in terracotta |
| Colour | `natural_clean` |
| Graphics | the `premium_editorial` style, planned scene by scene (below) |
| B-roll | **no stock search, no AI-made clips**: only your own files |
| Music | a file with "upbeat" in its name from your music folder, quiet (none is bundled) |

As with every preset, your own choices (format, graphics, words) still win. Everything it adds is
ordinary, editable clips on the timeline.

## How the scenes are planned · Paano pinaplano ang mga eksena

### 1. Scenes

The spoken words are cut into scenes of about **2–4 seconds**, on sentence boundaries:

- A long sentence is split at its longest pause.
- Short sentences are joined.
- A spoken list ("una …, pangalawa …, pangatlo …") stays one scene, up to 8 s, so its checklist
  can tick every item.

### 2. One beat per scene

Each scene gets **one main idea**, the "beat", that suits what is said.

| What is said | Beat |
|---|---|
| the hook (scene 1) | serif **headline** or **kinetic words** |
| a strong claim | **headline**, **kinetic words** or a **marker** sweeping over the keyword |
| a list | **checklist** that ticks each item as you say it; **UI panel** for a setup; **storyboard** page for a plan (with your pictures) |
| "i-search mo …", "search …" | a **search bar** typing what you said |
| "30 seconds", "5 minutes" | a **countdown** from that number |
| colours, "kulay", palette | **colour palette** taken from your picture or logo |
| follow, subscribe | your **profile card**; the Follow button turns to Following on the word |
| brand, shop, sponsor | your **logo** |
| app, results, proof, photos, "tingnan" | your screenshots as a **collage**, **montage**, **mosaic** or in a **phone**; or one of your clips as a floating **picture-in-picture** |
| a quiet moment | a slow **camera push-in** (no graphic) |

**Variety rules:**

- Never the same beat twice in a row.
- Big picture beats are never back to back, and at most about 4 in 10 scenes.
- Your pictures come back every few scenes when you gave some.
- The profile, logo, palette, countdown and storyboard beats are used once each.
- The subtitle card is used only when the video has no captions, since the cream captions already
  are the cards.

**With an AI** (Groq or Anthropic, your key):

- The AI chooses the beat and the exact words for every scene.
- Plain code then checks each choice:
  - The words must really be said in that scene.
  - The pictures must be yours.
  - The beat must fit the rules above.
- A wrong answer is sent back once with its problems.
- After that, or without an AI, the rules choose.

### 3. Timed to your words

- Every element starts on the frame of its word.
- The parts of an element appear on their own words (`cues`):
  - the words of a headline
  - the items of a checklist or UI panel
  - the end of the typing
  - the arrival of each picture
  - the Follow button

### 4. The look under the beats

- **Dimming, blur and vignette** under the big picture beats.
- A **punch-in** on the key word of a headline, kinetic or marker beat.
- A **black-and-white transition** into a scene that turns the story ("pero", "but", "dati",
  "ngayon"), at most once every 12 seconds.
- A **picture-in-picture** with rounded corners, a cream border and a soft shadow. It slides in
  and fades out.

### 5. Placement

- Graphics keep off your face (with tracking set up; otherwise off the usual face area), unless
  they are made to cover it for a moment (your screenshots).
- They never cover the captions and stay inside the safe area.

### 6. Only your files

The planner uses only your pictures, clips, logo and name. Nothing is downloaded, generated or
invented. It skips:

- free-stock and AI-made B-roll, if an edit has any
- a beat that needs a picture you did not give

Without any pictures, the summary says so and the scenes use text, cards and camera moves.

## Changing one scene · Pagbago ng isang eksena

- **Storyboard (app or `python editor.py storyboard-edit my.project.json --scene N`):**
  *Regenerate* gives every editorial scene in that storyboard scene another beat. The rest of the
  edit stays as it is.
- **A single graphic:** *Another look* in the Graphics inspector, or `python editor.py
  graphics-regenerate my.project.json --clip g3`. Its scene gets another graphic beat.
- **Locked clips are never changed.** A scene with a locked graphic or effect is not planned
  again; unlock it first.
- **Running the whole plan again** (`graphics --style premium_editorial`, or the AI edit) replaces
  only what the planner made. Its clips:
  - graphics with a `director` note
  - effect and overlay tracks whose ids start with `pe-`

  Your own and locked clips stay.

The plan is saved in the project (`meta.editorial.scenes`: start, end, beat and words of each
scene).

## What was and was not verified · Ano ang nasubukan

**Verified here (automatically, Linux, synthetic media made with FFmpeg):**

- **Scenes and beats:**
  - scenes of 2–4 s
  - a spoken list kept in one scene
  - the beat for each kind of line (list, search, countdown, colours, follow, screenshots)
  - no beat twice in a row
  - no back-to-back picture beats
- **Timing:**
  - each graphic starts on its word
  - checklist ticks land on the frame each item is said
- **Your files only:**
  - only your pictures are used; stock-marked media is ignored
  - no profile card without your name
  - the palette comes from your own logo
  - a PiP shows your clip with its style
- **The AI's choices:**
  - used when they check out
  - words that were never said, or pictures that are not yours, are sent back, then the rules
    take over
  - an AI error falls back to the rules
  - the AI cannot break the variety rules
  - choices are cached
- **Editing:**
  - running again keeps locked clips
  - one scene planned again changes only that scene
  - the storyboard and *Another look* use the scene planner
- **The preset:**
  - valid, and offered by the integration API
  - a polish job with it is accepted
  - a full polish with it passes the quality checks
- **A full edit rendered with FFmpeg and Chromium**, checked frame by frame:
  - your screenshots are on screen
  - the background is dimmed under them
  - the B&W transition drains the colour
  - the checklist ticks fill in
  - the cream caption card is drawn
  - the MP4 has the right length

**NOT VERIFIED:**

- real Taglish speech (the word rules were tested on typed Taglish text, not on a real Whisper
  transcript)
- Windows
- your real footage, screenshots and logo
- the real desktop app on your PC (the app was tested as a browser build with a stand-in engine)
- a real AI model's scene plans (a stand-in AI was used)
- how "premium" it looks to a viewer

These are sensible starting points; check the storyboard before you render.
