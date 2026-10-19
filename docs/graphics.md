# Motion graphics and the Director · Mga pop-up na salita at graphics

Write **"Edit this like a professional promoter"** and the AI edit adds pop-up words, cards,
counters, arrows and emoji where the important words are said. Their shape, font, colour and
motion follow the meaning and the mood of what you say. Everything is free and runs on your PC.
*Libre at lokal ito. Walang download, walang bayad na assets, walang logo ng ibang brand.*

## Quick start · Mabilis na simula

1. In the app, write your instructions as usual, for example *"Edit this like a professional
   promoter"*, *"lagyan ng graphics, parang news"*, or *"meme style, maraming emoji"*.
2. Under **Motion graphics** pick a look, or leave **Auto**: Auto adds graphics only when your
   instructions ask for them (words like *promoter, graphics, pop-up, kinetic, meme, news,
   luxury, documentary, minimal*).
3. Click **Edit with AI**. The summary lists every graphic and why.
4. Open the timeline editor: the graphics are clips on the **Graphics** track. Move, trim,
   change, lock or delete them like any clip.

On the command line:

```
python editor.py ai-edit myvideo.mp4 -i "Edit this like a professional promoter" --graphics promoter
python editor.py graphics output\myvideo_ai.project.json --style meme       (add/redo graphics)
python editor.py graphics output\myvideo_ai.project.json --style news --no-ai
python editor.py graphics-regenerate output\myvideo_ai.project.json --clip g3
python editor.py graphics-check output\myvideo_ai.project.json
python editor.py graphics-catalog                                          (list the templates)
```

## The looks (styles) · Mga istilo

| Style | What it does | Max per 10 s |
|---|---|---|
| **Professional promoter** | pop-up words, counters, cards, pills, emoji; flash / punch-in / whip on the big moments | 4 |
| **Calm documentary** | thin and elegant titles, slow slides, lower-thirds, no flashes | 1 |
| **Meme / funny** | meme captions, stickers, emoji, bouncing words | 3 |
| **News / explainer** | headline banners, lower-thirds, numbers, checklists | 2 |
| **Luxury / premium** | serif and gold titles, fine lines | 1 |
| **Minimal** | now and then one clean word or underline | 1 |

You can change the numbers in `autoedit/director_styles.py`, or the limit only with
`graphics: max_per_10s:` in `config.yaml`.

## The template library · Ang mga template (63)

All of them are made in this app (HTML/CSS drawn by Chromium), with free fonts (SIL Open Font
License, in `desktop/graphics/fonts`). Emoji use your computer's emoji font.

- **Words:** heavy pop, thin spaced, glow blur-in, bounce, slide up, drawn underline, highlight
  box, stamp, typewriter, glitch, outline fill, gradient shine, letter reveal, elegant serif,
  handwritten, news banner, meme caption, karaoke line
- **Cards:** prompt card (typing), notification stack, polaroid, icon badge, clock, title with
  chips, quote card
- **Pills:** lower-third ("Revision #11 ✓"), "Comment EDIT" with a click, @handle Follow →
  Following
- **Numbers:** counter, percent bar, price tag, checklist, star rating
- **Pointers:** arrow, circle, scribble underline
- **Fun:** emoji pop, emoji burst, hearts, warning banner, sticker, before/after tags
- **Formats** (used by the video formats, see [formats.md](formats.md)): numbered list item, rank
  number, A vs B split card, callout box, screenshot frame

In the editor: **Graphics** tab → search, filter by mood, ★ favourites (kept on this PC), and
**Add** puts one at the playhead. Each card shows the template moving.

Text tips: write `*word*` to make that word stand out (bigger, another colour, a box). Long
Taglish words are never broken in the middle; the text gets smaller first. Only a single word too
long for the box, even at the smallest size, is broken (and the export check says so).

### The editorial set (Premium Editorial Viral) · Ang editorial na set

Sixteen templates for the PREMIUM EDITORIAL VIRAL look: cream paper, ink text, serif headlines,
one terracotta accent, soft shadows, rounded corners, calm motion. **Only the editorial style
uses them** (the other looks never pick them); you can add any of them by hand from the Graphics tab.

| Template | What it shows |
|---|---|
| `editorial-headline` | magazine headline: kicker label, rule, issue number (`number`), serif words that arrive one by one, `*word*` in italic accent |
| `subtitle-card` | a cream rounded subtitle card; the spoken word lights up, `*word*` gets a marker |
| `kinetic-words` | big words that pop in one at a time (sans + italic serif mix), no card |
| `marker-highlight` | a sentence on paper; a marker pen sweeps over the `*keyword*` |
| `screenshot-collage` | 2–4 of **your** screenshots floating at angles, one after another (`images`) |
| `mosaic-grid` | a 2×2 / 3×2 / 3×3 grid of your pictures, tile by tile; `number` = a tile to focus at the end |
| `search-bar` | a search bar that types the query, then suggestion rows (`items`) |
| `ui-panel` | a floating app window: rows whose switches turn on one by one, a progress bar |
| `editorial-checklist` | a paper checklist; each item is ticked in turn, with a count (2/3) |
| `countdown-timer` | a digital countdown from `number` seconds to 0 with a draining ring |
| `storyboard-doc` | a storyboard page: scene frames from your pictures with their captions (`items`) |
| `phone-mockup` | a generic phone (no brand) showing your screenshot, floating in |
| `logo-badge` | **your** logo (`image`, required) in a rounded tile with a name |
| `screenshot-montage` | one card that slides through your screenshots, with dots |
| `palette-card` | colour swatches with their hex codes (`items` = `#rrggbb`; can be taken from your picture) |
| `profile-card` | a social profile: your photo or initials, name, handle, a Follow button that turns to Following |

