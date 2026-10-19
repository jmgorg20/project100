# The web app (phone and PC) · Ang web app

Your users open **https://API_DOMAIN/app/** on a phone or a PC: sign up, upload a video, pick a
style or write what they want, and get the edited video back. It is a PWA: on a phone it can be
installed like an app (Android Chrome: "Install app" / "Add to Home screen"; iPhone Safari: Share →
"Add to Home Screen").

*Bubuksan ng user ang https://API_DOMAIN/app/ sa phone o PC: mag-sign up, mag-upload, pumili ng
style o isulat ang gusto, at makukuha ang na-edit na video. Puwedeng i-install sa phone na parang app.*

It uses the same service and engine as everyone else (one codebase): it talks to the API with the
user's sign-in (docs/accounts.md), and the editing rules for captions and the storyboard are the
desktop app's own (`desktop/src/shared`), not a copy.

## What a user can do · Ano ang magagawa ng user

1. **Sign up / sign in** (email + password, or Google; invite code while sign-up is invite-only).
2. **New video:** choose the video from the gallery or files, optional photos, a **style** (the 7
   presets), a **layout** (automatic or one of the formats), **instructions** in English or Taglish
   (for example "Mabilis, big captions, tanggalin ang pauses"), and optionally a **project**.
3. The upload goes **in pieces** (8 MB by default, `SERVICE_CHUNK_MB`). A lost connection is retried by itself; **Pause**, or
   closing the app, keeps what arrived: picking the same file again continues from there.
4. **Live progress** while it edits (the page updates by itself and reconnects after a drop).
5. **The result:** play it in the page, **download** it, see the automatic checks, and how long it
   is kept ("Kept for 3 days more…"); **Delete now** removes it at once.
6. **Storyboard:** the video as scenes (hook, points, call to action) with their words; tap a
   scene's words to change them.
7. **Fix captions:** change any caption line, then **Save and make the video again**.
8. **Export:** 1080×1920, 720×1280 or 540×960; quality (standard, high, smaller, quick draft); 24-60
   frames per second.
9. **My videos:** the history, by project.
10. **Account:** language (**English / Taglish**, remembered on the account), this month's minutes,
    signed-in devices, password, two-step sign-in, the workspace's members and invitations, download
    my data, delete my account; terms and privacy pages (placeholders until step 7.5).

## For the owner · Para sa may-ari

- Nothing extra to run: the API image builds the web app (`deploy/Dockerfile.api`, a Node stage)
  and serves it at `/app/`; `/` sends visitors there. Same site as the API, so the sign-in cookie
  never goes to another site and no CORS setting is needed for it.
- Development: `cd web && npm ci && npm run build`, then `python editor.py serve` (it serves
  `web/dist`). Or `npx vite` in `web/` with the API on port 8787 (it forwards /v1 and /files).
- **Offline:** the app's own files are kept on the phone (a service worker), so it opens without
  internet and says it is offline. Videos and account data are never stored by it.
- **Updates:** a new version shows "A new version is ready · Reload".
- Security: the page may load only its own files (Content-Security-Policy; the captcha's site is
  added when a captcha is set), cannot be put in another site's frame, and every change it makes
  carries the session's CSRF token. Preview links play in the page and count only the bytes sent;
  only **Download** starts the "deleted 24 hours after download" clock.

*Walang dagdag na patatakbuhin: kasama na ang web app sa API image at nasa /app/. Offline: bubukas pa
rin ang app pero hindi ito nagtatabi ng video o account data sa phone.*

## Tests · Mga test

`cd web && npm ci && npx playwright install chromium && npm test` builds the app and runs it in
Chromium at phone sizes (Pixel 7, a small 360 px phone) and a desktop size, against **the real API**
(`web/tests/server.py`: SQLite, emails to files) with **a real worker agent** running the stand-in
engine:

- sign up → the email link → signed in; upload in pieces (several 1 MB pieces) → style, photos,
  instructions → live progress → result (preview served inline, download link, checks, expiry) →
  storyboard → fix a caption → export at 720×1280 "smaller" (the exact project and options sent are
  checked) → history → switch to Taglish → delete → sign out and in again (Taglish follows the
  account);
- the network dropping in the middle of an upload; pause, reload the app, pick the file again: it
  continues from where it stopped (not from zero); a fake "video" is rejected with the reason;
- every screen at 360 px and phone size: no sideways scrolling, every button and field at least
  44 px tall, the bottom navigation; no console errors (nothing blocked by the security policy);
- installable: the manifest and icons; with the network off, the app still opens from the phone and
  shows the offline notice; every English text has a Taglish version.

## Not verified · Hindi pa nasubukan

- **Real phones** (Android Chrome, iPhone Safari), installing to the home screen, and real mobile
  networks. The tests use Chromium with phone screen sizes and touch.
- **Playing the video in the page:** the test browser (Playwright's Chromium) cannot decode H.264,
  so the test checks that the player asked for the video and got an inline MP4; real Chrome, Safari
  and Android play it.
- The real engine behind the web app (the browser tests use the stand-in engine; the real engine is
  covered by the container test through the API).
- Google sign-in and the captcha widget in a real browser (both need real accounts).
