# AI pictures, video clips and voice-over (WanGP)

The AI edit can add **AI pictures, short AI video clips and AI voice-over lines**, made on
your own PC with **[WanGP](https://github.com/deepbeepmeep/Wan2GP)** by DeepBeepMeep.
WanGP is installed separately and has its own license (the *WanGP Community License*).
Read it in WanGP's `LICENSE.txt`. This editor does not include WanGP or any model, and it
**never downloads models**: you choose and download them in WanGP yourself, after reading
each model's license.

The AI only plans pictures, clips or voice-over when your instructions ask for them, or when
they clearly help. If WanGP is not set up, nothing is generated: the edit still finishes, and
the summary says what was not done.

## Setup (one time)

1. Install WanGP by following its own guide (`docs/INSTALLATION.md` in WanGP). It normally
   runs in a conda environment called `wan2gp`.
2. In WanGP, download the models you want and try them there first.
3. For each **quality tier** you want (Draft, Low, Mid, High) and each kind (pictures,
   video clips, voice-over):
   1. In WanGP, choose the model and the settings.
   2. Click **Export Settings** and save the file in this project's `generation_templates`
      folder.
   3. Put that file name in the tier's `"template"` in `generation.json`.

   The editor copies `generation.example.json` to `generation.json` the first time it runs.
   In the app, click **AI models**, then **Edit settings file**.
4. In the app, open **AI models**:
   1. Enter the **WanGP folder** (where `wgp.py` is).
   2. Enter **WanGP's Python**. To find it, open a terminal, run `conda activate wan2gp`,
      then `where python`.
   3. Click **Save**, then **Check WanGP models**.
5. Click **Test everything** once (see "Testing" below).

From the command line:

```
python editor.py gen-config --wangp-folder C:\WanGP --wangp-python C:\Users\you\miniconda3\envs\wan2gp\python.exe
python editor.py gen-status --check-wangp      # what is installed, per tier
python editor.py hardware                      # GPU, VRAM, RAM, free disk
python editor.py benchmark                     # test every installed tier (one at a time)
python editor.py compare --type image --prompt "A cozy sari-sari store at golden hour"
python editor.py set-tier --type image --default Mid     # or --pin High, --unpin, --clear-default
python editor.py ai-edit inbox\a.mp4 -i "..." --max-generation-minutes 15 --max-ai-clips 3
```

## Quality tiers

Each tier in `generation.json` has the following fields:

- **`template`**: the WanGP settings file you exported. The tier uses exactly that model and
  those settings. Model names are never written into the editor: they come from your file
  and from WanGP's own model list.
- **`overrides`** (optional): may only change `resolution` (e.g. `"480x832"`),
  `num_inference_steps`, `video_length` (frames, or seconds like `"3s"`) and
  `duration_seconds`. Any other key is ignored, and the app tells you so.
- **`label`**: a plain name shown in the app.
- **`vram_gb`**: your own estimate of the VRAM the tier needs, if you know it. It is shown
  as "your estimate", and left out when unknown.

For each tier, the **AI models** window shows the following:

- Whether it is **installed**. WanGP itself is asked: its model list and its own
  "is this downloaded" check.
  - A tier whose model is missing or only partly downloaded is **disabled**. The window
    says why and links to the model's official page and to WanGP's model documentation,
    with a reminder to read the license.
  - A tier with no settings file is disabled with setup steps.
- The **average generation time on this PC**, measured from real runs. Test runs are not
  counted in it.
- The **VRAM** estimate, if known, and the **test result**: passed, failed, or out of GPU
  memory, with the time and the peak VRAM when it could be measured.

The window never says that a tier or model is "better". It shows measured facts. Use
**Compare** and judge the outputs yourself.

## Testing (benchmark)

**Test** runs one short job per installed tier, **one GPU job at a time**. Only one GPU job
runs at a time across the whole editor, so an edit and a test never share the GPU. For each
tier it records the following:

- success, failure, or **out of GPU memory** (WanGP's error message is checked for the usual
  CUDA out-of-memory wording);
- the time;
- the **peak VRAM**, when `nvidia-smi` is available. It is sampled about twice a second for
  the whole GPU, so it is approximate and includes anything else using the GPU.

Results are saved in `work\generation\benchmarks.json`. They are keyed by the **PC's
hardware**, the **WanGP version**, the **model** and the **tier's settings**. A new GPU, a
WanGP update or a changed settings file therefore shows the tier as "not tested" again
instead of reusing an old result.

## Compare

**Compare** runs the same prompt and seed on every installed tier, one after the other. It
shows the results side by side with the time each one took. Click **Use as default** under
the one you like. That choice is saved per kind (pictures, clips, voice-over) in
`generation.json`. The outputs are kept in `work\generation\compare\<date>`.

## How Auto mode picks a tier

1. **Final tier:**
   1. a **pinned** tier, if you set one ("Auto mode uses: Always …");
   2. otherwise **your default**, chosen after Compare;
   3. otherwise the **highest tier that passed its test** on this PC;
   4. otherwise the highest installed tier.
2. **Preview:** in Auto mode, every AI item is first made with the **Draft** tier (or the
   lowest installed one). Then the whole set is made again with the final tier. With Auto
   mode off, only the draft is made, so you can review the plan. The final tier is used when
   you click Apply.
3. **Fallback:** if a job fails, runs out of GPU memory or takes longer than
   `job_timeout_minutes`, the next tier down is tried. The summary says so, e.g. *"AI video
   clip at 0:12: the High tier out of GPU memory, so the Mid tier was used instead."*
4. **Per-video limits:** these are set in the AI panel ("AI pictures & clips") and default
   to the `limits` in `generation.json`. If the app cannot read the generation settings,
   the boxes are not shown and the limits in `generation.json` apply.
   - **Max generation time:** all generation for one video stops after this many minutes.
     Unfinished items keep their draft, or are left out, and the summary says which.
   - **Max AI clips:** extra pictures or clips are not made, and the summary says how many.

WanGP is started once per edit, test or compare, and stopped afterwards. A job that is
cancelled or runs out of time is stopped. If WanGP does not stop within a minute, it is
closed.

## Hardware

The GPU name and VRAM are detected with `nvidia-smi`. Without it, Windows' own video
adapter list is used; Windows often reports the wrong VRAM for cards over 4 GB, so that
figure is shown only when it can be trusted. System RAM and free disk space are detected
too.

Detection runs when the app starts and when you click **Detect again**. If the hardware
changed since last time, the app says so and asks you to test again. The notice stays until
a test has run on the new hardware. If detection fails,
the app still works, and the window shows what could not be detected.

## Files

```
generation.json                your settings (tiers, defaults, pins, limits, WanGP paths)
generation_templates/          the WanGP settings files you exported
work/generation/hardware.json  the last hardware profile
work/generation/models.json    the last model list read from WanGP
work/generation/benchmarks.json  test results per hardware / WanGP version / model / settings
work/generation/runs.jsonl     every generation run (used for the average times)
work/generation/gpu.lock       makes sure only one GPU job runs at a time
```

## What was and was not verified

**Verified** (in the cloud test machine, with no GPU and without real WanGP):

- **Python tests:** 24 tests in `tests/test_generation.py`, run against a stand-in for
  WanGP (`tests/fake_wangp`) that copies WanGP's documented Python API (`shared/api.py`:
  `init`, `list_model_metadata`, `get_model_availability`, `submit_task`, events,
  `result`, `cancel`), and a fake `nvidia-smi`. They cover:
  - the hardware profile, including the fallback when `nvidia-smi` is missing;
  - the bridge, including WanGP's console output kept away from the JSON messages;
  - models that are not installed are refused and never sent to WanGP, so nothing is
    downloaded;
  - the GPU lock;
  - settings, overrides and tier statuses;
  - the tier choice and the fallback order;
  - benchmark: success, out of memory, time, VRAM, and results keyed per
    hardware / version / model;
  - Compare, and the AI edit with draft then final passes, fallbacks, the per-video limits
    and the summary lines;
  - that the edit still finishes when WanGP is not set up.
