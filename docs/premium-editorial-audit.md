# Premium Editorial Viral: audit of the 30 techniques

The style is **Premium Editorial Magazine + Cinematic Talking-Head + Kinetic Typography + Animated
Motion Graphics**. This page checks each of its 30 techniques against what the app and engine do
today (as of `main` at the "Phase 7.6" merge), so the work that follows is honest about where it
starts.

**Status**

- **ALREADY WORKING**: built *and* covered by an existing test that renders it, or by a real render.
- **PARTIALLY WORKING**: some of it exists, but not what this style needs.
- **MISSING**: not there.
- **BLOCKED**: cannot be done here.

None of the 30 is blocked.

**Where things live (short names)**

| Short name | Path | What it does |
|---|---|---|
| runtime | `desktop/graphics/engine.js` | the HTML/CSS graphics runtime, drawn by Chromium |
| templates | `desktop/graphics/templates/*.js` | the templates (catalog: `autoedit/graphics_catalog.json`) |
| renderer | `autoedit/project_render.py` | the FFmpeg project renderer |
| Director | `autoedit/director.py` and `director_styles.py` | picks and places graphics |
| formats | `autoedit/formats.py` and `formats/*.json` | the video formats |
| captions | `autoedit/captions.py` and `styles.py` | caption styles |
| presets | `autoedit/presets/*.json` | the style presets |
| storyboard | `autoedit/storyboard.py` | the scene view |

**Tests used as evidence** (all 337 tests in these files passed in this environment when the audit
was written, with Chromium drawing the templates, so none were skipped)

| Short name | Test file | What it checks |
|---|---|---|
| T-tpl | `tests/test_graphics_templates.py` | every template is drawn in Chromium: frame not empty, same pixels each time, animates in and out, Taglish text fits |
| T-gfx | `tests/test_graphics_render.py` | graphics rendered over video at their frames |
| T-rnd | `tests/test_project_render.py` | render pixel checks |
| T-fmt | `tests/test_formats.py` | format renders |
| T-cap | `tests/test_captions.py` | every caption style rendered with FFmpeg |
| T-dir | `tests/test_director.py` | Director rules: sync, density, face, captions |

