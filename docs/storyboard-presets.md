# Storyboard and presets · Storyboard at mga preset

## The storyboard · Ang storyboard

After an AI edit, press **Storyboard · Mga eksena** (or **Storyboard** in the timeline editor's top
bar). The edit is shown as scenes, before you render.

*Pagkatapos ng AI edit, pindutin ang **Storyboard**. Makikita ang edit bilang mga eksena bago i-render.*

Each scene card shows:

| | |
|---|---|
| **Purpose** | Hook, Point, Proof / numbers, Question, Call to action, Ending (simple rules: the first scene is the hook; numbers and prices are proof; "follow / comment / bili / link" in the last scene is a call to action) |
| **Time and length** | where it starts and how long it is (▶ plays from there) |
| **Source** | your video file(s) and any B-roll in it |
| **Words** | the captions of the scene |
| **Graphics** | the pop-up graphics in it |
| **Transition** | how it starts: cut, flash, whip, punch-in, wipe |
| **Music / SFX** | the music under it and how many sounds |
| **Colour** | the colour grade (warm, teal & orange…) |

What you can do:

- **Approve all & render** (*Aprubahan lahat*): marks the storyboard approved and opens Export.
  You can render without ever opening the timeline.
- **Regenerate** (*Gawing iba*): another look for this scene's graphics (simple rules, no AI cost),
  or **with AI** (uses your AI key). A scene with no graphics gets some, only inside that scene.
  Other scenes are not touched.
- **Replace footage** (*Palitan ang footage*): choose a clip or picture; it replaces the scene's
  B-roll, or is put over the whole scene if it has none.
- **Edit words** (*Baguhin ang salita*): type the scene's words; they are spread over its captions.
- **Lock** (*I-lock*): the scene's captions, graphics, B-roll, effects and sounds are locked: the
  editor will not move or change them and Regenerate skips them. Your main video clips stay
  editable, so you can still cut. **Unlock** to change it again.

**Everything is also on the timeline.** The storyboard is a view of the project, not a copy:
locking a scene sets 🔒 on its clips, editing words edits the caption clips. Press **Timeline** to
see them. Once you edit a scene, the scene boundaries are kept (so they do not shift while you
work); they are saved in the project (`meta.storyboard`).

Command line:

```
python editor.py storyboard my.project.json
python editor.py storyboard-edit my.project.json --scene 2 --lock
python editor.py storyboard-edit my.project.json --scene 2 --text "Una, mag-budget ng 500 kada linggo."
python editor.py storyboard-edit my.project.json --scene s3 --regenerate [--provider groq]
python editor.py render my.project.json
```

## Presets · Mga preset

A preset is a ready-made look for the whole edit. Pick one in the AI panel (**Preset · Handang
istilo**) or `--preset NAME`. Your own format, graphics choice and words still win over the
preset.

| Preset | Format | Graphics | Captions | Colour | Pacing | Music | Sounds |
|---|---|---|---|---|---|---|---|
| **Viral TikTok** | from your words | promoter, up to 3 per 10 s | pop word, bigger | high contrast | fast | upbeat | whoosh/pop |
| **Cinematic Storytelling** | from your words | luxury, 1 per 10 s | minimal, smaller | teal & orange | relaxed, no zooms | cinematic | – |
| **Premium UGC Ad** | from your words | promoter, 2 per 10 s | boxed | natural | fast | upbeat | whoosh/pop |
| **Podcast Clips** | from your words | minimal, 1 per 10 s | yellow pop | natural | relaxed | – | – |
| **Faceless Automation** | Voice-over with B-roll | minimal | bold caps | natural | fast | calm | – |
| **Calm Documentary** | from your words | calm documentary | classic | warm | relaxed, no zooms | calm | – |
| **Meme** | from your words | meme, up to 4 per 10 s | thick outline, bigger | high contrast | fast | – | whoosh/pop |
| **PREMIUM EDITORIAL VIRAL** | from your words | premium editorial, one beat per 2–4 s scene | cream editorial cards | natural | fast, smooth zooms | upbeat (quiet) | – |

- **The preset's captions and colour win over the AI's choice** (the AI still decides the cuts,
  zooms, photos and B-roll). You can change them afterwards on the timeline.
- **Faceless Automation** uses only the B-roll you give it ("approved assets"): no stock search,
  no AI-made clips. Give it a voice-over and B-roll files.
- **PREMIUM EDITORIAL VIRAL** plans the video scene by scene with only your own screenshots,
  photos, clips and logo (no stock, no AI-made clips). Guide:
  [premium-editorial.md](premium-editorial.md).
- **Music:** no music is bundled (copyright). Put music you are allowed to use in
  `assets/music` (`music: folder:` in config.yaml). A file whose name contains the mood
  (upbeat / happy / summer, cinematic / epic, calm / chill / lofi / piano) is picked first. It
  plays under the whole video and gets quieter while you speak. Without a music folder, the
  summary says no music was added.
- **Sounds** (whoosh, pop) are made on your PC by FFmpeg; they go on the flash/whip and popping
  graphics, at most 3 in 10 seconds.

### Your own presets · Sariling preset
Presets are plain JSON files. Copy one from `autoedit/presets/` into the `presets/` folder (next
to `editor.py`; `presets_folder:` in config.yaml), change it and give it a new `id` (the same as
the file name). A file with the same id as a built-in preset replaces it. `python editor.py
presets` lists them all and checks each file (`autoedit/presets/preset.schema.json`). The app's
menu shows the built-in presets.

## What was and was not tested · Ano ang nasubukan
- **Tested (automatically, Linux):** the eight presets and your own (valid, replaced, bad ones
  refused with the reason); what each preset changes in the settings and the plan; music picked
  by mood, repeated and faded; sounds spaced out; an AI edit with a preset end to end (stand-in
  AI); the storyboard's scenes, lock, words and regenerate in the engine **and the app, checked to
  give the same result**; the storyboard and preset menu in the app (browser build, mock engine).
- **Not tested:** real Taglish speech (the scene purposes are simple word rules), Windows and
  Electron, and how the presets look on your videos. These are sensible starting points, not
  "Hollywood quality".
