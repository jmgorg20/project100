"""The PREMIUM EDITORIAL VIRAL acceptance test: a talking-head video through the real AI edit
with default settings, rendered, then checked cue by cue (did each spoken cue produce the matching
effect, with the right text, at the right second?) plus contact sheets of the frames.

    python scripts/acceptance.py OUT_FOLDER [--video base.mp4] [--words words.json]
                                 [--cues cues.json] [--preset ID] [--real-transcription]

Without --video, a 29.8 s stand-in clip is made with FFmpeg (a test pattern and a tone). Without
--real-transcription the words come from the word-timestamp fixture (--words), because this
machine may have no Groq key or local Whisper; the report says which was used. The test pictures
(search_results.png, tiktok_logo.png, facebook_logo.png, youtube_logo.png, profile_photo.png) are
made here for the test only; they are never part of the app.

A cue that produced nothing is a FAILURE. Exit code 0 only when every cue passed.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoedit.director import norm, timeline_words  # noqa: E402

DATA = ROOT / "tests" / "data" / "acceptance"
ASSETS = {  # name -> (colour, size, label drawn on it)
    "search_results.png": ("#f4f4f4", "900x1400", "results"),
    "tiktok_logo.png": ("#111111", "400x400", "T"),
    "facebook_logo.png": ("#1877f2", "400x400", "f"),
    "youtube_logo.png": ("#ff0000", "400x400", "Y"),
    "profile_photo.png": ("#c8a27a", "400x400", "P"),
}


def make_assets(folder):
    """Simple test pictures (a fake results screenshot, letter logos, a face-coloured photo), drawn
    here for this test only."""
    from PIL import Image, ImageDraw
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, (colour, size, label) in ASSETS.items():
        w, h = (int(x) for x in size.split("x"))
        img = Image.new("RGB", (w, h), colour)
        d = ImageDraw.Draw(img)
        if name == "search_results.png":
            d.rounded_rectangle((40, 40, w - 40, 130), 45, fill="#ffffff", outline="#c9c9c9", width=4)
            for k in range(6):
                y = 190 + k * 190
                d.rectangle((60, y, 60 + 520, y + 34), fill="#1a56db")
                d.rectangle((60, y + 60, w - 80, y + 84), fill="#9aa0a6")
                d.rectangle((60, y + 100, w - 260, y + 124), fill="#9aa0a6")
        else:
            d.ellipse((w * 0.2, h * 0.2, w * 0.8, h * 0.8), fill="#ffffff" if colour != "#c8a27a" else "#7a5230")
        path = folder / name
        img.save(path)
        out.append(path)
    return out


def make_stand_in(path, seconds, words):
    """A 720x1280 stand-in for the talking head: a moving test pattern, a tone while words are
    said (so the cuts see speech where the words are)."""
    on = "+".join(f"between(t,{w['start']:.3f},{w['end']:.3f})" for w in words) or "0"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=720x1280:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.4*sin(2*PI*180*t)*min(1,{on})':s=48000:d={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(path)], check=True)
    return path


# ---------------------------------------------------------------- checking the cues

def strings_of(clip, media_names):
    """Every text a clip shows (text, items, numbers, picture names), lower case."""
    p = clip.get("params") or {}
    out = []
    for key in ("text", "text2", "prefix", "suffix"):
        if p.get(key):
            out.append(str(p[key]))
    out += [str(x) for x in p.get("items") or []]
    if p.get("number") is not None:
        out.append(str(p["number"]))
    for ref in ([p["image"]] if p.get("image") else []) + list(p.get("images") or []):
        out.append(media_names.get(ref, ref))
    if clip.get("media"):
        out.append(media_names.get(clip["media"], clip["media"]))
    return [s.replace("*", "").lower() for s in out]


def phrase_time(words, phrase, after=0.0):
    """(start, end) of the spoken phrase (first match at or after `after`)."""
    toks = [norm(t) for t in phrase.split() if norm(t)]
    norms = [norm(w["text"]) for w in words]
    for i in range(len(words) - len(toks) + 1):
        if words[i]["start"] >= after - 0.01 and norms[i:i + len(toks)] == toks:
            return words[i]["start"], words[i + len(toks) - 1]["end"]
    return None


def number_like(text):
    return {re.sub(r"[^\d]", "", x) for x in re.findall(r"\d[\d,.]*", text)}


def check_cues(project, cues):
    words = timeline_words(project)
    media_names = {m["id"]: Path(m.get("name") or m["path"]).name for m in project["media"]}
    clips = [c for t in project["tracks"] for c in t["clips"] if t["kind"] in ("graphics", "effect", "overlay")]
    rows = []
    for cue in cues:
        at = phrase_time(words, cue["said"])
        row = {"id": cue["id"], "said": cue["said"], "expect": cue["expect"], "want": cue.get("want", []),
               "time": round(at[0], 2) if at else None, "found": [], "ok": False}
        if at is None:
            row["why"] = "the phrase is not in the transcript (cut out?)"
            rows.append(row)
            continue
        s, e = at
        lo, hi = s - 0.6, e + float(cue.get("late", 1.2))
        for c in clips:
            if not (lo <= c["start"] <= hi):
                continue
            kind = c.get("template") or c.get("effect") or c.get("type")
            texts = strings_of(c, media_names)
            joined = " | ".join(texts)
            if cue["expect"] == "bw":
                hit = c.get("type") == "fx" and c.get("effect") == "bw"
            elif cue["expect"] == "numbers":
                nums = set().union(*(number_like(t) for t in texts)) if texts else set()
                hit = c.get("type") == "graphic" and any(n in nums for n in cue["want"])
            else:
                hit = c.get("type") == "graphic" and (not cue.get("templates") or kind in cue["templates"]) and \
                    any(w.lower() in joined for w in cue["want"])
            if hit:
                row["found"].append({"clip": c["id"], "kind": kind, "start": round(c["start"], 2),
                                     "end": round(c["start"] + c["duration"], 2), "shows": joined[:160]})
        need = int(cue.get("count", 1))
        matched = set()
        for f in row["found"]:
            for w in cue["want"]:
                if w.lower() in f["shows"] or (cue["expect"] == "numbers" and w in re.sub(r"[^\d|]", "", f["shows"])):
                    matched.add(w.lower())
        row["ok"] = bool(row["found"]) and (cue["expect"] == "bw" or len(matched) >= min(need, len(cue["want"])))
        if not row["ok"]:
            row["why"] = "nothing appeared for this cue" if not row["found"] else \
                f"only {sorted(matched)} of {cue['want']} appeared"
        rows.append(row)
    return rows


# ---------------------------------------------------------------- frames

def contact_sheet(video, out, every=2.0, cols=5, width=216):
    """A frame every `every` seconds, tiled."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
                    f"fps={1 / every},scale={width}:-1,drawtext=text='%{{pts\\:hms}}':x=6:y=6:fontsize=18:"
                    f"fontcolor=white:box=1:boxcolor=black@0.6,tile={cols}x3:padding=4:color=white",
                    str(out).replace(".jpg", "_%02d.jpg")], check=True)
    return sorted(out.parent.glob(out.stem + "_*.jpg"))


