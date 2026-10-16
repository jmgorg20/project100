# Auto Video Editor: desktop app

Electron + React + TypeScript. The window talks to the main process through a small,
typed bridge (`src/shared/api.ts`); the main process runs the Python engine
(`python ../editor.py --json --stdin-control ...`) and turns its JSON lines into live updates.

```
src/main/      Electron main process: engine runner, job queue, settings, encrypted keys, history
src/preload/   the bridge (self-contained: sandboxed preloads cannot load local modules)
src/renderer/  the window: preview player, AI panel, review list, dialogs
  editor/      the timeline editor (Timeline, Inspector, MediaBin, BrollPanel, ExportDialog, shortcuts)
src/shared/edit.ts   timeline edit operations (pure; every result is a valid project)
src/shared/brollEdit.ts   B-roll clips (the same results as autoedit/broll.py)
src/shared/    types and pure logic used by both sides (job events, history, plan review)
tests/unit/    Vitest: logic, the engine runner, and main.ts with the real engine
tests/ui/      Playwright: the window in Chromium with a stand-in bridge (?mock=1)
```

## Run it (Windows)

1. Do the engine setup in the main [README](../README.md) first (Python, FFmpeg,
   `python -m pip install -r requirements.txt`).
2. Install Node.js 22 LTS from <https://nodejs.org> (tick "Add to PATH").
3. In PowerShell, in this `desktop` folder:
   ```
   npm install
   npm start
   ```
   `npm install` downloads Electron (about 100 MB). `npm start` builds and opens the app.
4. Open **Settings**, paste your Groq key, and click **Check the editor engine**.
   If Python is not found, set its path there (e.g. `C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe`).

AI pictures, clips and voice-over use [WanGP](https://github.com/deepbeepmeep/Wan2GP)
(installed separately, its own license). Set it up in **AI models**; see
[docs/generation.md](../docs/generation.md). The app works without it.

**B-roll (optional):** in **Settings**, choose your own B-roll folder, and paste a free
Pexels and/or Pixabay key if you want free stock pictures and clips (both keys are encrypted
like the Groq key). See [docs/broll.md](../docs/broll.md).

There is no installer yet (that is Phase 4).

## Tests

```
npm test                 # unit tests (needs Python + FFmpeg for the engine tests)
npm run test:ui          # builds the window and runs the Playwright tests
npm run typecheck
```

The UI tests make their fixtures with the real engine (`tests/ui/make_fixtures.py`), and
save screenshots to `tests/ui/screenshots/`. They run in open-source Chromium, which
cannot play H.264, so the fixtures include WebM copies of the test videos; the real app
(Electron) plays MP4 directly.

`.npmrc` sets `legacy-peer-deps`: npm 10 crashes ("reading 'edgesOut'") while resolving
Vitest's optional peers; every peer this app needs is listed in `package.json`.

After changing caption styles in the engine, refresh the preview's copy:
`python ../editor.py ui-data > src/shared/engine-data.json` (a test checks it).
