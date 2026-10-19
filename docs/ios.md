# iPhone and iPad (notes only) · Para sa iPhone

There is no iOS app in this repository, by choice. iPhone users use the web app in Safari, and can
put it on the home screen. These notes say why, and what an App Store app would take later.

*Walang iOS app sa ngayon. Sa iPhone, buksan ang website sa Safari at i-"Add to Home Screen".*

## Today: the web app on the home screen · Sa ngayon

1. Open `https://YOUR_DOMAIN/app/` in **Safari**.
2. Share button → **Add to Home Screen** → Add.
3. It opens full screen with its own icon, like an app (the web manifest and the icons are already
   there). Sign-in stays, uploads from Photos or Files work, results download to Files / Photos.

Limits on iOS (Apple's, not the app's): the "Install" button the web app shows on Android does not
appear (people must use Add to Home Screen; a short how-to on your website helps); a long upload stops if
the person leaves Safari for a while (picking the same video again continues where it stopped).

## Later: an App Store app? · Sa hinaharap

| | |
|---|---|
| **A wrapper of the website** (like the Android app) | Apple refuses apps that are "just a website" (App Review Guideline 4.2, minimum functionality). It needs real iPhone features: e.g. picking many videos from Photos natively, background upload, share-sheet "Edit with AutoEdit", notifications when a video is ready. |
| **How** | Capacitor (capacitorjs.com) around the same web app (`web/`), plus small native plugins for those features. Needs a Mac with Xcode and an Apple Developer account (US$99 / year). |
| **Selling plans** | Digital subscriptions bought inside an iOS app must use Apple's In-App Purchase (Guideline 3.1.1), with Apple's fee; links to buy on the website are allowed only in some countries and cases ("reader" apps, the US and EU rules) — check the current rules. The simple path, as on Android: the iOS app does not sell plans (the web app's `source=android` mode can be reused as `source=ios`). |
| **Privacy** | App Store "privacy nutrition label" from the same facts as the privacy page; account deletion inside the app (already there: Account → Delete account). |
| **Cost** | Apple Developer US$99 / year, a Mac, and review time for each release. |

**Recommendation:** stay with the home-screen web app until iPhone users ask for an App Store app,
then build the Capacitor app with the native features above (that is what gets it approved).

*Payo: home-screen web app muna. Kung marami nang humihingi ng App Store app, gumawa gamit ang
Capacitor na may tunay na iPhone features, kasi tinatanggihan ng Apple ang app na website lang.*

## Not tested · Hindi nasubukan

Nothing here was run on an iPhone; the web app's tests use Chromium at phone sizes, not Safari.