def cue_frames(video, rows, folder):
    out = []
    for r in rows:
        if r["time"] is None:
            continue
        t = (r["found"][0]["start"] + 0.9) if r["found"] else r["time"] + 0.9
        path = folder / f"cue_{r['id']}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=360:-1", str(path)], check=True)
        out.append(path)
    return out


# ---------------------------------------------------------------- the run

def run(out, video=None, words_file=DATA / "base_words.json", cues_file=DATA / "base_cues.json", preset=None,
        real=False, seconds=29.8, instruction=""):
    from autoedit import ai_edit
    from autoedit.config import load_config
    from autoedit.words import load_transcript
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(Path(words_file).read_text(encoding="utf-8"))["words"]
    if video is None:
        seconds = max(seconds, round(fixture[-1]["end"] + 0.6, 2))
        video = make_stand_in(out / "base_stand_in.mp4", seconds, fixture)
        source = f"a {seconds:g} s stand-in clip made with FFmpeg (the base video was not available here)"
    else:
        source = f"the video {video}"
    photos = make_assets(out / "assets")
    if not real:
        words = load_transcript(words_file)
        ai_edit.transcribe = lambda *a, **k: list(words)            # the fixture stands in for Whisper
        heard = f"the word-timestamp fixture {Path(words_file).name} (no transcription here)"
    else:
        heard = "real transcription (config.yaml transcription:)"
    cfg = load_config()
    cfg["work_folder"] = str(out / "work")
    cfg["ai"]["cache_folder"] = str(out / "cache")
    cfg["output"]["encoder_speed"] = "ultrafast"
    result = ai_edit.ai_edit_video(video, cfg, instruction, [str(p) for p in photos], render=True,
                                   output=out / "edit.mp4", preset=preset)
    project = json.loads(Path(result["project"]).read_text(encoding="utf-8"))
    cues = json.loads(Path(cues_file).read_text(encoding="utf-8"))
    rows = check_cues(project, cues)
    # the captions as the renderer writes them (the .ass file burned into the video)
    from autoedit.project_render import build_project_ass
    ass = build_project_ass(project, ROOT / "assets" / "fonts") or ""
    shown = " ".join(re.sub(r"\{[^}]*\}", " ", line.split(",", 9)[9]) for line in ass.splitlines()
                     if line.startswith("Dialogue:") and ",Main" in line)
    bad = re.findall(r"\S*(?:[!?;:]|(?<!\d)[.,](?!\d))\S*", shown.replace("\\N", " "))
    rows.append({"id": "captions", "said": "(every caption on screen)", "expect": "no end punctuation",
                 "ok": not bad, "found": [], "time": None, "want": [],
                 "why": f"punctuation on screen: {bad[:5]}" if bad else ""})
    sheets = contact_sheet(Path(result["output"]), out / "sheet.jpg")
    frames = cue_frames(Path(result["output"]), rows, out)
    graphics = [c for t in project["tracks"] if t["kind"] == "graphics" for c in t["clips"]]
    effects = [c for t in project["tracks"] if t["kind"] in ("effect",) for c in t["clips"]]
    report = {"video": source, "words": heard, "preset": preset or "(none: default settings)",
              "graphics": len(graphics), "effects": len(effects), "passed": sum(r["ok"] for r in rows),
              "failed": sum(not r["ok"] for r in rows), "cues": rows, "output": result["output"],
              "sheets": [str(s) for s in sheets], "cue_frames": [str(f) for f in frames],
              "fallback": result.get("fallback"), "reason": result.get("reason", "")}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    return report


