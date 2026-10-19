"""The Android app (a Trusted Web Activity): the Digital Asset Links file the service serves, the
settings checks, and the Bubblewrap settings made from the web app's manifest."""

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from scripts import android_twa
from service.api import create_app
from service.settings import Settings, SettingsError

FP = ":".join(["AB"] * 32)


def test_asset_links(settings):
    with TestClient(create_app(settings)) as http:
        assert http.get("/.well-known/assetlinks.json").status_code == 404           # no app set up
    s = dataclasses.replace(settings, android_package="com.example.autoedit", android_cert_sha256=[FP])
    with TestClient(create_app(s)) as http:
        r = http.get("/.well-known/assetlinks.json")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.json() == [{"relation": ["delegate_permission/common.handle_all_urls"],
                         "target": {"namespace": "android_app", "package_name": "com.example.autoedit",
                                    "sha256_cert_fingerprints": [FP]}}]


def test_android_settings_are_checked():
    base = {"SERVICE_ENV": "development"}
    s = Settings.from_env({**base, "SERVICE_ANDROID_PACKAGE": "com.example.autoedit",
                           "SERVICE_ANDROID_CERT_SHA256": f"{FP}, {':'.join(['01'] * 32)}"})
    assert s.android_cert_sha256 == [FP, ":".join(["01"] * 32)]
    for bad in ({"SERVICE_ANDROID_PACKAGE": "autoedit", "SERVICE_ANDROID_CERT_SHA256": FP},
                {"SERVICE_ANDROID_PACKAGE": "com.example.autoedit", "SERVICE_ANDROID_CERT_SHA256": "ab:cd"},
                {"SERVICE_ANDROID_PACKAGE": "com.example.autoedit"}):
        with pytest.raises(SettingsError):
            Settings.from_env({**base, **bad})


def test_bubblewrap_settings_follow_the_web_manifest(tmp_path):
    data = android_twa.build("App.Example.com", "com.example.autoedit", version_code=7, version_name="1.2.0")
    manifest = json.loads(android_twa.WEB_MANIFEST.read_text(encoding="utf-8"))
    assert data["host"] == "app.example.com" and data["packageId"] == "com.example.autoedit"
    assert data["startUrl"] == "/app/?source=android" and data["fullScopeUrl"] == "https://app.example.com/app/"
    assert data["themeColor"] == manifest["theme_color"] and data["name"] == manifest["name"]
    assert data["iconUrl"] == "https://app.example.com/app/icons/icon-512.png"
    assert data["maskableIconUrl"] == "https://app.example.com/app/icons/maskable-512.png"
    assert data["appVersionCode"] == 7 and data["signingKey"]["path"] == "./android.keystore"
    for host, package in (("https://app.example.com", "com.example.a"), ("app.example.com/app", "com.example.a"),
                          ("localhost", "com.example.a"), ("app.example.com", "autoedit"),
                          ("app.example.com", "com.1bad.name")):
        with pytest.raises(ValueError):
            android_twa.build(host, package)
    out = tmp_path / "twa-manifest.json"
    assert android_twa.main(["--host", "app.example.com", "--package", "com.example.autoedit", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["webManifestUrl"] == "https://app.example.com/app/manifest.webmanifest"


def test_the_start_page_is_in_the_app_scope():
    manifest = json.loads(android_twa.WEB_MANIFEST.read_text(encoding="utf-8"))
    assert android_twa.START.startswith(manifest["scope"]) and manifest["display"] == "standalone"
