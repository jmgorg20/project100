# The AI edit (Phase 2)

You describe the finished video in plain Taglish or English. The editor transcribes it,
asks a language model for a **plan**, builds the timeline (a [project file](project-format.md))
with its normal editing steps, and, in Auto mode, renders it straight away.

```
python editor.py ai-edit inbox\talk.mp4 -i "Mabilis na edit, malaking yellow captions, ipakita ang gcash_receipt.png pag sinabi kong resibo" --photos assets\overlays\gcash_receipt.png
python editor.py ai-edit inbox\a.mp4 inbox\b.mp4 inbox\c.mp4 -i "Same style for all"     # batch
python editor.py estimate inbox\talk.mp4 --provider anthropic                               # cost first
```

## Steps

1. **Transcript.** Groq Whisper (or `--transcribe-with local`). Saved in `work\cache`,
   keyed by the video's content, so the same video is never transcribed (or paid for) twice,
   even if renamed.
2. **Plan.** The model gets the instruction, the transcript with word times, the video
   length, the photo file names, and the preset edit as a starting point. It answers with a
   small JSON plan ([`autoedit/ai_plan.schema.json`](../autoedit/ai_plan.schema.json)):
   caption style, size and position, words to highlight, pacing, zoom, colour, extra cuts
   (retakes, unwanted parts), extra zooms, colour changes for parts, pop-in photos,
   effects and transitions (flash, whip, shake, glitch, dip), and B-roll items (what to
   show, search words, a look, and a source: see [broll.md](broll.md)). It is also told
   which B-roll sources you have (your folder's file-name words, stock keys, WanGP).
   It can also attach effects to the speaker's hand, face or body (`tracked_effects`: a glow, sparks,
   an aura or energy rings: see [tracking.md](tracking.md)) when tracking is set up.
   Anything it cannot do goes in `notes` and is shown to you as "Not done: ...".
   Plans saved by older versions (without effects or B-roll looks) still load.
3. **Checks.** Every plan is checked against the schema, then for sense (times inside the
   video, photos that exist, not cutting everything), then by actually building the
   project (which is checked against the project schema). If anything fails, the model is
   asked **once more**, with the problems listed. If the second answer also fails, or the
   provider cannot be reached (no key, no internet, rate limit), the editor uses the
   **preset edit** and says so at the top of the summary ("Heads up: ...").
4. **Project.** Built by the same tested steps as `python editor.py edit` (cuts, zooms,
   captions, photos). B-roll is found or made first (your folder, then free stock, then AI).
   The app shows each stage as it arrives.
5. **Summary.** A plain-language list of what was actually done, read from the finished
   project (not from what the model claimed): new length and number of jump cuts, removed
   parts with reasons, zooms, caption style and size, colour, photos and when they appear,
   photos not used, and what could not be done.
6. **Render** (Auto mode) with the normal renderer. With Auto mode off, nothing is
   rendered until you accept the changes you want.

Each run saves a project file and a plan file next to the finished video
(`<name>_edited.project.json` / `.plan.json` from the command line, `<name>_ai...` from the
app). The plan file holds the instruction, plan, summary and cost, and is what "Change this edit" (a
follow-up) and "Apply" (after review) start from.

## Transcription (Taglish) · Ang pagsulat ng sinabi

- Groq Whisper `whisper-large-v3` (the most accurate; `turbo` is faster but misses more Taglish),
  `language: tl`. With it goes a short hint: your own words (vocabulary.json), words from your
  instruction and your photo / file names (`search_results.png` → search, results), and a Taglish
  line with words Whisper often mishears ("tatlo", "hinanap"...). `transcription: taglish_hint:
  false` in config.yaml turns the Taglish line off.
- **Taglish post-correction** (on the real Windows run the hint was not enough: "Tatlo" came out
  "Tatyo"). After transcription, a word that is exactly one letter off a known word becomes that
  word: Tagalog / English numbers (`Tatyo` → `Tatlo`, `tatlumpong` → `tatlumpung`), words creators
  say on camera (`hinanat` → `hinanap`, `disipina` → `disiplina`) and the words of your
  instruction and file names. Everyday words (`wala`, `sana`, `dito`...), plurals and words of
  under 5 letters (4 for numbers) are never touched. "What the AI did" lists every change
  (`Fixed 2 misheard Taglish word(s): 'Tatyo' -> 'Tatlo', ...`). `transcription: taglish_fix: false`
  turns it off. The countdown also accepts a number word one letter off when the next word is a
  number ("Tatyo dalawa isa" → 3, 2, 1).
