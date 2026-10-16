import pytest

from autoedit.cuts import (alternate_zoom, cut_points, find_removals, is_filler, keep_segments,
                           merge_intervals, remap_range, remap_time, remap_words, snap_to_frames,
                           total_length)
from autoedit.words import Word

FILLERS = ["ah", "uh", "um", "uhm", "eh"]


def w(text, start, end):
    return Word(text, start, end)


def test_merge_intervals():
    assert merge_intervals([(5, 6), (1, 2), (1.5, 3), (3, 4)]) == [(1, 4), (5, 6)]
    assert merge_intervals([(2, 2), (3, 1)]) == []


def test_filler_detection_ignores_case_punctuation_and_repeats():
    assert is_filler(w("Uhm,", 0, 1), FILLERS)
    assert is_filler(w("ummm", 0, 1), FILLERS)
    assert is_filler(w("AH...", 0, 1), FILLERS)
    assert not is_filler(w("ako", 0, 1), FILLERS)
    assert not is_filler(w("umaga", 0, 1), FILLERS)


def test_long_silence_is_cut_with_padding():
    words = [w("isa", 0.0, 1.0), w("dalawa", 2.0, 3.0)]
    removals = find_removals(words, 3.0, silence_threshold=0.25, padding=0.08)
    assert removals == [pytest.approx((1.08, 1.92))]


def test_short_pause_is_kept():
    words = [w("isa", 0.0, 1.0), w("dalawa", 1.2, 2.0)]
    assert find_removals(words, 2.0, 0.25, 0.08) == []


def test_leading_and_trailing_silence_cut():
    words = [w("hello", 1.0, 2.0)]
    removals = find_removals(words, 5.0, 0.25, 0.08)
    assert removals == [pytest.approx((0.0, 0.92)), pytest.approx((2.08, 5.0))]


def test_filler_word_inside_long_gap_is_cut_together_with_silence():
    words = [w("isa", 0.0, 1.0), w("uh", 1.3, 1.6), w("dalawa", 2.0, 3.0)]
    removals = find_removals(words, 3.0, 0.25, 0.08, fillers=FILLERS)
    assert removals == [pytest.approx((1.08, 1.92))]


def test_tight_filler_is_cut_even_without_silence():
    words = [w("isa", 0.0, 1.0), w("um", 1.0, 1.2), w("dalawa", 1.2, 2.0)]
    removals = find_removals(words, 2.0, 0.25, 0.08, fillers=FILLERS)
    assert len(removals) == 1
    start, end = removals[0]
    assert 1.0 < start < 1.06 and 1.14 < end < 1.2


def test_fillers_kept_when_switched_off():
    words = [w("isa", 0.0, 1.0), w("um", 1.0, 1.2), w("dalawa", 1.2, 2.0)]
    assert find_removals(words, 2.0, 0.25, 0.08, FILLERS, remove_fillers=False) == []


def test_audio_silence_and_manual_cuts_are_added():
    words = [w("mahabang", 0.0, 3.0)]  # word timing smeared over a pause
    removals = find_removals(words, 3.0, 0.25, 0.08, audio_silences=[(1.0, 2.0)],
                             manual_cuts=[(2.5, 2.7)])
    assert removals == [pytest.approx((1.08, 1.92)), pytest.approx((2.5, 2.7))]


def test_no_words_keeps_everything():
    assert find_removals([], 10.0, 0.25, 0.08) == []


def test_keep_segments_is_complement_and_drops_tiny_pieces():
    keeps = keep_segments([(1.0, 2.0), (2.05, 3.0)], 5.0, min_keep=0.1)
    assert keeps == [(0.0, 1.0), (3.0, 5.0)]


def test_snap_to_frames():
    assert snap_to_frames([(0.01, 1.02)], 30) == [(0.0, pytest.approx(1.0333, abs=1e-3))]
    assert snap_to_frames([(1.0, 2.0)], 30) == [(1.0, 2.0)]
    s, e = snap_to_frames([(0.51, 0.52)], 30)[0]
    assert s <= 0.51 and e >= 0.52 and round((e - s) * 30) == 1


def test_remap_time_moves_times_onto_cut_timeline():
    segments = [(0.0, 1.0), (2.0, 3.0), (5.0, 6.0)]
    assert remap_time(0.5, segments) == pytest.approx(0.5)
    assert remap_time(2.5, segments) == pytest.approx(1.5)
    assert remap_time(5.25, segments) == pytest.approx(2.25)
    # Inside a removed part: snap forward or back.
    assert remap_time(1.5, segments, side="next") == pytest.approx(1.0)
    assert remap_time(1.5, segments, side="prev") == pytest.approx(1.0)
    assert remap_time(4.0, segments, side="next") == pytest.approx(2.0)
    assert remap_time(7.0, segments, side="next") is None
    assert remap_time(7.0, segments, side="prev") == pytest.approx(3.0)


def test_remap_words_drops_cut_words_and_fillers():
    segments = [(0.0, 1.0), (2.0, 3.0)]
    words = [w("isa", 0.1, 0.5), w("um", 0.6, 0.9), w("nawala", 1.2, 1.8), w("dalawa", 2.2, 2.6)]
    result = remap_words(words, segments, FILLERS)
    assert [x.text for x in result] == ["isa", "dalawa"]
    assert (result[1].start, result[1].end) == (pytest.approx(1.2), pytest.approx(1.6))


def test_remap_words_clamps_partly_cut_word():
    segments = [(0.0, 1.0), (2.0, 3.0)]
    result = remap_words([w("hati", 0.8, 2.3)], segments)
    assert (result[0].start, result[0].end) == (pytest.approx(0.8), pytest.approx(1.3))


def test_remap_range():
    segments = [(0.0, 1.0), (2.0, 3.0)]
    assert remap_range(0.5, 2.5, segments) == (pytest.approx(0.5), pytest.approx(1.5))
    assert remap_range(1.2, 1.8, segments) is None


def test_full_cut_math_end_to_end():
    words = [w("a", 0.5, 1.0), w("b", 2.0, 2.5)]
    removals = find_removals(words, 3.0, 0.25, 0.08)
    segments = snap_to_frames(keep_segments(removals, 3.0), 30)
    assert total_length(segments) == pytest.approx(0.66 + 0.66, abs=0.1)
    new = remap_words(words, segments)
    assert new[0].start == pytest.approx(0.08, abs=0.04)
    assert new[1].start == pytest.approx(new[0].end + 0.16, abs=0.08)


def test_cut_points_and_alternating_zoom():
    segments = [(0, 2), (3, 5), (6, 8), (9, 11)]   # cuts at 2, 4, 6 on the new timeline
    assert cut_points(segments) == [2, 4, 6]
    zooms = alternate_zoom(segments, min_interval=1.5, max_interval=4.0)
    assert zooms == [(2, 4), (6, 8)]


def test_alternating_zoom_forces_switch_on_long_takes():
    zooms = alternate_zoom([(0, 10)], min_interval=1.5, max_interval=3.0)
    assert zooms == [(3.0, 6.0), (9.0, 10)]   # flips at 3, 6 and 9 seconds
    assert alternate_zoom([(0, 10)], 1.5, 4.0) == [(4.0, 8.0)]  # 8 + 4 is past the end
    assert alternate_zoom([(0, 1)], 1.5, 4.0) == []
