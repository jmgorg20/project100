# Auto Video Editor (TikTok / Facebook Reels)

Drop in a raw vertical talking video (Filipino / Taglish) and get back a finished
**1080x1920 MP4**: pauses and "uhm"s cut out, jump-cut zooms, colour grade, louder
and even audio, and word-by-word captions. It runs on your own Windows PC with free
tools only (Python + FFmpeg). No paid editor, no subscription.

```
python editor.py edit inbox\myvideo.mp4 --style 2
```

What it does, in order:

1. **Transcribes** the speech with word timings (Groq Whisper online, or offline on your PC).
2. **Cuts pauses** longer than 0.25 s and **filler words** (ah, uh, um, uhm, eh), keeping a
   little air (80 ms) around each cut so words don't sound clipped.
3. **Jump-cut zoom**: alternates between normal and 115% every few seconds.
4. Makes it **1080x1920, 30 fps, H.264 + AAC** (crops to fill the screen, never stretches).
5. **Loudness** evened out to about -14 LUFS (what TikTok/Reels like).
6. **Colour grade** (natural_clean by default).
7. **Captions** burned in, in one of 13 styles, kept away from the app's buttons.
8. Optional **intro/outro**, **logo watermark**, **pop-in images** when you say a keyword,
   **sound effects**, and **screen recording** layouts.