- **Real Whisper words have no punctuation** (Groq's word timestamps): the cue engine then finds
  sentences by pauses and capital letters (never cutting after "sa", "ng", "ang"...), a title after
  "Una" / "Pangalawa" without caps or a colon, list items in the sentence after "checklist ..."
  split at verb forms (mag-post, sagutin, i-check) or pauses. Tested on the words of the real
  Windows run (`tests/data/realclip/`, evidence in `docs/acceptance/realclip/a/`).
- **Fix the words before the edit.** In the app: Settings → *Let me fix the words before the AI
  edit*; after you press Edit with AI you see what was heard, line by line, correct it ("Tatyo" →
  "Tatlo"), then the edit starts with your words (captions and graphics use them). Command line:
  `python editor.py transcribe me.mp4 --output me.transcript.json`, fix the file, then
  `python editor.py ai-edit me.mp4 --transcript me.transcript.json`.
- **Captions without punctuation** (default): no `, . ! ? ; :` or quotes on screen; `i-check`,
  `mag-post`, `it's`, `3,600` and `1.5` stay. The words themselves are not changed. Settings →
  *Caption punctuation* (keep / remove), `--caption-punctuation keep`, `captions: punctuation:` in
  config.yaml, the caption editor's *Show punctuation* switch (whole project), or the API's
  `"caption_punctuation"`.
- **Not verified:** how much the hint improves real Taglish speech (there is no real speech or
  Groq key on the test machine; the request that is sent is tested).

## Providers

| | Groq (default) | Anthropic (optional) |
|---|---|---|
| Key | free at console.groq.com | your own, paid |
| Model (default) | `openai/gpt-oss-120b` | `claude-opus-5-5` |
| How JSON is enforced | JSON mode; the schema is in the prompt; then our checks | structured outputs (`output_config.format` with the schema), effort `medium`; then our checks |
| Library | `requests` | official `anthropic` SDK, with Anthropic's server-side refusal fallback (`fallbacks: "default"`) |

Change the models in the app's Settings or in `config.yaml` under `ai:`.

## When the engine seems stuck · Kapag parang natigil ang editor

Every step of an edit is logged, and a stuck step is never just waited on:

- **`work/logs/edit.log`:** every step after the AI call, with the time it started and ended (each
  line written to disk at once). The step that never ended is the last `start` without its `end`.
  Time spent waiting for the AI is marked (`waiting for the AI ...`).
- **A heartbeat:** the engine tells the app it is alive every 5 s.
- **A time limit per step:** a planning step that runs longer than 60 s (`edit: step_timeout`;
  waiting for the AI does not count, it has its own limits; transcribing, AI pictures, formats and
  rendering report their own progress) is stuck. The app shows *"The editor got stuck in the step
  ... Steps: ...edit.log  Where it was stuck: ...engine-stack.log"* and the engine stops (exit code 3).
- **`work/logs/engine-stack.log`:** the Python stacks of every thread when a step is stuck, and every
  90 s while an edit runs (Python's `faulthandler`, which works even when Python itself is blocked):
  the last lines of the main thread are the exact line it was on.
- **Nothing can wait on the app:** the engine writes to the app on its own threads, so a busy window
  never stops the edit (before this, nothing after the plan happened until the app read again); a
  line the app cannot handle never stops it reading; no FFmpeg / ffprobe / helper shares the app's
  stdin pipe, and on Windows the "cancel" pipe is only read when something is in it.

## When the AI is slow or rate limited · Kapag mabagal o limitado ang AI

No AI request can hold the edit up:

- **A time limit per request:** 90 s (`ai: timeout`), then it is asked again, up to 2 times
  (`ai: retries`), after a timeout, a lost connection or a server error.
- **Rate limits (429):** Groq's free tier allows a number of tokens per minute. When it says
  "wait", the app waits the time Groq asks for (when it is under a minute) and says so on screen:
  *Planning the editorial scenes - Groq is rate limiting the requests (429): trying again in 8 s
  (1 of 2)*. A longer wait is not waited out.
- **Small requests:** the scene plan asks only for the scenes your words have not already set
  (none at all when every scene is set), with only the beats your files allow, short scene text, a
  short instruction, and a right-sized answer (on the user's clip: ~2,800 tokens counted against
  the per-minute limit instead of ~9,700). When it would still not fit `ai: groq_tpm` (8000), it is
  sent in parts; if Groq still says it is too large, each part is halved.
- **The rules take over:** when the AI cannot be asked, the scenes are planned by the editorial
  rules (what you say still sets the graphics), and *What the AI did* says why, with the log's path.
- **The log:** `work/logs/ai-plan.log`: every request with the time, its size, how many answer
  tokens it allows, the status (200, 429, 413, a timeout...), how long it took and the tokens
  used. Never your key or your words.

## Cost estimate

`estimate` and the app show an estimate before running; the summary shows the cost of the
run from the provider's own token counts. Prices come from `config.yaml` (`ai: prices:`).
The Anthropic prices were taken from Anthropic's current price list; **the Groq prices
could not be checked against groq.com when this was written** (the site was not reachable),
so check them and edit `config.yaml` if they differ. A saved transcript or plan costs $0.

## Keys

The app stores keys encrypted with the operating system (Electron `safeStorage`; DPAPI on
Windows) and passes them to the engine only as environment variables. They are never
written to logs, shown again, or sent to the window. If encryption is not available, the
app refuses to store the key and asks you to use `.env` instead. The command line reads
`GROQ_API_KEY` / `ANTHROPIC_API_KEY` from the environment or `.env`.

## What was and was not verified

**Slow / rate-limited AI (Linux, a local stand-in for Groq's API):** a request that never answers is
given up on after the limit and 2 retries; a 429 is waited out and said on screen; a long wait is
not; a too-large request is split; cancel works while waiting; the app's own command
(`editor.py ai-edit`, plan given, Groq hanging) finishes with the rules' scene plan and the reason.
**NOT VERIFIED:** Windows, and the real Groq API (no key here): the free-tier figure (8000 tokens a
minute) and Groq's exact 429 / 413 wording are taken from Groq's documented error format and should
be checked against your account's limits page.


**Verified (Linux, automated tests):** plan checks and their messages; the exact request
each provider gets (with the HTTP library or SDK replaced by a fake: URL, model, JSON mode
or structured outputs, refusal fallback, key only in the header); error messages for bad
keys, unknown models, rate limits and refusals; one retry with the problems listed; the
preset fallback after two failures or a provider error, and when a plan breaks the edit;
transcript and plan caches; cost maths; the whole flow from plan to rendered video with
FFmpeg, including Auto mode off, follow-ups, and batches where one video fails.

**NOT verified:** any real call to Groq or Anthropic (no network access to them here), so
not how well either model plans real Taglish edits; real Filipino speech; the Groq model
name and prices; Windows.