**Your pictures only.** `image` / `images` are media of your project (your screenshots, photos,
logo). Without them a plain numbered placeholder is drawn; nothing is downloaded or made up, and
no real person or brand is bundled.

**Timed to the words (`cues`).** Every template whose parts appear one after another (words,
items, steps, pictures) takes `cues`: the seconds, from the graphic's start, when each part
should appear. The Director sets them from the spoken words, so each part lands on the word that
names it. Without cues the parts are spread evenly.

**Caption style 14, `editorial_card`.** Ink text on a cream rounded card (with a soft shadow)
behind each caption group; the spoken word in terracotta.

## Editing a graphic · Pag-edit

Click it on the timeline or on the preview. On the right you can change:

| Setting | |
|---|---|
| **Template** | another template of the same kind (the words stay) |
| **Another look** | the next template of the same kind, never the same as the graphics next to it |
| **Regenerate** | the Director makes a new one for the same words (tick *ask the AI* to use your AI key; otherwise simple rules) |
| **Text, second line, items, number, emoji, icon, picture** | what it shows |
| **Colours, font, size, intensity** | the look |
| **Across / up-down** | where its centre is |
| **On the picture when it starts** | a flash, whip or punch-in at its first frame |
| **Lock** | nothing can move or change it, and the AI keeps it when it redoes the graphics |

**Before/after wipe:** Effects tab → *Before/after wipe*. A white line sweeps across; the side it
has passed gets a colour look (choose the look, direction, speed and where it stops).

## The rules the Director follows · Mga patakaran

The AI picks *which* graphic goes with *which* words. Plain code then checks every graphic
(the same rules for the AI's plan and for the simple fallback plan):

- **On time:** a graphic starts on the frame of the first word it belongs to.
- **Only important words:** never on filler (*ang, yung, ng, um*).
- **Not too many:** at most N per 10 seconds (the style's limit), a minimum gap between them, and
  never two big graphics at once.
- **Variety:** never the same template twice in a row; no template used over and over.
- **The right mood:** money talk gets money styles, warnings get warning styles, and so on.
- **Never on your face:** with tracking set up (docs/tracking.md) the real face position is used;
  without it, the upper middle of the frame (where a speaker usually is) is kept clear, and the
  summary says so.
- **Never on the captions**, and inside the part of the screen TikTok/Reels do not cover.
- **Readable:** short text, not too small, enough contrast.

If the AI's plan fails the checks, it is asked once more with the problems listed; if it fails
again (or no AI key / no internet), simple rule-based graphics are used and the summary says so.

## Before you export · Bago mag-export

The Export window checks the graphics and warns when one:
covers the face, runs off the screen, sits where the app's buttons are, sits on the captions,
has text that had to shrink below 30 px (*min_font* in `config.yaml`), had to break a word, has
too little contrast, or runs past the end of the video. You can still export.

## How it is made (for the curious) · Paano ito ginawa

Each graphic is drawn frame by frame by a Chromium (in the app: a hidden window; on the command
line: Playwright's Chromium, or Microsoft Edge / Chrome) into a small lossless video with
transparency (FFV1), saved in `work\cache\graphics` under a key made from everything that
changes its pixels. Moving a graphic does not redraw it; changing its text or length does. FFmpeg
then lays these videos over the picture. The preview in the editor draws the same templates live
in the page (a little lighter), so place and timing match the export.

## What was and was not verified

**Verified (automatically, on Linux):**
- All 63 templates (47 + the 16 editorial ones) drawn by a real Chromium: not empty, centred where x/y say, same pixels on
  every run (up to tiny anti-aliasing differences), going in and out, within the frame, with
  Taglish text, *ñ*, emoji and very long words (no word breaks in normal sentences).
- Compositing measured on the rendered pixels: a graphic appears exactly on its frames and where
  x/y say; a picture inside a polaroid; the before/after wipe (one side graded, white line); the
  flash and punch-in at a graphic's start; the cache (drawn once, redrawn only when needed).
- The Director with a stand-in AI: valid plans used, bad plans retried once with the problems,
  failures falling back to rules; sync to word frames; density, gap and variety limits; mood
  match; never on synthetic face tracks (still, moving left-right, moving down) or the default
  face area; never on captions (lower, centre, top); text length and contrast; locked graphics
  kept; one graphic regenerated alone; the export check.
- The editor (in a browser with a stand-in for the app's bridge): the Templates tab, adding,
  editing, locking, another look, regenerate, the wipe, the export check, the style menu; random
  edit sequences always give projects the engine accepts.
- The app's drawing service with Playwright's Chromium standing in for Electron's hidden window.

**NOT verified:**
- **Electron's hidden window** drawing the frames (no Electron here): its transparency and
  timing were not seen working. If graphics come out with a black background or missing in the
  app's exports, please report it; the command line path (Node.js + Edge/Chrome) is the fallback.
- **Real Taglish speech** and a real AI provider: the Director's choices on real transcripts.
- **How it looks**: the look-and-feel and taste of the templates on your videos. This is not
  "Hollywood quality"; it is a set of clean, editable templates.
- **Windows**, Edge/Chrome as the command-line browser, and **speed on your PC** (here: about
  0.05 s per frame to draw a graphic with Chromium on the CPU).
- Real face positions: only synthetic face tracks were used in the tests.
