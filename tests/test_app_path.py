"""The app path on the real Windows run: a talking-head preset stays a talking head ("countdown" in
the instruction is a graphic, not the Ranking format), the plan AI is told the cards come from
the words (no "only the provided photos" notes), and every card asked for is reported."""

from autoedit import ai_edit, editorial, formats


def test_format_keywords_are_whole_words_and_countdown_is_a_graphic():
    scores = formats.keyword_scores("Gusto ko ng countdown at checklist, search bar")
    assert "ranking" not in scores and "listicle" not in scores
    assert "ranking" in formats.keyword_scores("gawin mong ranking, top 5")
    assert "listicle" in formats.keyword_scores("isang list ng tips")


def test_the_plan_ai_is_told_the_cards_need_no_photos():
    cfg = {"graphics": {"style": "auto"}}
    text = ai_edit.graphics_text(cfg, "countdown at checklist", "premium_editorial")
    assert "MOTION GRAPHICS: ON" in text and "NO photos" in text
    assert ai_edit.graphics_text(cfg, "", "off") == ""


def test_notes_about_cards_are_left_to_the_graphics_step():
    note = ("Some requested pop-ups (countdown graphics, large-word card, checklist, storyboard card, "
            "text card) could not be created because only the provided photos are available.")
    assert ai_edit.GRAPHICS_NOTE.search(note)
    assert not ai_edit.GRAPHICS_NOTE.search("Music cannot be added by the program.")


def test_every_card_asked_for_is_reported():
    made = [("countdown", 3.0, "Tatlo dalawa isa"), ("before_after", 6.1, "Dati wala akong follower"),
            ("before_after", 6.1, "")]
    lines = editorial.requested_lines("countdown, storyboard card at black and white sa dati", made)
    assert lines[0] == 'You asked for countdown: made at 0:03 ("Tatlo dalawa isa").'
    assert "storyboard card: nothing in what you said" in lines[1] and "Storyboard ko" in lines[1]
    assert lines[2].count("0:06") == 1                                    # one moment, one mention
    assert editorial.requested_lines("", made) == []
