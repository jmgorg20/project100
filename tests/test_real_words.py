"""Real Whisper words, as the Windows app got them: no punctuation, lowercase key words, "Tatyo" for
"Tatlo". The Taglish post-correction, the cue engine on such words, and the real app entry point
(`editor.py ai-edit`, as the desktop app runs it) all make every spoken card."""

import json
import subprocess
import sys

import pytest
import yaml

from autoedit import PROJECT_DIR, cues
from autoedit.config import load_config
from autoedit.taglish import correct_words
from autoedit.words import Word, load_transcript
from tests import synthetic

REAL = PROJECT_DIR / "tests" / "data" / "realclip" / "groq_words.json"


def real_words():
    return [{"text": w.text, "start": w.start, "end": w.end} for w in load_transcript(REAL)]


@pytest.mark.parametrize("heard, fixed", [("Tatyo", "Tatlo"), ("tatlu", "tatlo"), ("hinanat", "hinanap"),
                                          ("disipina", "disiplina"), ("tatlumpong", "tatlumpung")])
def test_misheard_taglish_words_are_put_right(heard, fixed):
    out, changes = correct_words([Word(heard, 0, 1)])
    assert out[0].text == fixed and changes == [(heard, fixed)]


@pytest.mark.parametrize("word", ["wala", "sana", "dito", "posts", "comment", "shame", "lake", "Facebook", "ako"])
def test_right_words_are_left_alone(word):
    assert correct_words([Word(word, 0, 1)])[1] == []


def test_the_words_of_your_instruction_and_files_are_known():
    out, _ = correct_words([Word("Kumbucha", 0, 1)], ["gawa ng kombucha", "kombucha_logo.png"])
    assert out[0].text == "Kombucha"                         # one letter off a word you wrote
    assert correct_words([Word("Kumbucha", 0, 1)], enabled=False)[0][0].text == "Kumbucha"


def test_every_spoken_card_from_real_unpunctuated_words():
    found = {c.kind: c for c in cues.extract(real_words())}
    # "Tatyo dalawa isa" (no correction applied here): a countdown from the near-miss
    assert found["countdown"].number == 3 and [t for _k, t in found["countdown"].items] == ["3", "2", "1"]
    assert found["keyword"].text == "DISIPLINA"                              # "Una disiplina", no caps
    assert found["search"].text == "paano kumita online"
    assert found["before_after"].items[0][1] == "Ngayon ito na ako"
    # "Ito ang checklist ko sa phone" + "Mag-post sagutin ang comments i-check ang analytics"
    assert [t for _k, t in found["checklist"].items] == ["Mag-post", "sagutin ang comments", "i-check ang analytics"]
    assert found["checklist"].text == "checklist ko sa phone"
    assert [t for _k, t in found["stats"].items] == ["0", "1,000 followers", "30 araw"]   # "tatlumpong"
    assert "screenshot" in found and "follow" in found


def test_sentences_without_punctuation_follow_pauses_and_capitals():
    spans = cues.sentence_spans(real_words())
    ws = real_words()
    said = [" ".join(w["text"] for w in ws[a:b + 1]) for a, b in spans]
    assert "Tatyo dalawa isa" in said and "Una disiplina" in said
    # never cut after a word that needs what follows ("... followers sa / tatlumpong araw")
    assert any(s.endswith("sa tatlumpong araw") for s in said)


def test_punctuated_transcripts_keep_their_own_sentences():
    ws = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, t in
          enumerate("Ito ang plano ko. Gising, kape, edit.".split())]
    assert cues.sentence_spans(ws) == [(0, 3), (4, 6)]


def test_the_app_entry_point_makes_every_spoken_card(tmp_path):
    """`editor.py --json ai-edit` exactly as the desktop app runs it (preset, --format auto, the
    instruction file, your photos), with the real words given as --transcript."""
    data = json.loads(REAL.read_text(encoding="utf-8"))
    seconds = data["words"][-1]["end"] + 0.6
    video = tmp_path / "talking.mp4"
    on = "+".join(f"between(t,{w['start']},{w['end']})" for w in data["words"])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=720x1280:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"aevalsrc='0.4*sin(2*PI*180*t)*min(1,{on})':s=48000:d={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(video)], check=True)
    photos = [synthetic.make_image(tmp_path / n, color=c, size="600x400")
              for n, c in [("search_results.png", "white"), ("profile_photo.png", "orange")]]
    cfg = load_config()
    cfg["work_folder"] = str(tmp_path / "work")
    cfg["ai"]["cache_folder"] = str(tmp_path / "cache")
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (tmp_path / "instruction.txt").write_text("Gusto ko ng countdown, checklist, search bar at profile card.",
                                              encoding="utf-8")
    out = tmp_path / "edit.mp4"
    proc = subprocess.run([sys.executable, str(PROJECT_DIR / "editor.py"), "--json", "--config", str(conf),
                           "ai-edit", str(video), "--output", str(out), "--provider", "groq",
                           "--transcribe-with", "groq", "--caption-punctuation", "remove", "--no-stock",
                           "--instruction-file", str(tmp_path / "instruction.txt"), "--no-render",
                           "--preset", "premium_editorial_viral", "--format", "auto",
                           "--transcript", str(REAL), "--photos", *map(str, photos)],
                          capture_output=True, text=True, cwd=str(PROJECT_DIR), env={**__import__("os").environ,
                                                                                    "GROQ_API_KEY": ""})
    assert proc.returncode == 0, proc.stderr[-2000:]
    project = json.loads(out.with_suffix(".project.json").read_text(encoding="utf-8"))
    templates = {c["template"] for t in project["tracks"] if t["kind"] == "graphics" for c in t["clips"]}
    assert {"countdown-timer", "kinetic-words", "search-bar", "editorial-checklist", "stat-cards",
            "profile-card"} <= templates, (templates, [d for d in json.dumps(proc.stdout).split("\\n") if "Graphics:" in d][:12])
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    details = next(e for e in events if e.get("type") == "summary")["details"]
    assert any("'Tatyo' -> 'Tatlo'" in d for d in details)
    # a talking-head preset: never the Ranking format because "countdown" was asked for
    assert project["meta"]["format"] == "talking_head" and not any(d.startswith("Format:") for d in details)
    assert any(d.startswith("Graphics: You asked for checklist: made at") for d in details)
    captions = [w["text"] for t in project["tracks"] if t["kind"] == "caption" for c in t["clips"]
                for w in c.get("words", [])]
    assert "Tatlo" in captions and "Tatyo" not in captions                   # the captions say it right
