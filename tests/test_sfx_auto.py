"""Sound effects synced to the graphics (the real Windows export had none): every sound is made by
FFmpeg (nothing copied, safe to post), each lands on its graphic's moment (a whoosh as a card
comes in, a tick on each checklist item, typing while the search bar types, a shutter on a
screenshot, a rise into the black-and-white past and an impact on "ngayon"), your own files in
assets/sfx win, and "off" means none."""

import math
import subprocess

import pytest

from autoedit import sfx_auto, sfx_synth
from autoedit.ffmpeg_tools import find_tool
from autoedit.words import load_transcript
from tests.test_asset_report import with_photos
from tests.test_editorial_director import cfg, graphics_of, run

REAL = "tests/data/realclip/groq_words.json"


def peak_db(path):
    out = subprocess.run([find_tool("ffmpeg"), "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(out.split("max_volume:")[1].split("dB")[0])


@pytest.mark.parametrize("name", sorted(sfx_synth.SOUNDS))
def test_every_sound_is_made_here_and_is_audible_not_loud(name, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOEDIT_SFX_CACHE", str(tmp_path))
    monkeypatch.setenv("AUTOEDIT_OWN_SFX", str(tmp_path / "none"))
    path = sfx_synth.sound_file(name)
    assert path.parent == tmp_path and -30 < peak_db(path) < -2


def test_your_own_sound_wins(tmp_path, monkeypatch):
    own = tmp_path / "own"
    own.mkdir()
    (own / "whoosh.mp3").write_bytes(b"x")
    monkeypatch.setenv("AUTOEDIT_OWN_SFX", str(own))
    assert sfx_synth.sound_file("whoosh") == own / "whoosh.mp3"
    monkeypatch.setenv("AUTOEDIT_SFX_CACHE", str(tmp_path / "made"))
    assert sfx_synth.sound_file("tick").parent == tmp_path / "made"


def real_edit(tmp_path):
    words = [{"text": w.text, "start": w.start, "end": w.end} for w in load_transcript(REAL)]
    return run(with_photos(words, tmp_path), cfg())["project"]           # with the user's photos


def test_each_graphic_gets_its_sound_on_its_moment(tmp_path):
    p = real_edit(tmp_path)
    sounds = sfx_auto.plan(p)
    at = lambda name: [t for n, t, _l in sounds if n == name]          # noqa: E731
    shown = {c["template"]: c for c in graphics_of(p)}
    for c in graphics_of(p):                                         # every card comes in with a sound
        assert any(abs(t - c["start"]) < 0.09 for n, t, _l in sounds if n in ("whoosh", "soft_pop")), c["template"]
    check = shown["editorial-checklist"]
    ticks = [check["start"] + x for x in check["params"]["cues"]]
    assert all(any(abs(t - x) < 0.01 for t in at("tick")) for x in ticks)       # a tick on each item
    bar = shown["search-bar"]
    a, b = (bar["start"] + x for x in bar["params"]["cues"][:2])
    typing = [t for t in at("type") if a - 1e-6 <= t < b]
    assert len(typing) >= 5                                                      # typing while it types
    assert any(abs(t - (shown["screenshot-collage"]["start"] + 0.12)) < 0.01 for t in at("shutter"))
    bw = next(c for t in p["tracks"] for c in t["clips"] if c.get("effect") == "bw")
    assert at("rise") and at("rise")[0] < bw["start"] and abs(at("impact")[0] - (bw["start"] + bw["duration"] - 0.15)) < 0.01
    times = [t for _n, t, _l in sounds]
    assert all(b - a >= sfx_auto.MIN_GAP - 1e-6 for a, b in zip(times, times[1:]))


def test_the_sounds_go_on_the_sound_effects_track_quietly_or_not_at_all(tmp_path):
    p = real_edit(tmp_path)
    n = sfx_auto.add(p, {"sfx": {"auto": "auto", "auto_volume": 0.35}})
    track = next(t for t in p["tracks"] if t["kind"] == "audio" and t.get("role") == "sfx")
    assert n > 20 and len([c for t in p["tracks"] if t.get("role") == "sfx" for c in t["clips"]]) == n
    assert all(0 < c["volume"] <= 0.35 for c in track["clips"])
    assert p["settings"]["audio"]["sfx_ducking"] == 0.5
    q = real_edit(tmp_path)
    assert sfx_auto.add(q, {"sfx": {"auto": "off"}}) == 0
    assert not any(t["clips"] for t in q["tracks"] if t.get("role") == "sfx")


def test_ducking_makes_them_a_little_quieter_not_buried(tmp_path, monkeypatch):
    # the first real-export measurement found the sounds ~19 dB under the voice: now ~5 dB
    monkeypatch.setenv("AUTOEDIT_SFX_CACHE", str(tmp_path))
    from autoedit.project_render import Graph, add_audio_tracks
    p = real_edit(tmp_path)
    sfx_auto.add(p, {"sfx": {"auto": "auto", "auto_volume": 0.35}})
    g = Graph()
    add_audio_tracks(g, p, {m["id"]: m for m in p["media"]}, ".", 30, "0:a")
    line = next(x for x in g.lines if "[sfxkey]sidechaincompress" in x)
    threshold = float(line.split("threshold=")[1].split(":")[0])
    ratio = float(line.split("ratio=")[1].split(":")[0])
    voice = -10.0                                                     # a normal voice, dBFS
    cut = (voice - 20 * math.log10(threshold)) * (1 - 1 / ratio)
    assert 3 <= cut <= 7
