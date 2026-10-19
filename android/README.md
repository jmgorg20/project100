# Android app (Trusted Web Activity)

This folder holds the Bubblewrap settings for the Android app (`twa-manifest.json`, made by
`python scripts/android_twa.py --host ... --package ...`) and, after `bubblewrap update` /
`bubblewrap build`, the generated Android project, which is not committed. The signing key
(`android.keystore`) must never be committed: back it up somewhere safe.

Step by step: [docs/android.md](../docs/android.md). iPhone: [docs/ios.md](../docs/ios.md).
