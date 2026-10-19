"""Write LICENSES.md: the licences of everything AutoEdit uses or ships (Python packages, the npm
packages of the desktop and web apps, fonts, and the programs in the container images).

    python scripts/licenses.py            # rewrites LICENSES.md from the installed Python packages and the lockfiles

Run it after changing dependencies (with the service's and worker's requirements installed), check
the "Look at" list at the top, and commit the result.
"""

import json
import re
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = {"requirements.txt": "engine / desktop", "requirements-service.txt": "service (API)",
                "requirements-worker.txt": "worker"}
LOCKFILES = {"desktop/package-lock.json": "desktop app", "web/package-lock.json": "web app"}
# licences that need a closer look before you distribute (source offer, notices, network use)
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|MPL|EPL|CDDL|SSPL|EUPL|OSL|CC-BY-SA|Commons Clause)", re.I)
TEST_ONLY = {"pytest", "httpx", "iniconfig", "pluggy", "packaging", "pygments"}

BUNDLED = [
    ("FFmpeg (Debian package, in both container images)", "LGPL-2.1+ / GPL-2.0+ (the Debian build enables GPL parts "
     "such as libx264)", "Used as a separate program, not linked. If you give the container images to others, offer "
     "the FFmpeg source (Debian's source package) with them. Running it on your own servers is not distribution."),
    ("Node.js (official image, in the worker image)", "MIT (plus bundled third-party notices)", ""),
    ("Chromium via playwright-core (worker image, renders graphics)", "BSD-3-Clause and many third-party licences "
     "(see chrome://credits)", "Downloaded at image build time from Playwright's CDN, not stored in this repository."),
    ("Python (Debian package)", "PSF-2.0", ""),
    ("Inter font (assets/fonts, desktop/graphics/fonts)", "OFL-1.1", "Licence text: assets/fonts/LICENSE-Inter.txt."),
    ("Anton, Archivo Black, Bangers, Bebas Neue, Caveat, JetBrains Mono, Oswald, Playfair Display "
     "(desktop/graphics/fonts)", "OFL-1.1", "Licence texts: desktop/graphics/fonts/OFL-*.txt. The fonts may be "
     "embedded in videos; they may not be sold on their own."),
]
NOT_SHIPPED = [
    ("AI model weights", "None are in this repository or the images (scripts/check_no_weights.py checks it in CI). "
     "Transcription and planning use hosted services (Groq, Anthropic) under their terms. The desktop app downloads "
     "the optional MediaPipe tracking models (Apache-2.0) and faster-whisper models (MIT) only when the person asks."),
    ("WanGP (optional local video generation, desktop)", "Installed separately by the person; each of its models has "
     "its own licence, shown in the app before use."),
]


def _license_of(dist):
    m = dist.metadata
    expr = m.get("License-Expression")
    if expr:
        return expr
    text = (m.get("License") or "").strip()
    if text and len(text) < 60 and "\n" not in text:
        return text
    classifiers = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c not in ("OSI Approved",)]
    if classifiers:
        return " / ".join(classifiers)
    return text.splitlines()[0][:60] if text else "UNKNOWN"


def _requirement_names(path):
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"([A-Za-z0-9_.-]+)", line)
        if m and not line.startswith("-"):
            names.append(m.group(1))
    return names


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def python_packages():
    """{name: {"version", "license", "used_by": set}} for the requirements and what they pull in."""
    found, missing = {}, set()

    def visit(name, used_by):
        key = _norm(name)
        if key in found:
            found[key]["used_by"].add(used_by)
            return
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.add(name)
            return
        found[key] = {"name": dist.metadata["Name"], "version": dist.version, "license": _license_of(dist),
                      "used_by": {used_by}}
        for req in dist.requires or []:
            try:
                r = Requirement(req)
            except InvalidRequirement:
                continue
            if r.marker and not r.marker.evaluate({"extra": ""}):
                continue                                  # an extra, or another platform / Python version
            visit(r.name, used_by)

    for req_file, used_by in REQUIREMENTS.items():
        path = ROOT / req_file
        if path.exists():
            for name in _requirement_names(path):
                visit(name, used_by)
    return found, missing


def npm_packages():
    rows = {}
    for lock, used_by in LOCKFILES.items():
        path = ROOT / lock
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, info in (data.get("packages") or {}).items():
            if not key:
                continue
            name = key.split("node_modules/")[-1]
            entry = rows.setdefault((name, info.get("version", "?")), {"license": info.get("license") or "UNKNOWN",
                                                                       "used_by": set(), "dev": True})
            entry["used_by"].add(used_by)
            entry["dev"] = entry["dev"] and bool(info.get("dev"))
    return rows


def render():
    py, missing = python_packages()
    npm = npm_packages()
    look = sorted({f"{v['name']} ({v['license']})" for v in py.values() if COPYLEFT.search(v["license"])} |
                  {f"{n} ({e['license']}{', build tool, not shipped' if e['dev'] else ''})"
                   for (n, _), e in npm.items() if COPYLEFT.search(str(e["license"]))} |
                  {f"{v['name']} (licence unknown)" for v in py.values() if v["license"] == "UNKNOWN"} |
                  {f"{n} (licence unknown)" for (n, _), e in npm.items() if e["license"] == "UNKNOWN"})
    out = ["# Licences of the software AutoEdit uses", "",
           "Generated by `python scripts/licenses.py` (do not edit by hand; run it again after changing dependencies).",
           "This list is information, not legal advice.", "",
           "**AutoEdit itself:** all rights reserved by its owner unless the owner adds a licence file.", ""]
    out += ["## Look at", ""]
    out += [f"- {x}" for x in look] or ["- nothing: no copyleft or unknown licences among the packages found"]
    out += ["", "FFmpeg (below) is GPL in the container images: see the note there.", ""]
    if missing:
        out += [f"Not installed when this was generated (install all requirements and run again): "
                f"{', '.join(sorted(missing))}", ""]
    out += ["## Programs and fonts in the apps and images", "", "| What | Licence | Note |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in BUNDLED]
    out += ["", "## Not shipped", "", "| What | Note |", "|---|---|"]
    out += [f"| {a} | {b} |" for a, b in NOT_SHIPPED]
    out += ["", "## Python packages", "", "| Package | Version | Licence | Used by |", "|---|---|---|---|"]
    for v in sorted(py.values(), key=lambda v: v["name"].lower()):
        used = ", ".join(sorted(v["used_by"])) + (" (tests only)" if _norm(v["name"]) in TEST_ONLY else "")
        out.append(f"| {v['name']} | {v['version']} | {v['license']} | {used} |")
    out += ["", "## npm packages", "", "Build tools (dev) are used to build the apps and are not shipped in them.", "",
            "| Package | Version | Licence | Used by |", "|---|---|---|---|"]
    for (name, version), e in sorted(npm.items()):
        out.append(f"| {name} | {version} | {e['license']} | {', '.join(sorted(e['used_by']))}"
                   f"{' (dev)' if e['dev'] else ''} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    (ROOT / "LICENSES.md").write_text(render(), encoding="utf-8")
    print("LICENSES.md written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