- **The desktop app's main process with the real engine** (Vitest, fake WanGP):
  - reading the tiers and WanGP's installed check;
  - saving the WanGP folder, the default and the pinned tier;
  - a test run with its live events, Compare with the same prompt and seed, and Stop;
  - after Stop, no WanGP process is left behind;
  - a whole edit through the app's job queue that makes an AI picture with the per-video
    limits (the second clip is not made, and the summary says so).
- **Desktop UI tests** (Playwright, using the engine's real output against the fake WanGP):
  - the AI models window: hardware, tier statuses, disabled tiers with reasons and license
    notes;
  - Compare side by side with times, "Use as default", pinning, and the test run with Stop;
  - the per-video limits being sent;
  - the draft and final steps;
  - the hardware-change notice, in the main window and in AI models;
  - a test that keeps running (with its log and Stop) when AI models is closed and reopened;
  - an AI video clip shown in the live preview;
  - that the window never uses the words "better" or "best".

**NOT verified:**

- **Real WanGP** was not run. It needs an NVIDIA GPU, which the cloud machine does not have.
  The integration follows WanGP 18.11's documentation and source code (read, not run).
  A different WanGP version may behave differently.
- **Real benchmarking:** real generation times, real out-of-memory behaviour and real peak
  VRAM could not be measured. All times in the tests come from the stand-in.
- **Output quality** of any model or tier was not checked.
- **GPU detection on real hardware:** `nvidia-smi` and the Windows video adapter list were
  only tested with fake output.
- **Windows:** stopping WanGP's process tree (`taskkill /T`) and the GPU lock file on
  Windows. Note: if the engine itself does not stop within 90 seconds of Stop, the app
  kills it. On Windows that also closes WanGP. On macOS/Linux only the engine is killed.
  This was not seen in tests, because the engine closes WanGP itself within 60 seconds.
- **The voice-over models:** whether a given WanGP audio model accepts the
  `duration_seconds` setting, and how its output sounds.
- **A real AI provider** asking for clips: the plan format was tested with faked AI answers.