| # | Technique | Status | Where it lives now | What is needed |
|---|---|---|---|---|
| 1 | Editorial magazine typography | PARTIALLY WORKING | `serif-elegant` (Playfair serif, gold accent) and `thin-spaced` templates (T-tpl). | A magazine headline: kicker / small caps label, large serif headline with an italic emphasis word, thin rules, issue-style number, cream or ink colourways. Director must be able to pick it. |
| 2 | Minimalist subtitle cards | PARTIALLY WORKING | Caption style `boxed` (white text on a black box, T-cap). | A cream rounded caption card with dark serif/sans text, soft shadow, one short phrase at a time, the spoken word marked; a caption style the preset uses. |
| 3 | Kinetic typography | PARTIALLY WORKING | `bounce-words`, `split-reveal`, `slide-up`, `karaoke-line`, `glow-blur-in`, `pop-heavy` (T-tpl); captions `pop_word` / `typewriter` (T-cap). Inside a graphic the words move on a fixed schedule, not when they are spoken. | Word-by-word kinetic text whose words land on the spoken word times (needs #30), with editorial fonts. |
| 4 | Floating screenshot collage | PARTIALLY WORKING | `screenshot-frame` shows one image (T-tpl, image drawn: T-gfx `test_image_param_is_drawn`). | Several of the user's screenshots floating at angles, layered with shadows, entering one after another. Templates take one image only today. |
| 5 | Animated mosaic / grid layout | MISSING | Only the split-screen layout of two videos (formats). | A grid of the user's photos / screenshots (2×2, 3×2, 3×3) that builds tile by tile and can focus one tile. Needs multi-image template input. |
| 6 | Search bar typing animation | MISSING | `typewriter` types plain text, `prompt-card` is a chat-style prompt (T-tpl); no search bar. | A search bar (rounded field, magnifier, caret) that types the query, optionally with suggestion rows. |
| 7 | Floating UI panels and checklists | PARTIALLY WORKING | `checklist`, `notification-stack`, `prompt-card`, `callout-box` (T-tpl). | A floating app-window / panel (title bar, rows, toggles, progress) with soft shadow and rounded corners, in the editorial colourways. |
| 8 | Black-and-white transitions | PARTIALLY WORKING | A `grade` clip `black_and_white` (T-rnd `test_grade_intensity_and_smooth_zoom`) and the before/after `wipe` with that grade (T-gfx). | A transition that drains colour into B&W at a cut (and back), as an effect the Director can place at scene changes. |
| 9 | Animated countdown timer | PARTIALLY WORKING | `clock-timer` (a spinning clock face) and `counter-number` (counts up to a number) (T-tpl). | A digital countdown (3-2-1 / mm:ss ticking down, ring draining) synced to the time it is on screen. |
| 10 | Storyboard document animation | MISSING | The storyboard (`storyboard.py`, desktop Storyboard view) is an editing view, not a graphic. | A graphic of a storyboard / document page: panels with frames from the user's own media and captions, revealed panel by panel. |
| 11 | Punch-in zoom | ALREADY WORKING | `zoom` clip with no `ease` = instant punch-in (T-rnd `test_grade_intensity_and_smooth_zoom`); `attach: punch` on a graphic (T-gfx `test_attached_punch_zooms_the_picture`); pacing zooms in the AI edit. | Use in the preset on emphasis words. |
| 12 | Zoom-out / reframing | PARTIALLY WORKING | Reframing with `crop` (T-rnd `test_crop_reframes_the_picture`); a smooth zoom only grows (in), it never returns. | A smooth zoom-out (from a tighter crop back to the wide shot) and an in-and-out "breathing" zoom, with easing. |
| 13 | Text pop-in | ALREADY WORKING | `pop-heavy`, `stamp`, `emoji-pop` templates (T-tpl animates in/out), captions `pop_word` (T-cap `test_pop_word_animates_scale`). | Editorial-looking variants in the new templates. |
| 14 | Text scaling | ALREADY WORKING | Scale-in animations in `pop-heavy`, `glow-blur-in`, `highlight-box` (T-tpl). The `size` parameter scales any template (T-tpl). | A slow "push" scale on headlines in the editorial templates. |
| 15 | Picture-in-picture | PARTIALLY WORKING | Video `layout: pip` (you small over another video, corner, moving border) rendered and checked in T-fmt `test_reaction_pip_corner_and_moving_border`. | A floating PiP window of a *second* user clip or photo over the talking head, with rounded corners, shadow and a smooth entrance/exit, placed by the Director. |
| 16 | Floating phone mockups (generic device frame) | MISSING | None. | A generic phone frame (no brand) drawn in CSS showing the user's screenshot / photo, floating and tilting in. |
| 17 | App logo overlays (user-supplied) | PARTIALLY WORKING | Overlay image clips can show any user image (`overlayClip`); `icon-badge` uses built-in icons only. | A logo badge template that shows the user's own logo file (rounded tile, label), used only when the user supplied one. |
| 18 | Dark vignette | MISSING | None. | A vignette effect clip (strength, softness) rendered by FFmpeg. |
| 19 | Background dimming | MISSING | None (overlay opacity only fades the overlay itself). | A dim effect that darkens (and optionally blurs) the picture under a graphic, timed with it. |
| 20 | Drop shadows | PARTIALLY WORKING | Graphics cards draw CSS box shadows (T-tpl). Overlay photos and B-roll have none. | Soft shadow option on overlay clips; consistent soft shadows in the new templates. |
| 21 | Rounded graphic cards | PARTIALLY WORKING | Cards in templates are rounded (`checklist`, `quote-card`, `prompt-card`...) (T-tpl). Overlay photos and PiP are square. | Rounded corners option on overlay clips; rounded editorial cards. |
| 22 | Screenshot montage | MISSING | None (one `screenshot-frame` at a time). | A montage template that cycles several user screenshots in one card (slide / stack). |
| 23 | Keyword highlighting | ALREADY WORKING | Caption keyword colours (T-cap `test_center_keyword_highlights_and_capitalises_keywords`), `*word*` emphasis in templates (`highlight-box`, `serif-elegant`...) (T-tpl). | Editorial marker-pen highlight on the keyword *when it is spoken*. |
| 24 | Color palette graphics | MISSING | None. | A palette card: swatches with hex codes / names, built from colours given or picked from the user's image. |
| 25 | Animated checklist progression | PARTIALLY WORKING | `checklist` ticks items one after another on a fixed schedule (T-tpl). | Each item ticks at the moment its words are spoken (needs #30); progress bar. |
| 26 | Multi-layer compositions | PARTIALLY WORKING | The renderer stacks main video → zoom → grade → wipe → fx → tracked fx → overlays → graphics → captions (T-rnd, T-gfx). No dimming / vignette layers, and no planned compositions. | Dim / vignette between the picture and the cards, shadowed overlays, and the Director composing 2-3 layers per scene (e.g. dimmed talking head + floating screenshot + headline). |
| 27 | Smooth overlay entrance / exit | PARTIALLY WORKING | Graphics ease in and out (T-tpl `test_template_animates_in_and_out`); overlay clips only `none` or `pop`. | Slide / fade / rise / scale entrances and exits with easing for overlay clips and PiP. |
| 28 | Social profile overlays | PARTIALLY WORKING | `follow-pill` (handle + follow button) and `comment-pill` (T-tpl), text only. | A profile card with the user's own photo (or initials), name, handle and a follow button; never a bundled real person. |
| 29 | Vertical 9:16 framing | ALREADY WORKING | Projects are 1080×1920 by schema; every render test checks 1080×1920 (T-rnd); `fit: fill` / `blur` and `crop` (T-rnd `test_crop_reframes_the_picture`). | Nothing new. |
| 30 | Speech-synchronized graphics | PARTIALLY WORKING | A graphic *starts* on the frame of its word (T-dir `test_graphics_start_on_the_frame_of_their_word`). What happens inside it (words, items, ticks) runs on a fixed schedule. | Pass the spoken word times into the template (`cues`), so kinetic words, highlights, checklist ticks and typing land on the words; the Director fills them. |

**Count:**

| Status | Count | Techniques |
|---|---|---|
| ALREADY WORKING | 5 | 11, 13, 14, 23, 29 |
| PARTIALLY WORKING | 17 | 1, 2, 3, 4, 7, 8, 9, 12, 15, 17, 20, 21, 25, 26, 27, 28, 30 |
| MISSING | 8 | 5, 6, 10, 16, 18, 19, 22, 24 |
| BLOCKED | 0 | — |

## Plan: one PR per milestone, in order

1. **Audit** (this page).
2. **Picture effects in the renderer:**
   - techniques: 8, 12, 15, 18, 19, 20, 21, 26, 27
   - vignette, dimming, B&W transition, zoom-out and breathing zoom
   - overlay rounded corners, shadow and smooth entrance / exit (so PiP floats)
   - each tested by real FFmpeg renders with pixel checks
3. **Editorial graphics templates:**
   - techniques: 1, 2, 4, 5, 6, 7, 9, 10, 16, 17, 22, 24, 28, plus editorial variants of 3, 13, 14, 23, 25
   - multi-image inputs from the user's own media
   - each drawn in Chromium, rendered over video and checked
4. **Speech-synchronized graphics (30):**
   - word cues passed into templates
   - kinetic text, highlights, checklist ticks and typing on the spoken words
5. **The PREMIUM EDITORIAL VIRAL preset:**
   - preset JSON (English + Taglish) and a Director style
   - a scene-by-scene plan that chooses effects per scene, with a visual change every 2–4 s
   - jump cuts and punch-in / out
   - user assets only
   - polish CLI and the service can use it
6. **Desktop app:**
   - the preset in the dropdown
   - regenerate one scene with the new effects
   - preview and export controls for the new clip types
7. **End-to-end render with generated media**, the frame checks, and the final "NOT VERIFIED" list.

## Not verified by this audit

This page reads code and existing tests. The following has not been checked:

- real Taglish speech
- Windows
- the user's own footage
- the desktop app on the user's PC

## Status after each PR (kept up to date)

**Reference video:** a frame every 2 s was studied (0 s … 56 s). Only its look is used: none of its
words, brands, numbers or names. "Seen at" gives the second(s) where the reference shows the technique.

**Evidence:**
- *test*: a test that renders it and checks pixels.
- *acceptance*: the cue-by-cue acceptance run (`scripts/acceptance.py`, `docs/acceptance/`), where
  the effect appeared with the right text at the right second.

| # | Technique | Seen at | After M2 (cue engine) | After M3 (look) | Evidence |
|---|---|---|---|---|---|
| 1 | Editorial magazine typography | 0, 2, 16, 44 s | ALREADY WORKING (headline, kinetic title); magazine cover in M3 | ALREADY WORKING: magazine cover for a well-filled opening (masthead = your first title word) | acceptance (third): hook |
| 2 | Minimalist subtitle cards | all (captions) | PARTIALLY WORKING: cream caption cards, no punctuation; serif word-by-word look in M3 | ALREADY WORKING: serif (Playfair Display) cream cards, words faint until said, no end punctuation | test (`editorial_card` reveal); acceptance: captions |
| 3 | Kinetic typography | 0, 44, 46 s | ALREADY WORKING | unchanged | acceptance: keyword (DISIPLINA on its word) |
| 4 | Floating screenshot collage | 14 s | ALREADY WORKING (your screenshots, matched by file name) | unchanged | acceptance: screenshot |
| 5 | Animated mosaic / grid | 30 s | PARTIALLY WORKING: picture grid; grid of text tiles in M3 | ALREADY WORKING: also a mosaic of word tiles for a recap ("Kaya tandaan…") | acceptance (third): recap |
| 6 | Search bar typing | 6, 10, 26 s | ALREADY WORKING (types the query you say) | unchanged | acceptance: search |
| 7 | Floating UI panels / checklists | 8, 18, 40, 48 s | ALREADY WORKING: checklist, UI panel; timeline card and chat cards in M3 | ALREADY WORKING: also a timeline card (a routine) and comment cards ("Comment mo…") | acceptance (third): timeline, comment |
| 8 | Black-and-white transitions | 28 s | ALREADY WORKING ("dati … ngayon": B&W, then colour) | ALREADY WORKING: plus the past words struck out, the new ones landing on "ngayon" | acceptance (third): before_after, strike |
| 9 | Animated countdown | 22 s | ALREADY WORKING (3, 2, 1 on the spoken numbers) | unchanged | acceptance: count |
| 10 | Storyboard document | 36, 38 s | ALREADY WORKING (the scene names you say) | unchanged | acceptance: storyboard |
| 11 | Punch-in zoom | 6, 46 s | ALREADY WORKING | unchanged | test; key-word punch-ins in the acceptance project |
| 12 | Zoom-out / reframing | 12 s | ALREADY WORKING | unchanged | test (`zoomClip.from`) |
| 13 | Text pop-in | 0, 46 s | ALREADY WORKING | unchanged | test |
| 14 | Text scaling | 46 s | ALREADY WORKING | unchanged | test |
| 15 | Picture-in-picture | 20, 24 s | PARTIALLY WORKING: floating rounded PiP of your clip; a PiP card with a label in M3 | ALREADY WORKING: a label pill under the floating PiP with the words it goes with | test (`label-pill` under the PiP box) |
| 16 | Floating phone mockup | — | ALREADY WORKING (template, your screenshot) | ALREADY WORKING: "… sa phone / app ko" shows your matching screenshot in the phone | acceptance (third): phone |
| 17 | App logo overlays | 4 s | ALREADY WORKING: a tile per platform you name, from your logo file, else the name as text | unchanged | acceptance: platforms |
| 18 | Dark vignette | 28 s | ALREADY WORKING | unchanged | test; acceptance: before_after |
| 19 | Background dimming | 16, 22, 28 s | ALREADY WORKING (under every big card) | unchanged | test; acceptance project |
| 20 | Drop shadows | all cards | ALREADY WORKING | unchanged | test |
| 21 | Rounded graphic cards | all cards | ALREADY WORKING | unchanged | test |
| 22 | Screenshot montage | — | ALREADY WORKING (template) | unchanged | test |
| 23 | Keyword highlighting | 46 s, captions | ALREADY WORKING | unchanged | test; acceptance |
| 24 | Colour palette graphics | — | ALREADY WORKING (colours from your picture) | unchanged | test |
| 25 | Animated checklist progression | 48–52 s | ALREADY WORKING (ticks on each spoken item) | unchanged | acceptance: checklist |
| 26 | Multi-layer compositions | 16, 30 s | ALREADY WORKING (video, dim, vignette, cards, captions in one render) | unchanged | acceptance render |
| 27 | Smooth overlay entrance / exit | all | ALREADY WORKING | unchanged | test |
| 28 | Social profile overlays | 56 s | ALREADY WORKING (your handle as said, your photo) | unchanged | acceptance: handle, follow |
| 29 | Vertical 9:16 framing | all | ALREADY WORKING | unchanged | test |
| 30 | Speech-synchronized graphics | all | ALREADY WORKING (cue engine: each graphic starts on its word) | unchanged | acceptance: 12 of 12 cues |

M3 acceptance: `docs/acceptance/m3/` (the base, second and a third transcript that has a routine,
a comment call, a recap and "sa phone").

**Still NOT VERIFIED:**
- real Taglish speech: the acceptance run uses a word-timestamp fixture
- your base video: it was not attached; a 29.8 s stand-in made with FFmpeg is used
- Windows and the desktop app on your PC
- how "premium" the result looks to a viewer
