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

Caption text editing, styles per caption, sound effects and transitions come in the next update.

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
- the sound of B-roll clips is not used (in the export either).