def markdown(r):
    lines = [f"Video: {r['video']}  ", f"Words: {r['words']}  ", f"Preset: {r['preset']}  ",
             f"Graphics: {r['graphics']}, effect clips: {r['effects']}  ",
             f"**{r['passed']} passed, {r['failed']} FAILED**", "",
             "| cue | said | expected | result | what appeared |", "|---|---|---|---|---|"]
    for c in r["cues"]:
        shows = "; ".join(f"{f['kind']} @ {f['start']}s: {f['shows']}" for f in c["found"])[:220] or "—"
        res = "PASS" if c["ok"] else f"**FAILURE** ({c.get('why', '')})"
        when = f" @ {c['time']}s" if c.get("time") is not None else ""
        lines.append(f"| {c['id']} | {c['said']}{when} | {c['expect']} {c.get('want') or ''} | {res} | {shows} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--video")
    ap.add_argument("--words", default=str(DATA / "base_words.json"))
    ap.add_argument("--cues", default=str(DATA / "base_cues.json"))
    ap.add_argument("--preset")
    ap.add_argument("--instruction", default="")
    ap.add_argument("--real-transcription", action="store_true")
    a = ap.parse_args()
    r = run(a.out, a.video, a.words, a.cues, a.preset, a.real_transcription, instruction=a.instruction)
    print(markdown(r))
    sys.exit(0 if r["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
