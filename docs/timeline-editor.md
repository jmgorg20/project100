# The timeline editor · Ang timeline editor

After the AI edits your video, you can fix anything by hand on a CapCut-style timeline:
cut, move, speed up, change the volume, reframe for 9:16, then export.
*Pagkatapos ng AI edit, puwede mong ayusin ang kahit ano nang mano-mano.*

## Open it · Paano buksan

- After an AI edit: under **What the AI did**, click **Edit on timeline · Buksan sa timeline**.
- Any project: click **Open project…** at the top and choose a `.project.json` file.
  Every AI edit and every `python editor.py edit` saves one next to the video.

The first time you open a project, a copy of it is kept as
`<name>.before-editing.project.json`. To go back to the AI's version, open that file
instead.

## The screen · Ang screen

| Part | What it does |
|---|---|
| **Preview** (top middle) | Plays the timeline live. **Exact frame** asks the engine for the real frame, exactly as it will export. |
| **B-roll** (left) | Describe a picture or clip and the app finds or makes it; your B-roll folder. See [B-roll](#b-roll--dagdag-na-kuha). |
| **Media** (left) | The project's files. **Import** adds videos, pictures and sound files. Drag one onto a track, or use **＋ Video**, **＋ B-roll** or **＋ Sound** to add it at the playhead. You can also drop files from Windows Explorer onto the editor. |
| **Clip settings** (right) | Settings of the clip you clicked (see below). |
| **Timeline** (bottom) | From top to bottom: captions, effects (zoom, colour), B-roll and photos, the **main video**, then voice-over, music and sound effects. Each track can be muted 🔈, hidden 👁 or locked 🔓. |

## Editing · Pag-edit

- **Select:** click a clip. Shift- or Ctrl-click selects more.
- **Split:** put the playhead where you want the cut and press **S**, or click **✂ Split**.
  With clips selected, only they are split; otherwise everything under the playhead is.
- **Delete:** select and press **Delete**. On the main video the gap closes by itself.
- **Trim:** drag the left or right edge of a clip. A clip cannot go past the start or end
  of its file.
- **Move:** drag a clip left or right, or onto another track of the same kind. If it would
  overlap another clip, it goes onto a new track of that kind (for example "Captions 2").
- **Reorder the main video:** drag a main clip; a blue line shows where it will go.
- **Snapping** (on by default, key **N**): edges snap to other clips' edges and to the playhead.
- **Undo / redo:** **Ctrl+Z** / **Ctrl+Shift+Z** (or the ↶ ↷ buttons). Dragging a slider is
  one undo step, not dozens.
- **Saving:** automatic, a moment after each change ("Saved · Naka-save" at the top). If
  saving fails (disk full, file locked), it says **Not saved!**; hover over it for the reason.

### The main video is "magnetic" · Magnetic ang main video

Like CapCut, the main video track has no gaps. When you delete, trim or speed up a main clip,
everything after it moves. **Captions, effects, B-roll and sounds that sit on that part of the
video move with it:**
- deleting a part of the main video also removes the captions that were on it;
- reordering moves the captions with their clip;
- 2x speed squeezes those captions to match.

Lock a track (🔓 → 🔒) to keep it exactly where it is.

### Clip settings · Mga setting ng clip

- **Speed · Bilis:** 0.25x to 4x (buttons 0.5x / 1x / 1.5x / 2x / 3x, or the slider).
  The voice keeps its pitch.
- **Sound · Tunog:**
  - **Volume** goes from 0 to 400%. The preview cannot play louder than 100%, but the export can.
  - **Fade in / Fade out** are in seconds.
- **Frame · Pag-frame (9:16):**
  - **Fill the screen** crops the sides of a wide video.
  - **Show all, blurred background** shows the whole picture.
  - With Fill: **Zoom**, **Left ↔ right** and **Up ↕ down** choose which part of the picture
    stays in view.
- **B-roll / photo:** position, size, opacity, pop-in animation.
- **Zoom effect, colour grade:** amount, and which colour look.


## Captions · Mga caption

Click a caption **on the picture** (or its clip on the timeline). On the right you can then:
- **Words:**
  - type over a word (typing two words splits its time between them; clearing a word removes it);
  - change when it starts;
  - ★ highlight it in the keyword colour;
  - add an emoji (😂🔥❤️👍…) after the word you clicked last.
- **Listen again · Pakinggan ulit:** sends that part of the video to the transcriber again,
  with your vocabulary, and replaces just those captions. Undo brings the old ones back.
  It needs your Groq key, or the local transcriber.
- **Look:**
  - all 13 caption styles;
  - place: the style's own, lower, middle or top;
  - size;
  - whether ★ highlights are coloured;
  - tick **Change every caption** to apply it to all of them.
- **Add a caption:** with nothing selected, type it under **Captions** on the right; it goes
  at the playhead.

### Your words & corrections (Taglish)

With nothing selected, click **Your words & corrections**:
- **Words:** names, brands and slang the transcriber should spell right (GCash, Shopee,
  Ate Rose…). They are sent with every transcription as a hint.
- **Corrections:** "when it hears… → write…" (e.g. *g cash → GCash*). Case doesn't matter.
  They are applied to every transcript, including ones saved before.
- **Save & fix this video's captions** also fixes the captions already on this timeline.

They are kept in `vocabulary.json` next to the editor (start from `vocabulary.example.json`),
so the command line uses them too.

## Sound · Tunog

With nothing selected:
- **Even out the loudness:** −14 LUFS is what TikTok, Reels and YouTube use.
- **Lower the music when someone talks:** ducking.
- **Reduce background noise:** steady fans and hiss. The noise level is measured in the
  pauses of your speech, so it adapts to each recording.
- **🎙 Record a voice-over:**
  1. pick a microphone and watch the level bar;
  2. press Record (3-2-1);
  3. press Stop and listen;
  4. **Use it**: it goes on the Voice-over track at the playhead, and the file is kept in a
     `recordings` folder next to the project.

The **Music** and **Sound FX** tabs on the left list your own folders (choose them once). You
can search, listen, and **＋** a file at the playhead. The app never ships music: use only
sounds you have the right to use.

Ducking and noise reduction are heard in the **export**; the live preview plays the sound as
recorded.

## Effects and transitions · Mga epekto

The **Effects** tab adds, at the playhead:
- punch-in zoom, smooth zoom;
- shake, flash, dip to black, glitch, whip blur.

**Transitions** go on the nearest cut of the main video (flash, whip blur, dip to black,
glitch). **Colour looks** go on the clip at the playhead, or on the whole video.

Each one is a normal clip on the Effects track: drag it, trim it, and set its **Strength** on
the right. A zoom has **Zoom in over** (0 = punch-in).

**Speed ramp:** select a main clip and choose a ramp under Speed (speed up, slow down, bullet
time, montage). The clip becomes 3 parts with their own speeds, which you can change later.

## B-roll · Dagdag na kuha

The **B-roll** tab finds or makes a picture or clip for what you describe: from your own
B-roll folder first, then free stock (Pexels/Pixabay, with your free key), then AI (WanGP).
Click a B-roll clip to see where it came from (credit, licence, or **AI**), and to **Find
another**, **Regenerate with AI** or **Replace with a file**. Each is one undo step.
Full guide: [broll.md](broll.md).

### Keyboard shortcuts · Mga shortcut

Press **?** in the editor for the full list.

| Keys | Action |
|---|---|
| Space or K | play / pause |
| S or Ctrl+B | split |
| Delete | delete |
| Ctrl+Z / Ctrl+Shift+Z | undo / redo |
| ← → | one frame |
| Shift+← → | one second |
| ↑ ↓ | previous / next cut |
| Home / End | start / end |
| + / − / Ctrl+0 | zoom the timeline in / out / fit |
| N | snapping on/off |
| Ctrl+S | save now |
| Ctrl+E | export |

## Export · I-export

Click **Export** (or **Ctrl+E**) and choose:

| Option | Choices |
|---|---|
| **Size** | 1080×1920 (Full HD), 720×1280 or 540×960 |
| **Frames per second** | 24, 25, 30, 50 or 60 (the project's own rate is marked) |
| **Quality** | High, Standard (for TikTok/Reels), Smaller file, Quick draft |
| **Save as** | the file name (next to the project by default) |

The engine renders exactly what the timeline holds, with FFmpeg. A progress bar shows how far
it is, and **Cancel** stops it without leaving a half-written file. When it is done, use
**Show in folder** or **Play it**.

## How close is the preview to the export?

The preview is drawn live by the app, so it is close but not identical. Use **Exact frame** to
see the real thing. Checked automatically:
- **Reframe/crop:** the preview places the picture within about 1 pixel of the engine's
  frames (5 cases, including wide videos).
- **Caption and photo positions:** they match the engine's rendered frames (earlier tests).
- **Speed:** a 2x clip plays at 2x; the timeline-to-source time maths is the same as the engine's.
- **Fades:** the same linear shape as FFmpeg's `afade`.

Known differences:
- fonts, outlines and colour grades are drawn by the browser;
- volume above 100% plays at 100% in the preview;
- "Show all, blurred background" shows black instead of the blurred copy;
- the sound of B-roll clips is not used (in the export either);
- effects:
  - the flash, dip, shake and smooth zoom follow the engine's timing;
  - glitch and whip blur are only rough look-alikes;
  - colour strength is blended in CSS;
- ducking and noise reduction are only in the export.
