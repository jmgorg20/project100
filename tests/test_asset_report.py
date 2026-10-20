"""Your photos on the real Windows run ("search result.png" reported skipped twice while a collage
used it; logos never placed): each photo is matched by name and by meaning (spaces and capitals
do not matter), can be pinned to a word in the instruction, and gets a line saying where it was
used and why, or why not."""

from autoedit import editorial
from autoedit.project import media_from_file
from autoedit.words import load_transcript
from tests import synthetic
from tests.director_helpers import make_project, make_words
from tests.test_editorial_director import cfg, graphics_of, run

REAL = "tests/data/realclip/groq_words.json"
NAMES = ["search result.png", "TikTok logo.png", "Facebook logo.png", "YouTube logo.png", "profile photo.png"]


def with_photos(words, tmp_path, names=NAMES):
    p = make_project(words, caption_style="editorial_card")
    for i, name in enumerate(names):
        p["media"].append(media_from_file(synthetic.make_image(tmp_path / name, color="blue", size="600x400"), f"up{i}"))
    return p


def real_words():
    return [{"text": w.text, "start": w.start, "end": w.end} for w in load_transcript(REAL)]


def test_names_with_spaces_and_capitals_and_meanings_match(tmp_path):
    assets = editorial.Assets(with_photos(real_words(), tmp_path), cfg())
    assert assets.platform_logos == {"tiktok": "up1", "facebook": "up2", "youtube": "up3"}
    assert assets.avatar == "up4" and assets.images == ["up0"]
    assert assets.name_matches("up0", ["resulta"]) == ["resulta"]               # spelling: "result"
    assert assets.name_matches("up0", ["kumain"]) == []
    p = with_photos(real_words(), tmp_path, ["Benta ko.png"])
    assert editorial.Assets(p, cfg()).name_matches("up0", ["sales"]) == ["sales"]   # meaning: benta = sales


def test_every_photo_gets_a_reason(tmp_path):
    r = run(with_photos(real_words(), tmp_path), cfg())
    lines = {line.split(":")[0]: line for line in r["assets"]}
    assert set(lines) == set(NAMES)
    assert "used at 0:14 as screenshot-collage (matched 'resulta'" in lines["search result.png"]
    assert "profile-card" in lines["profile photo.png"] and "I-follow mo ako" in lines["profile photo.png"]
    assert "not used - TikTok is never said" in lines["TikTok logo.png"]
    assert "YouTube is never said" in lines["YouTube logo.png"] and "show YouTube logo when I say" in lines["YouTube logo.png"]


def test_a_photo_can_be_pinned_to_a_word(tmp_path):
    words = make_words("Nasa TikTok ako araw-araw . Salamat sa mga followers ko .".split())
    p = with_photos(words, tmp_path)
    r = editorial.generate(p, cfg(), "Ipakita ang Facebook logo pag sinabi ko followers. show search result when I say Salamat",
                           use_ai=False)
    shown = graphics_of(r["project"])
    followers = next(w["start"] for w in words if w["text"] == "followers")
    salamat = next(w["start"] for w in words if w["text"] == "Salamat")
    assert any(c["template"] == "app-tile" and c["params"].get("image") == "up2" and abs(c["start"] - followers) < 0.05
               for c in shown)
    assert any("up0" in (c["params"].get("images") or []) and abs(c["start"] - salamat) < 0.05 for c in shown)
    assert any(line.startswith("Facebook logo.png: used at") and "pinned in your instruction" in line for line in r["assets"])


def test_a_pin_that_cannot_be_done_is_said(tmp_path):
    words = make_words("Salamat sa inyo .".split())
    r = editorial.generate(with_photos(words, tmp_path), cfg(), "show tiktok logo when I say TikTok. show menu when I say Salamat",
                           use_ai=False)
    assert any('"TikTok" is not said' in n for n in r["notes"])
    assert any('show "menu" on "Salamat", but none of your files has that name' in n for n in r["notes"])
