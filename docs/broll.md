# B-roll and effects (the "B-roll / VFX director") · B-roll at mga epekto

B-roll is the extra picture you show over yourself while you talk: a cup of coffee when you
say "kape", a jeepney when you talk about your commute. The AI edit can now plan it, and the
editor finds or makes each one for you. *Ang B-roll ay mga dagdag na kuha na ipinapakita habang
nagsasalita ka.*

## Where B-roll comes from · Saan ito kinukuha

For every B-roll item, in this order (you can also choose one source only):

1. **Your own B-roll folder** · *sarili mong folder*. Choose it in **Settings** (or the
   **B-roll** tab in the editor). Name files and folders after what they show:
   `coffee\cup morning.jpg`, `jeepney street.mp4`, `cartoon\robot.png`. Words in the file
   name *and* its folders count. Half of the search words must match.
   A folder or file named `cartoon`, `drawing`/`sketch`, `low_poly`, `3d`/`robot`, `anime`
   marks that look; such files are only used when that look is asked for.
2. **Free stock** · *libreng stock*: Pexels and Pixabay, **only if you saved your own free
   key** in Settings (get one at <https://www.pexels.com/api/> and
   <https://pixabay.com/api/docs/>; both are free). No key = this step is skipped. No key is
   built into the app.
   - Pexels has real photos and footage (used for the *realistic* look).
   - Pixabay also has illustrations and animations (used for cartoon, drawing and the other
     looks).
   - Portrait (9:16) results are preferred. Only the one picture/clip that is used is
     downloaded, into a `broll` folder next to your project, and kept there.
3. **AI generation** · *gawa ng AI*: WanGP on your PC, with your quality tiers (see
   [generation.md](generation.md)): the draft tier for a quick preview, then the final tier;
   one GPU job at a time; if a tier fails or runs out of memory, the next one down is tried;
   the per-video limits apply. No WanGP = this step is skipped, and the summary says so.

If nothing is found or made, the edit still finishes; the summary says which B-roll was left
out and why.

## Looks · Itsura

| Look | What it means |
|---|---|
| Realistic | real footage or photo (default) |
| Cartoon | flat 2D cartoon |
| Drawing / sketch | hand-drawn pencil sketch |
| Low-poly / boxy 3D | simple boxy 3D shapes |
| Stylized 3D / robot | toy-like or robot-like 3D render |
| Anime | anime illustration |

For AI generation, the look's words are added to the prompt (for example *"…, flat 2D cartoon
illustration, bold outlines, bright colours"*).

## In the AI edit · Sa AI edit

Ask for it in your instruction, for example:
- *"Lagyan mo ng b-roll pag nagsasalita ako tungkol sa kape at jeep."*
- *"Add cartoon-style b-roll, AI-generated lang."*
- *"May transitions sa bawat bagong topic, at shake sa punchline."*

The AI is told which sources you have (how many files your folder has and the words in their
names, which stock sites have a key, what WanGP can make). It plans each item with what it
shows (English), 2 to 4 search words, a look, and the source (normally "auto"). With Auto mode
off, each B-roll item and effect is listed for review, and you can untick any of them.

**Effects (the "VFX" part):** the AI can also plan short accents: flash, whip blur, shake,
glitch, dip to black. A *transition* is placed exactly on the nearest jump cut. They become
normal clips on the Effects track, so you can move them, change their strength or delete them.

## In the editor · Sa editor

- **B-roll tab** (left): describe what to show, choose look, picture or video clip, place
  (full screen, top, middle), seconds and where from, then **Add at the playhead**. Your
  B-roll folder is listed below; **＋** adds a file yourself.
- **Click a B-roll clip** (right panel):
  - where it came from: your folder, the stock credit with links to the source page and the
    licence, or **AI** (with the tier);
  - **Find another · Iba pa**: the same description, a different file (your folder, then stock,
    then AI); it skips the files it already showed on this clip;
  - **Regenerate with AI · Gawin ulit**: a new AI version (quick draft or final);
  - **Replace with a file…**: your own picture or video instead;
  - change what it shows, the search words or the look for the next search.
  
  Each of these is one undo step (**Ctrl+Z**). The clip keeps its place, size and timing; a
  video shorter than the clip shortens the clip.
- AI-made clips have a purple **AI** badge on the timeline.

## Licences, credits and AI labels · Lisensya at kredito

- **Stock:** each clip keeps the author, the source page and the licence
  ([Pexels License](https://www.pexels.com/license/),
  [Pixabay Content License](https://pixabay.com/service/license-summary/)). Neither requires
  credit, but the **Export** window gives you ready-to-paste credits, and giving credit is
  kind and recommended. Do not sell the stock files as they are, and check the licence for
  things like people or brands in the picture.
- **AI-made content:** the Export window reminds you when your video has AI-made B-roll.
  TikTok, Facebook/Instagram and YouTube ask creators to label realistic AI-generated
  content: turn on the platform's AI label when you post. *I-on ang AI label pag nag-post.*
- **WanGP and its models** have their own licences (see [generation.md](generation.md)). The
  app never downloads a model by itself.
- Never use B-roll to fake a real person or event. The app has no face swap, deepfake, voice
  cloning or lip-sync.

## Command line

```
python editor.py ai-edit inbox\myvideo.mp4 -i "lagyan ng b-roll" --broll-library "D:\My B-roll"
python editor.py ai-edit inbox\myvideo.mp4 -i "..." --no-stock          (never ask Pexels/Pixabay)

python editor.py broll --search "coffee cup" --kind image                (find one, print it)
python editor.py broll output\myvideo_ai.project.json --clip o3          (find another for clip o3)
python editor.py broll output\myvideo_ai.project.json --clip o3 --source ai --quality draft
python editor.py broll output\myvideo_ai.project.json --new --at 4.5 --duration 2 ^
    --prompt "a jeepney on a busy street" --style cartoon --position top
```

Settings in `config.yaml`:

```yaml
broll:
  library_folder: ""      # your B-roll folder
  use_stock: true         # Pexels/Pixabay, only with PEXELS_API_KEY / PIXABAY_API_KEY in .env
```

On the command line, put the stock keys in `.env` (see `.env.example`). They are never printed.

## Files

| File | What |
|---|---|
| `autoedit/broll.py` | the order of sources, library matching, looks, adding/replacing clips |
| `autoedit/stock.py` | Pexels and Pixabay search and download (credits, licences) |
| `<project folder>\broll\` | stock downloads, kept so they are fetched once |
| clip `broll` in the project | where each clip came from (see [project-format.md](project-format.md)) |

## What was and was not verified

**Verified (automatically, on Linux):**
- Library matching (file and folder words, plurals, looks, "find another"), the source
  order, and that a "library only" request never falls back to AI: Python tests.
- Pexels/Pixabay search and download with **faked answers** (no network): the request
  (key in the header or parameter, portrait), which file is picked, credits, licences, the
  plain messages for a refused key / the free limit / no internet, that keys are never
  printed, that downloads are kept and never left half-written.
- AI B-roll with the **stand-in WanGP** (no GPU): draft tier, labels, the AI flag.
- The whole AI edit with B-roll from a folder, and planned effects landing on the right
  moment (the same mapping as the captions) and transitions centred on a jump cut.
- The editor's B-roll operations give the same clips as the engine's, and the engine accepts
  every result (also inside the random-edit test); 3 browser tests drive the B-roll tab,
  find another, regenerate, replace, cancel, the stock credit and the export's credits and
  AI label, with results the real engine made.

**Not verified:**
- **Real Pexels/Pixabay calls** (no network or keys here): their real answers, rate limits
  and download speed. The request format follows their public API documentation.
- **Real WanGP** pictures and clips in each look, and how well the look words work with each
  model.
- How well the AI plans B-roll and effects for real Taglish videos (no AI service could be
  reached).
- The real Electron window on Windows (links opening in the browser, folder dialogs).
