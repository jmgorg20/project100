# The Android app · Ang Android app

The Android app is the web app in a **Trusted Web Activity** (TWA): a small Android app that opens
`https://YOUR_DOMAIN/app/` full screen in Chrome, without the address bar. There is no second
codebase: every change to the web app is in the Android app at once, without a Play Store update.
Uploads, sign-in, the offline page and "Add to Home Screen" work as on the website.

*Ang Android app ay ang web app din, pero naka-full screen sa loob ng Chrome. Walang hiwalay na code:
bawat update sa website ay nasa app agad, hindi na kailangang mag-update sa Play Store.*

The app is made with **Bubblewrap**, Google's own tool for TWAs; the settings come from this
repository (`scripts/android_twa.py` reads the web app's manifest, so the name, colours and icons match).

## What you need · Kailangan

- The web app live on HTTPS (see [going-live.md](going-live.md)). Check
  `https://YOUR_DOMAIN/app/manifest.webmanifest` opens.
- Node.js 20+ and Java (Bubblewrap offers to download the JDK 17 and the Android command-line tools
  itself the first time: answer **Yes**). Windows, macOS or Linux.
- A Google Play developer account (one-time US$25), for the Play Store.

## Make the app · Gawin ang app (Windows: PowerShell)

```
npm install -g @bubblewrap/cli
python scripts/android_twa.py --host app.example.com --package com.yourname.autoedit
cd android
bubblewrap update --manifest=./twa-manifest.json --skipVersionUpgrade   # makes the Android project from the settings
bubblewrap build                                                         # asks for the signing key's passwords
```

- `--host`: the domain the web app is on (no `https://`, no path).
- `--package`: the app id on the Play Store. **It can never change** after the first upload.
- The first `bubblewrap build` creates the **signing key** `android/android.keystore` (it asks for a
  password and your name). **Back it up** (password manager, offline copy): without it you cannot
  publish updates. It is never committed (`android/.gitignore`).
- The result: `app-release-signed.apk` (to install on your own phone) and `app-release-bundle.aab`
  (for the Play Store).

*`--package` ay hindi na mapapalitan. I-backup ang `android.keystore` at ang password nito; kung
mawala, hindi ka na makakapag-update ng app.*

## Connect the app and the site · Ikonekta ang app at ang site

Android shows the app full screen only when the site says the app is its own (Digital Asset Links).
The service serves that file when these are set in `deploy/.env`:

```
SERVICE_ANDROID_PACKAGE=com.yourname.autoedit
SERVICE_ANDROID_CERT_SHA256=AB:CD:...:EF            # comma-separated if more than one
```

The fingerprints:
- your own key: `bubblewrap fingerprint list` (or `keytool -list -v -keystore android.keystore`, "SHA256");
- **Play App Signing** (on by default): Play Console → your app → Test and release → App integrity →
  "App signing key certificate" → SHA-256. Put **both** in the setting (yours for the APK you install
  yourself, Google's for the copy people download from the Play Store).

Restart the API and check `https://YOUR_DOMAIN/.well-known/assetlinks.json` shows them. If the app
opens with an address bar at the top, the fingerprints do not match: compare them again.

## Selling plans: Google Play rules · Pagbebenta ng plan

Google Play requires its own billing for digital goods sold *inside* apps from the Play Store (with
exceptions that change by country and year). So the Android app **does not sell plans**: it opens
`/app/?source=android`, and then the Billing card shows the plan and the minutes, with "Plans cannot
be bought in the Android app", and no buy or "manage payment" buttons or links. Plans bought on the
website work in the app (same account). The website in Chrome on the same phone still sells plans
(the app mode is remembered only inside the app).

Before you publish, read Google Play's current "Payments" policy (and, if you want to sell in the
app, Google Play Billing or the "user choice billing" programme in your countries): adding Play
Billing would be a new step, not in this repository.

*Bawal magbenta ng plan sa loob ng Android app nang hindi gumagamit ng Google Play Billing. Kaya sa
app, makikita lang ang plan at minutes; sa website pa rin bumibili.*

## Publish on the Play Store · I-publish

1. Play Console → Create app (name, language, free, "App").
2. Fill in: privacy policy URL (`https://YOUR_DOMAIN/app/privacy.html`), app access (a test account
   with an invite code for Google's reviewers), ads (none), content rating, target audience (18+ or
   the ages you allow), data safety (what [privacy.html](../web/public/privacy.html) says: email,
   videos, payment info by Paddle, not shared for ads, can be deleted), and the AI-generated content
   declaration if asked.
3. Store listing: icon 512×512 (`web/public/icons/icon-512.png`), a feature graphic 1024×500,
   at least 2 phone screenshots.
4. Test and release → **Internal testing** first: upload `app-release-bundle.aab`, add your testers,
   install from the link. Check: full screen (no address bar), sign-in, upload from the gallery,
   download, back button, the Billing card shows no buying.
5. Then Closed testing (Play requires 12+ testers for 14 days on new personal accounts) and Production.

## Updates · Mga update

- Web app changes: nothing to do, the app shows the new web app at once.
- A new app version is needed only for a new icon, name, colours or Bubblewrap / Android updates:
  `python scripts/android_twa.py ... --version-code 2 --version-name 1.0.1`, then `bubblewrap update`
  and `bubblewrap build` again, and upload the new `.aab`. The version code must go up every time.

## iPhone · iOS

See [ios.md](ios.md).

## What was and was not tested · Ano ang nasubukan

- **Tested here:** the Digital Asset Links file (and its settings checks), the Bubblewrap settings
  made from the web manifest (host, package, version, icons, start page inside the app's scope), and
  in the browser: the app mode hides buying (across pages in the app), the website in another tab of
  the same browser still sells plans.
- **Not tested:** building the APK / AAB (the Android SDK and Google's download servers are not
  reachable from where this was built), the app on a real phone, the Play Store review, and Play's
  payment rules for your country (read them). Bubblewrap's `twa-manifest.json` fields were written
  for the current Bubblewrap; if `bubblewrap update` complains about a field, run
  `bubblewrap init --manifest=https://YOUR_DOMAIN/app/manifest.webmanifest` instead, use
  `/app/?source=android` as the start URL and the same package id, and continue from "build".