Every edit is also saved as a **project file** (`output\myvideo_edited.project.json`): the
whole timeline (cuts, zooms, captions, overlays, sounds) as tracks and clips. You can
re-render it, and the desktop editor that is being built will open it so you can change
anything by hand. See [Project files](#project-files).

> **Desktop app status:** this is Phase 0 of turning the editor into a CapCut-style desktop
> app (live preview, multi-track timeline, AI first edit). Phase 0 adds the project file and
> its renderer. The app itself is not built yet; everything below is the command line.

---

## What was tested, and what was not

Be aware of what has and has not been checked:

**Tested (automatically, on Linux with FFmpeg 6.1, Python 3.13):**
- 164 automated tests pass (`python -m pytest`): cutting maths, timestamp remapping,
  keyword rules, settings, edit plans, watch mode, and all 13 caption styles. Each style
  is turned into a subtitle file and drawn by FFmpeg/libass to check that text appears.
- **Project files:** the schema and ~30 kinds of mistakes (each with a clear message);
  saving and loading; and rendering synthetic projects checked **frame by frame** by
  colour: clip edges land on the exact frame, reordered clips, gaps, stills, pop-in
  photos, colour grade ranges, export sizes, volume/mute/fades and sound placement.
- **The auto edit through a project gives the same video as before.** Rendering the
  synthetic edit through its project and through the original renderer gives the same
  frames and the same sound (checked in the tests; without an intro/outro the decoded
  frames and audio samples were identical). All 13 caption styles produce exactly the same
  subtitle file as before.
- `render`, `frame`, `validate`, JSON progress, and **cancel** (FFmpeg is stopped, no
  half-written file is left).
- Full edits of a **synthetic test video** (colour bars + beeps standing in for speech, with a
  fake transcript): output is 1080x1920, 30 fps, H.264, with an AAC audio track, and sound
  and picture have the same length. Layouts tested: face, split screen, picture-in-picture,
  screen only. Pop-in overlays, plan zooms/grades, watermark, intro and sound effects tested too.
- Preview pictures of all 13 caption styles were rendered and looked at
  (see `docs/caption_styles.png`).
- The Groq request was checked with a fake server (correct address, model, language
  `tl`, word timestamps, key not printed).

**Not tested:**
- **Real Filipino/Taglish speech.** How well Whisper hears Taglish, and how natural the cuts
  feel on a real voice, has not been checked. Try a short video first and adjust
  `silence_threshold` / `padding` in `config.yaml` to taste.
- **Real Groq API calls** (no API key was available).
- **faster-whisper (local transcription)**: it was not installed or run here.
- **Windows.** The code avoids the usual Windows problems (long command lines, `C:` drive
  paths in FFmpeg filters), but it was not run on a Windows PC. Speed on your PC is unknown.
  Expect the export to take roughly as long as the video, or longer on older laptops.
- FFmpeg 7/8 (Windows builds are usually newer than the 6.1 used for testing). The editor
  switches to the newer way of passing the filter file automatically.
- The **desktop app** does not exist yet (later phases), so nothing about the app, its
  preview, the installer, the AI timeline (Groq/Anthropic LLM calls) or preview-vs-render
  matching has been tested.
- Cancelling on **Windows** (the app stops FFmpeg through the editor) was only tested on
  Linux.

If something breaks, the error message says what went wrong. The temporary files are
kept in `work\` so you can see what happened.

---

## Setup on Windows (step by step, one time)

### 1. Install Python

1. Go to <https://www.python.org/downloads/> and download Python **3.11 or newer**.
2. Run the installer. **On the first screen, tick "Add python.exe to PATH"**, then
   click *Install Now*.

### 2. Install FFmpeg

1. Click the Start menu, type `powershell`, and open **Windows PowerShell**.
2. Type this and press Enter:
   ```
   winget install Gyan.FFmpeg
   ```
3. **Close PowerShell and open it again** (so it finds the new program).
4. Check that it works: type `ffmpeg -version` and press Enter. You should see a version number.

> No `winget`? Download the "full" build from <https://www.gyan.dev/ffmpeg/builds/>,
> unzip it to `C:\ffmpeg`, and add `C:\ffmpeg\bin` to your PATH
> (Start → "Edit the system environment variables" → Environment Variables → Path → New).

### 3. Get this project

On the GitHub page click **Code → Download ZIP**, unzip it, e.g. to
`C:\Users\<you>\Videos\autoeditor`. (Or `git clone` it if you use Git.)

### 4. Open a terminal in the project folder

Open the project folder in File Explorer, click the address bar, type `powershell` and press
Enter. A blue window opens already inside the folder.

### 5. Install the Python parts

```
python -m pip install -r requirements.txt
```

(This also installs the offline transcriber `faster-whisper`, which is a big download. If
you will only use Groq, you can skip it: `python -m pip install PyYAML requests Pillow jsonschema pytest`.)

### 6. Add your Groq API key (for online transcription)

1. Make a free account at <https://console.groq.com> and create a key at
   <https://console.groq.com/keys>.
2. In the project folder, copy `.env.example` and rename the copy to **`.env`**
   (Windows may warn about changing the extension; click Yes).
3. Open `.env` with Notepad and replace `your_groq_api_key_here` with your key:
   ```
   GROQ_API_KEY=gsk_...your key...
   ```
4. Save. **Never share this file.** It is in `.gitignore`, so Git will not upload it.

Prefer fully offline? Skip this step and set `provider: local` in `config.yaml`
(slower; the first run downloads the model, about 1.5 GB for "medium").

### 7. Check everything

```
python editor.py check
```

You should see `OK` lines for FFmpeg and your key.

---

## Everyday use

### Edit one video

```
python editor.py edit inbox\myvideo.mp4
python editor.py edit inbox\myvideo.mp4 --style 11 --grade warm
python editor.py edit inbox\myvideo.mp4 --style bold_caps --preset relaxed
```

The finished video goes to `output\myvideo_edited.mp4`.

| Option | What it does |
|---|---|
| `--style N` | caption style, number 1-13 or name (see below) |
| `--grade NAME` | `natural_clean`, `none`, `warm`, `black_and_white`, `orange_teal`, `high_contrast` |
| `--lang tl` | speech language (default `tl`, Tagalog/Filipino; Taglish works) |
| `--preset fast` | pacing preset from `config.yaml` (`fast` or `relaxed`, or add your own) |
| `--provider groq` / `local` | online or offline transcription |
| `--transcript file.json` | skip transcription and use this transcript |
| `--plan plan.json` | extra instructions for this video (see "Edit plan") |
| `--screen rec.mp4` | add a screen recording (see "Screen recordings") |
| `--layout split/pip/screen` | screen recording layout |
| `--silence 0.4` | cut pauses longer than 0.4 s (overrides the preset) |
| `--zoom 1.2` | punch-in zoom amount (overrides the preset) |
| `--no-captions` | no captions |
| `--output path.mp4` | save somewhere else |
| `--keep-work` | keep the temporary files in `work\` |

### Re-render or check a project file

```
python editor.py render output\myvideo_edited.project.json
python editor.py render output\myvideo_edited.project.json --height 1280 --crf 23
python editor.py frame output\myvideo_edited.project.json --time 12.5
python editor.py validate output\myvideo_edited.project.json
python editor.py edit inbox\myvideo.mp4 --project-only
```

`render` saves `myvideo_edited_render.mp4` next to the project (`--height 1280` = 720x1280,
`960` = 540x960). `frame` saves the exact picture at 12.5 s as a PNG. `--project-only`
makes the project without rendering. See [Project files](#project-files).

### Fix the transcript and re-run (no new transcription)

Every edit saves `output\myvideo.transcript.json`. Open it in Notepad to fix a misheard word,
or wrap a word in stars like `"*GitHub*"` to force it to be a highlighted keyword. Then:

```
python editor.py edit inbox\myvideo.mp4 --transcript output\myvideo.transcript.json
```

Only change the words, not the numbers. The format is:

```json
{"language": "tl", "words": [
  {"word": "Kumusta", "start": 0.50, "end": 0.90},
  {"word": "*GitHub*", "start": 5.50, "end": 6.00}
]}
```

### Watch a folder (automatic)

```
python editor.py watch
```

Leave it running. Every video you drop into `inbox\` is edited with your `config.yaml`
settings, and the original is moved to `inbox\done\` (or `inbox\failed\` if something went
wrong; fix the problem and move it back into `inbox\`). Stop with **Ctrl+C**.

### See all caption styles

```
python editor.py styles
python editor.py styles --video inbox\myvideo.mp4     # use a frame from your video
```

Pictures are saved in `output\style_previews\`. The red areas show where TikTok/Reels put
their buttons and text; captions stay out of them.

---

## Caption styles

![All 13 caption styles](docs/caption_styles.png)

| # | Name | Look |
|---|---|---|
| 1 | `classic` | white text, black outline, lower area |
| 2 | `yellow_pop` | spoken word turns yellow (default) |
| 3 | `boxed` | white text on a black box |
| 4 | `bold_caps` | UPPERCASE bold, spoken word red |
| 5 | `minimal` | small lowercase text, light shadow |
| 6 | `neon_green` | spoken word neon green, thick outline |
| 7 | `one_word` | one big word at a time, centred |
| 8 | `pink_highlight` | spoken word on a pink box |
| 9 | `thick_outline` | yellow text, very thick black outline |
| 10 | `top_banner` | near the top, white with soft shadow |
| 11 | `center_keyword` | big centred text, 1-3 words per line, KEY WORDS in yellow |
| 12 | `typewriter` | words appear as you say them |
| 13 | `pop_word` | each word pops in as you say it |

Captions show at most 2 lines, sit above the bottom 20% of the screen, and keep away from
the right edge (like/comment/share buttons).

**Font:** the project includes the free *Inter* font (`assets/fonts`, SIL Open Font License),
which has all Filipino letters (ñ, Ñ). To use Arial instead, change `font_regular`,
`font_bold` and `font_heavy` in `config.yaml` to `Arial`, `Arial`, `Arial Black`. You can also
drop any `.ttf`/`.otf` font into `assets/fonts` and use its name.

**Add your own style:** open `autoedit/styles.py`, copy one line in the `STYLES` list, give
it number 14 and a new name, and change the values (colours, size, position...). Every setting
is explained at the top of that file. Then run `python editor.py styles` to see it.

### Keyword highlighting

Some styles colour **key words** (yellow by default): `boxed`, `one_word`, `top_banner`,
`center_keyword`, `typewriter`, `pop_word`. Styles that colour the spoken word instead
(e.g. `yellow_pop`) don't. Key words are picked by free rules, no AI service:

- **manual:** words written as `*word*` in the transcript (always highlighted)
- **numbers** (500, 3, twenty...), **prices** (500 pesos, ₱1,299, $5)
- **English/tech words** (app, online, laptop, GCash, GitHub, AI...) and borrowed words
- **long words** (more than 7 letters)

At most 1 key word is coloured in every 4 words, so it stays readable. Switch rules on/off,
change the colour, or add your own always-highlight words under `highlight:` in `config.yaml`.

---

## Pop-in overlays (B-roll)

Put images (screenshots, notifications, documents: `.png`, `.jpg`) or short clips (`.mp4`)
in `assets\overlays\`. Then list keywords in `triggers.yaml`:

```yaml
triggers:
  - keyword: github
    file: github.png        # assets/overlays/github.png
    duration: 2.5
    position: top           # top or center
  - keyword: [gcash, g-cash]
    file: gcash_notification.png
```

When you say the keyword, the picture pops in (grows in and fades in), stays for the
duration, and fades out. Only one overlay shows at a time, and it moves out of the way if
your caption style is at the top or in the centre.

### Sound effects (optional, off by default)

No sounds are included. Put your own royalty-free files at `assets\sfx\pop.wav` (plays when an
overlay pops in) and `assets\sfx\whoosh.wav` (plays on zoom cuts), then set
`sfx: enabled: true` in `config.yaml`. Change `volume` to taste.

### Intro, outro, watermark

In `config.yaml` under `branding:` set `intro` / `outro` to an image or short clip, and
`watermark` to a logo `.png` (transparent background works best). Leave them empty to skip.

---

## Screen recordings

```
python editor.py edit inbox\face.mp4 --screen inbox\recording.mp4                 # split
python editor.py edit inbox\face.mp4 --screen inbox\recording.mp4 --layout pip    # face in corner
python editor.py edit inbox\recording.mp4 --layout screen                        # screen only
```

- **split** (default with `--screen`): screen recording in the top 60% (over a blurred copy of
  itself), your face in the bottom 40%, captions on the line between them.
- **pip**: screen recording fills the frame, your face in a small box at the top left.
- **screen**: only the screen recording, centred over a blurred copy of itself. The sound and
  transcript come from the recording.

The face video provides the sound and the transcript; the two videos are assumed to start
at the same moment. Cuts and zooms apply to both.

---

## Edit plan (optional, per video)

Without a plan the editor uses the preset rules only. With `--plan plan.json` you can add
specific instructions. **All times are seconds in the RAW video** (before cutting), so you can
read them off your phone's player.

```json
{
  "style": "center_keyword",
  "grade": "warm",
  "auto_zoom": true,
  "cuts":     [{"start": 41.0, "end": 47.5}],
  "zooms":    [{"start": 12.0, "end": 15.5, "amount": 1.3}],
  "grades":   [{"start": 30.0, "end": 36.0, "grade": "black_and_white"}],
  "overlays": [{"file": "receipt.png", "at": 20.0, "duration": 3, "position": "center"}]
}
```

| Key | Meaning |
|---|---|
| `style`, `grade` | change the caption style / grade for this video (a `--style`/`--grade` flag still wins) |
| `auto_zoom` | `false` turns off the automatic alternating zoom |
| `cuts` | extra parts to remove (a retake, a mistake) |
| `zooms` | zoom in by `amount` (1.0-3.0) during these times |
| `grades` | a different grade during these times |
| `overlays` | show a file from `assets\overlays\` at time `at` |

Every key is optional. An example is in `examples\plan.json`.

---

## Settings (`config.yaml`)

Open `config.yaml` in Notepad. Every line has a note. The main ones:

- `style`, `grade`, `preset`, `language`: your defaults
- `transcription: provider:` `groq` or `local`
- `presets: fast:` pause length to cut (`silence_threshold`), filler removal, zoom amount and
  how often the zoom changes
- `silence: padding:` air kept around cuts; `noise_db:` what counts as quiet (noisy room?
  try `-30`)
- `fillers:` the filler words to remove
- `audio: loudness:` target loudness (-14)
- `output: crf:` quality (lower = better/bigger), `encoder_speed:` `veryfast` for quicker exports

---

## Project files

`python editor.py edit` saves the edit as `output\<name>_edited.project.json` (turn this off
with `save_project: false` under `output:` in `config.yaml`). It is plain JSON: the media
files, then **tracks** (main video, photos, effects, captions, voice-over, music, sound
effects) holding **clips** with a start time and length. The desktop app will edit this
file, and `python editor.py render` turns any project into the final MP4.

The full description, timing rules and known limits are in
[`docs/project-format.md`](docs/project-format.md); an example is
[`examples/project.json`](examples/project.json).

## Troubleshooting

| Message | Fix |
|---|---|
| `Could not find 'ffmpeg'` | Do step 2 again, then close and reopen the terminal. |
| `FFmpeg was built without libass` | Install the full build: `winget install Gyan.FFmpeg`. |
| `GROQ_API_KEY is missing` | Do step 6. The file must be named exactly `.env` (not `.env.txt`). |
| `Groq rejected the API key (401)` | Copy the key again from console.groq.com. |
| `hit the free usage limit (429)` | Wait a while, or use `provider: local`. |
| `has no audio track` | The video has no sound; record again with the microphone on. |
| Words get clipped | Raise `silence: padding:` to `0.12`, or `silence_threshold` to `0.4`. |
| Pauses not cut in a noisy room | Set `noise_db: -30`. |
| Captions in the wrong font | Check the font names in `config.yaml`; run `python editor.py styles`. |
| `These media files are missing` | A file used by the project was moved or deleted. Put it back, or fix its `path` in the project file. |
| `The project file has problems` | Run `python editor.py validate <file>`: each problem says which clip and what is wrong. |

## For the curious: project layout

```
editor.py            the commands (edit, watch, styles, check)
config.yaml          your settings
triggers.yaml        keyword -> overlay list
autoedit/
  pipeline.py        the edit, step by step
  cuts.py            silence/filler cutting maths and timestamp remapping
  captions.py        builds the .ass caption file
  styles.py          the 13 caption styles (add yours here)
  highlight.py       keyword rules
  project.py         the project file: checks, loading, saving
  project.schema.json  the project file rules (shared with the desktop app)
  project_render.py  renders a project with one FFmpeg command
  render.py          FFmpeg building blocks (and the original renderer, used by the tests)
  progress.py        progress messages (text, or JSON lines for the app)
  transcribe.py      Groq and faster-whisper
  overlays.py, plan.py, grades.py, watch.py, previews.py ...
tests/               automated tests (run: python -m pytest)
inbox/ output/ work/ your videos (never uploaded to Git)
```

Running the tests: `python -m pytest` (needs FFmpeg; takes about two minutes).

The Inter font is © The Inter Project Authors, SIL Open Font License 1.1
(`assets/fonts/LICENSE-Inter.txt`).
