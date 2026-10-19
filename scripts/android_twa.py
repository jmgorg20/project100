"""Write android/twa-manifest.json: the settings Bubblewrap (Google's tool for Android apps that
show a website, "Trusted Web Activity") uses to make the AutoEdit Android app. The name, colours and
icons come from the web app's manifest, so the app and the website always match.

    python scripts/android_twa.py --host app.example.com --package com.example.autoedit
    cd android && bubblewrap build          (see docs/android.md)

Run it again with a higher --version-code for each Play Store update. The signing key itself is
never in the repository (android/.gitignore).
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_MANIFEST = ROOT / "web" / "public" / "manifest.webmanifest"
OUT = ROOT / "android" / "twa-manifest.json"
PACKAGE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+")
HOST = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
START = "/app/?source=android"          # the web app hides buying plans in the Android app (docs/android.md)


def _icon(manifest, purpose):
    icons = [i for i in manifest.get("icons", []) if purpose in str(i.get("purpose", "any")).split()]
    icons.sort(key=lambda i: int(str(i.get("sizes", "0x0")).split("x")[0]), reverse=True)
    return icons[0]["src"] if icons else None


def build(host, package, version_code=1, version_name="1.0.0", key_path="./android.keystore", key_alias="autoedit",
          manifest=None):
    host = host.strip().lower()
    if host.startswith(("http://", "https://")) or "/" in host or not HOST.fullmatch(host):
        raise ValueError("--host is the domain only, e.g. app.example.com (HTTPS is required and implied)")
    if not PACKAGE.fullmatch(package) or len(package) > 150:
        raise ValueError("--package looks like com.yourname.autoedit (letters, digits, dots)")
    if not 1 <= int(version_code) <= 2_100_000_000:
        raise ValueError("--version-code is a whole number that goes up with every Play Store update")
    m = manifest if manifest is not None else json.loads(WEB_MANIFEST.read_text(encoding="utf-8"))
    any_icon, maskable = _icon(m, "any"), _icon(m, "maskable")
    if not any_icon:
        raise ValueError("the web manifest has no icon")
    base = f"https://{host}"
    return {
        "packageId": package,
        "host": host,
        "name": m["name"],
        "launcherName": m.get("short_name", m["name"])[:12],
        "display": m.get("display", "standalone"),
        "orientation": m.get("orientation", "portrait"),
        "themeColor": m["theme_color"],
        "themeColorDark": m["theme_color"],
        "navigationColor": m["background_color"],
        "navigationColorDark": m["background_color"],
        "navigationDividerColor": m["background_color"],
        "navigationDividerColorDark": m["background_color"],
        "backgroundColor": m["background_color"],
        "enableNotifications": False,
        "startUrl": START,
        "iconUrl": base + any_icon,
        "maskableIconUrl": base + maskable if maskable else None,
        "webManifestUrl": base + "/app/manifest.webmanifest",
        "fullScopeUrl": base + m.get("scope", "/app/"),
        "splashScreenFadeOutDuration": 300,
        "signingKey": {"path": key_path, "alias": key_alias},
        "appVersionCode": int(version_code),
        "appVersionName": version_name,
        "appVersion": version_name,
        "shortcuts": [],
        "generatorApp": "autoedit-scripts",
        "fallbackType": "customtabs",
        "features": {},
        "alphaDependencies": {"enabled": False},
        "enableSiteSettingsShortcut": True,
        "isChromeOSOnly": False,
        "isMetaQuest": False,
        "minSdkVersion": 21,
        "fingerprints": [],
        "additionalTrustedOrigins": [],
        "retainedBundles": [],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--host", required=True, help="the domain the web app is on, e.g. app.example.com")
    p.add_argument("--package", required=True, help="the app id, e.g. com.yourname.autoedit (never change it later)")
    p.add_argument("--version-code", type=int, default=1)
    p.add_argument("--version-name", default="1.0.0")
    p.add_argument("--key-path", default="./android.keystore")
    p.add_argument("--key-alias", default="autoedit")
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args(argv)
    try:
        data = build(a.host, a.package, a.version_code, a.version_name, a.key_path, a.key_alias)
    except ValueError as exc:
        p.error(str(exc))
    Path(a.out).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{a.out} written for https://{data['host']}{data['startUrl']} ({data['packageId']}, "
          f"version {data['appVersionName']} / {data['appVersionCode']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
