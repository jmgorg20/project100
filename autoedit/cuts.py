"""The cutting math: which parts of the video to keep, and how times move after cutting.

Everything here is plain arithmetic on lists of (start, end) seconds, so it is easy to test.
"""

import math

from .words import collapse_repeats, normalize


def is_filler(word, fillers):
    wanted = {collapse_repeats(normalize(f)) for f in fillers}
    return collapse_repeats(normalize(word.text)) in wanted


def merge_intervals(intervals):
    """Sort and join overlapping/touching (start, end) intervals."""
    merged = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def find_removals(words, duration, silence_threshold, padding, fillers=(),
                  remove_fillers=True, audio_silences=(), manual_cuts=()):
    """Return the time ranges to cut out of the original video.

    - Silences between spoken words longer than `silence_threshold` are cut,
      leaving `padding` seconds of air on both sides so speech is not clipped.
    - Filler words ("uh", "um", ...) are cut out (when `remove_fillers`).
    - `audio_silences` (from ffmpeg silencedetect) catch pauses that the
      transcript's word timings smear over.
    - `manual_cuts` (from an edit plan) are removed exactly.
    """
    speech = [w for w in words if not (remove_fillers and is_filler(w, fillers))]
    removals = []

    if not speech:
        # No usable words: only cut what the audio says is silent.
        for s, e in audio_silences:
            if e - s > silence_threshold:
                removals.append((s + padding, e - padding))
        removals.extend(manual_cuts)
        return _clip(merge_intervals(removals), duration)

    # Silence before the first word and after the last word.
    if speech[0].start > silence_threshold:
        removals.append((0.0, speech[0].start - padding))
    last_end = max(w.end for w in speech)
    if duration - last_end > silence_threshold:
        removals.append((last_end + padding, duration))

    # Gaps between consecutive spoken words.
    prev_end = speech[0].end
    for word in speech[1:]:
        gap_start, gap_end = prev_end, word.start
        gap = gap_end - gap_start
        had_filler = remove_fillers and any(
            is_filler(w, fillers) and w.start >= gap_start - 0.01 and w.end <= gap_end + 0.01
            for w in words
        )
        if gap > silence_threshold:
            removals.append((gap_start + padding, gap_end - padding))
        elif had_filler and gap > 0:
            # A filler squeezed between words: cut it with a smaller safety margin.
            pad = min(padding, gap / 4)
            removals.append((gap_start + pad, gap_end - pad))
        prev_end = max(prev_end, word.end)

    for s, e in audio_silences:
        if e - s > silence_threshold:
            removals.append((s + padding, e - padding))
    removals.extend(manual_cuts)
    return _clip(merge_intervals(removals), duration)


def _clip(intervals, duration):
    return [(max(0.0, s), min(duration, e)) for s, e in intervals if min(duration, e) > max(0.0, s)]


def keep_segments(removals, duration, min_keep=0.1):
    """The parts of the video that stay: everything that is not removed.

    Tiny leftover pieces shorter than `min_keep` are dropped (they would just flicker).
    """
    keeps = []
    cursor = 0.0
    for start, end in merge_intervals(removals):
        if start > cursor:
            keeps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keeps.append((cursor, duration))
    return [(s, e) for s, e in keeps if e - s >= min_keep]


def snap_to_frames(segments, fps):
    """Round segment edges to whole video frames so audio and video stay in sync.

    Edges are rounded outwards (start earlier, end later) so speech is never clipped.
    """
    snapped = []
    for start, end in segments:
        s = math.floor(start * fps + 1e-6) / fps
        e = math.ceil(end * fps - 1e-6) / fps
        if e > s:
            snapped.append((s, e))
    return merge_intervals(snapped)


def total_length(segments):
    return sum(e - s for s, e in segments)


def remap_time(t, segments, side="next"):
    """Convert a time in the original video to a time in the cut video.

    If `t` falls inside a removed part, it moves to the start of the next kept
    part (side="next") or the end of the previous one (side="prev").
    Returns None if there is no such part.
    """
    offset = 0.0
    previous_end_out = None
    for start, end in segments:
        if t < start:
            if side == "next":
                return offset
            return previous_end_out
        if t <= end:
            return offset + (t - start)
        offset += end - start
        previous_end_out = offset
    return previous_end_out if side == "prev" else None


def remap_words(words, segments, fillers=(), remove_fillers=True):
    """Move word timestamps onto the cut timeline. Words that were cut out are dropped."""
    result = []
    for word in words:
        if remove_fillers and is_filler(word, fillers):
            continue
        new_start = remap_time(word.start, segments, side="next")
        new_end = remap_time(word.end, segments, side="prev")
        if new_start is None or new_end is None or new_end - new_start < 0.02:
            continue
        result.append(word.copy(start=round(new_start, 3), end=round(new_end, 3)))
    return result


def remap_range(start, end, segments):
    """Map an original-time range to the cut timeline. Returns None if fully removed."""
    s = remap_time(start, segments, side="next")
    e = remap_time(end, segments, side="prev")
    if s is None or e is None or e <= s:
        return None
    return (s, e)


def cut_points(segments):
    """Times in the cut video where one kept segment ends and the next begins."""
    points, t = [], 0.0
    for start, end in segments[:-1]:
        t += end - start
        points.append(round(t, 4))
    return points


def alternate_zoom(segments, min_interval, max_interval):
    """Choose when to punch in: returns [(start, end)] ranges (cut timeline) to zoom.

    The zoom flips between normal and zoomed at jump cuts, but never sooner than
    `min_interval` seconds after the last flip. If no cut comes for
    `max_interval` seconds, it flips anyway so the shot keeps moving.
    """
    total = total_length(segments)
    points = cut_points(segments)
    switches, last = [], 0.0
    while True:
        next_cut = next((p for p in points if p >= last + min_interval), None)
        forced = last + max_interval
        switch = next_cut if next_cut is not None and next_cut <= forced else forced
        if switch >= total - min_interval / 2:
            break
        switches.append(switch)
        last = switch
    edges = switches + [total]
    # Normal until the first switch, zoomed until the second, normal until the third...
    return [(edges[i], edges[i + 1]) for i in range(0, len(edges) - 1, 2)]
