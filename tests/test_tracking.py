"""Tracking: cleaning up a tracked point (gaps, smoothing, loss), reading MediaPipe's results,
and running the detector over a video, all with synthetic tracks and a stand-in MediaPipe.
(Real MediaPipe on real footage is NOT covered here: see docs/tracking.md.)"""

import random
import sys
import threading
import types

import pytest

from autoedit import tracking
from autoedit.errors import Cancelled, EditorError
from autoedit.tracking import (DEFAULTS, Point, Prepared, Track, check_track_data, frame_points,
                               min_cutoff_for, one_euro, pick_hand, resolve, resolve_sequence)
from tests import synthetic

FPS = 30


def times(seconds, start=0.0, fps=FPS):
    return [start + i / fps for i in range(int(seconds * fps))]


def line(n, x0=0.2, x1=0.8, y=0.5, c=1.0, noise=0.0, seed=1):
    rng = random.Random(seed)
    xs = [x0 + (x1 - x0) * i / max(1, n - 1) + rng.gauss(0, noise) for i in range(n)]
    ys = [y + rng.gauss(0, noise) for _ in range(n)]
    return Point(xs, ys, [c] * n)


def steps(values):
    return [b - a for a, b in zip(values, values[1:])]


def test_a_steady_point_fades_in_and_is_followed():
    pt = Point([0.4] * 90, [0.6] * 90, [1.0] * 90)
    r = resolve(pt, FPS, 0.0, times(3))
    assert r.alpha[0] == 0.0 and r.alpha[-1] == 1.0                   # starts invisible
    assert all(b >= a for a, b in zip(r.alpha, r.alpha[1:]))          # only rises
    assert r.alpha[int(DEFAULTS["attack"] * FPS) + 1] == 1.0          # fully in after the attack time
    assert all(abs(x - 0.4) < 1e-9 and abs(y - 0.6) < 1e-9 for x, y in zip(r.x, r.y))


def test_smoothing_calms_jitter_but_keeps_up_with_motion():
    n = 150
    raw = line(n, noise=0.01)
    fine = resolve(raw, FPS, 0.0, times(5), smooth=0.0)
    steady = resolve(raw, FPS, 0.0, times(5), smooth=0.9)

    def jitter(r):
        return sum(abs(b - a) for a, b in zip(r.y, r.y[1:]))
    assert jitter(steady) < 0.35 * jitter(fine)
    # A fast sweep (0.2 -> 0.8 in 5 s = 0.12/s) is still followed closely, even when steady.
    clean = line(n)
    follow = resolve(clean, FPS, 0.0, times(5), smooth=0.9)
    lag = max(abs(a - b) for a, b in zip(follow.x[20:], clean.x[20:]))
    assert lag < 0.02
    # A quick flick (0.15 s from 0.2 to 0.8) catches up within a few frames at smooth 0.5.
    xs = [0.2] * 30 + [0.2 + 0.6 * min(1, i / 5) for i in range(40)] + [0.8] * 20
    flick = resolve(Point(xs, [0.5] * 90, [1.0] * 90), FPS, 0.0, times(3), smooth=0.5)
    assert abs(flick.x[30 + 5 + 6] - 0.8) < 0.08


def test_one_euro_basics():
    assert one_euro([1.0, 1.0, 1.0], 1 / 30, 1.0) == [1.0, 1.0, 1.0]
    out = one_euro([0, 1, 1, 1, 1, 1, 1, 1], 1 / 30, 0.6)
    assert out[1] < 1 and out[-1] > out[1]                            # approaches, not instantly
    assert min_cutoff_for(0) == pytest.approx(15) and min_cutoff_for(1) == pytest.approx(0.6)


def test_a_short_gap_is_bridged():
    pt = line(90)
    for i in range(40, 46):                                           # 0.2 s not found
        pt.c[i] = 0.0
        pt.x[i] = 0.0                                                 # garbage while lost
    r = resolve(pt, FPS, 0.0, times(3), smooth=0.0)
    assert min(r.alpha[20:]) == 1.0
    assert all(0.2 < x < 0.8 for x in r.x[20:])                       # no jump to the garbage 0.0
    expected = 0.2 + 0.6 * 43 / 89
    assert r.x[43] == pytest.approx(expected, abs=0.01)


def test_a_long_loss_fades_out_and_holds_instead_of_jumping():
    pt = line(150)
    for i in range(60, 120):                                          # lost for 2 s
        pt.c[i] = 0.0
        pt.x[i], pt.y[i] = 0.99, 0.99
    r = resolve(pt, FPS, 0.0, times(5), smooth=0.3)
    gone = [i for i in range(60, 120) if r.alpha[i] == 0.0]
    assert gone and gone[0] <= 60 + int(DEFAULTS["release"] * FPS) + 2
    # While it fades the position holds (and is where the point was), never the garbage.
    held = [r.x[i] for i in range(62, 100)]
    assert max(held) - min(held) < 1e-9 and held[0] < 0.6
    assert all(b <= a + 1e-12 for a, b in zip(r.alpha[70:100], r.alpha[71:100]))  # only falls
    # Found again: it fades back in (no sudden full brightness).
    assert r.alpha[120] < 0.3 and r.alpha[-1] == 1.0
    # No visible jump anywhere: while visible, the position moves at most a little per frame.
    for i in range(1, 150):
        if min(r.alpha[i], r.alpha[i - 1]) > 0.02:
            assert abs(r.x[i] - r.x[i - 1]) < 0.02 and abs(r.y[i] - r.y[i - 1]) < 0.02, i


def test_found_again_while_still_fading_glides_to_the_new_place():
    # Gone for 0.33 s (past the bridged gap, but it has not finished fading), back far away:
    # it would jump across.
    xs = [0.2] * 60 + [0.9] * 60
    pt = Point(list(xs), [0.5] * 120, [1.0] * 120)
    for i in range(60, 60 + 10):
        pt.c[i] = 0.0
    r = resolve(pt, FPS, 0.0, times(4), smooth=0.0)
    steps_x = [abs(b - a) for a, b in zip(r.x, r.x[1:])]
    assert max(steps_x) < 0.2                                         # 0.7 apart, glides in 0.2 s
    assert r.alpha[60 + 10] > 0.1 and r.alpha[60 + 10] < 1                 # still fading when found
    assert r.x[-1] == pytest.approx(0.9, abs=1e-6) and r.x[40] == pytest.approx(0.2, abs=1e-6)


def test_outside_the_tracked_time_counts_as_lost():
    pt = Point([0.5] * 30, [0.5] * 30, [1.0] * 30)                    # samples for 1 s from t = 2
    r = resolve(pt, FPS, 2.0, times(5))
    assert max(r.alpha[:55]) == 0.0
    assert r.alpha[60 + 12] > 0.9
    assert r.alpha[-1] == 0.0                                         # after the samples: lost
    assert resolve(Point([], [], []), FPS, 0.0, times(1)).alpha == [0.0] * 30


def test_sequences_over_cuts_and_missing_tracks():
    p = Point([0.3] * 150, [0.3] * 150, [1.0] * 150)
    prep = Prepared(p, FPS, 0.0)
    # Source time jumps (a cut), then a stretch with no track at all.
    items = [(prep, 0.1 * 0 + i / FPS) for i in range(20)] + [(prep, 1.5 + i / FPS) for i in range(20)] \
        + [(None, 0.0)] * 30
    r = resolve_sequence(items, 1 / FPS)
    assert r.alpha[19] == 1.0 and r.alpha[39] == 1.0                  # a cut does not drain it
    assert r.alpha[-1] == 0.0


def test_smoothing_is_deterministic_and_does_not_change_the_stored_track():
    pt = line(100, noise=0.01)
    before = list(pt.x)
    a = resolve(pt, FPS, 0.0, times(3), smooth=0.7)
    b = resolve(pt, FPS, 0.0, times(3), smooth=0.7)
    assert a.x == b.x and pt.x == before


def test_choosing_the_hand():
    left = Point([0.3] * 90, [0.5] * 90, [0.9] * 90)
    right = Point([0.7] * 90, [0.5] * 90, [0.9] * 40 + [0.0] * 50)
    tr = Track(FPS, 0.0, {"left_palm": left, "right_palm": right})
    assert pick_hand(tr, "right", "palm", 0, 3) == "right_palm"
    assert pick_hand(tr, "any", "palm", 0, 3) == "left_palm"          # found for longer
    assert pick_hand(tr, "any", "palm", 0, 1) in ("left_palm", "right_palm")


def test_the_stored_form_round_trips_and_is_checked():
    tr = Track(30, 1.5, {"face": Point([0.5, 0.51], [0.4, 0.4], [0.9, 0.8], [0.3, 0.3]),
                         "right_palm": Point([0.1, 0.2], [0.2, 0.2], [1, 1])}, "test", True)
    data = tr.to_json(["face"])
    assert list(data["points"]) == ["face"] and data["swap_hands"] and data["start"] == 1.5
    back = Track.from_json(data)
    assert back.points["face"].s == [0.3, 0.3] and back.swap_hands
    assert check_track_data(data) == []
    bad = {"fps": 30, "points": {"face": {"x": [1], "y": [1, 2], "c": [1]}, "elbow": {"x": [], "y": [], "c": []}}}
    problems = check_track_data(bad)
    assert any("same length" in p for p in problems) and any("elbow" in p for p in problems)


# ---- MediaPipe results -> points (stand-ins for its result objects) ---------------------

NS = types.SimpleNamespace


def lm(x, y):
    return NS(x=x, y=y, z=0.0)


def hand_marks(cx, cy):
    marks = [lm(cx, cy) for _ in range(21)]
    marks[0] = lm(cx, cy + 0.1)
    marks[8] = lm(cx, cy - 0.12)
    marks[4] = lm(cx - 0.05, cy - 0.03)
    return marks


def result_with(hands):
    return NS(hand_landmarks=[m for m, _ in hands], handedness=[[NS(category_name=n, score=s)] for _, (n, s) in
                                                                  [(m, h) for m, h in hands]])


def test_frame_points_from_mediapipe_results():
    hands = NS(hand_landmarks=[hand_marks(0.3, 0.6), hand_marks(0.7, 0.5)],
               handedness=[[NS(category_name="Left", score=0.9)], [NS(category_name="Right", score=0.8)]])
    face = NS(detections=[NS(bounding_box=NS(origin_x=300, origin_y=100, width=200, height=240),
                             categories=[NS(score=0.95)])])
    found = frame_points(hands, face, None, 1000, 1000)
    assert found["left_index_tip"][:3] == (0.3, pytest.approx(0.48), 0.9)
    assert found["right_wrist"][:2] == (0.7, pytest.approx(0.6))
    assert found["left_palm"][0] == pytest.approx(0.3)
    assert found["face"][:3] == (pytest.approx(0.4), pytest.approx(0.22), 0.95)
    assert found["face"][3] == pytest.approx(0.2)
    # No pose model: the body is estimated from the face (below it, wider) with less confidence.
    assert found["body"][1] > found["face"][1] and found["body"][3] == pytest.approx(0.56)
    assert found["body"][2] < found["face"][2]
    swapped = frame_points(hands, None, None, 1000, 1000, swap=True)
    assert swapped["right_index_tip"][0] == 0.3 and "face" not in swapped


def test_two_hands_called_the_same_keep_the_surer_one():
    hands = NS(hand_landmarks=[hand_marks(0.3, 0.6), hand_marks(0.7, 0.5)],
               handedness=[[NS(category_name="Right", score=0.6)], [NS(category_name="Right", score=0.9)]])
    found = frame_points(hands, None, None, 100, 100)
    assert found["right_palm"][0] == pytest.approx(0.7) and "left_palm" not in found


def test_a_pose_model_gives_the_body():
    pose = NS(pose_landmarks=[[lm(0, 0)] * 11 + [lm(0.6, 0.4), lm(0.4, 0.4)] + [lm(0, 0)] * 10
                              + [lm(0.58, 0.8), lm(0.42, 0.8)] + [lm(0, 0)] * 8])
    for q in pose.pose_landmarks[0]:
        q.visibility = 0.9
    found = frame_points(None, None, pose, 1000, 1000)
    assert found["body"][:2] == (pytest.approx(0.5), pytest.approx(0.6))
    assert found["body"][3] == pytest.approx(0.2 * 1.4)


# ---- the detector run, with a stand-in MediaPipe ---------------------------------------------

class FakeLandmarker:
    """Returns a hand moving left to right, lost for a while, and records its use."""
    log = []
    lose_hands = False

    def __init__(self, kind, options):
        self.kind, self.options, self.n = kind, options, 0

    @classmethod
    def create_from_options(cls, options):
        return cls(cls.kind, options)

    def detect_for_video(self, image, ts):
        FakeLandmarker.log.append((self.kind, ts, image.shape))
        i = ts / 1000                                                  # 0.1 per second
        if self.kind == "hand":
            if FakeLandmarker.lose_hands or 1.0 <= ts / 1000 < 1.5:
                return NS(hand_landmarks=[], handedness=[])
            return NS(hand_landmarks=[hand_marks(0.1 + 0.1 * i, 0.5)],
                      handedness=[[NS(category_name="Right", score=0.9)]])
        return NS(detections=[NS(bounding_box=NS(origin_x=10, origin_y=10, width=20, height=20),
                                 categories=[NS(score=0.8)])])

    def close(self):
        FakeLandmarker.log.append((self.kind, "closed", None))


def make_fake_mediapipe(monkeypatch):
    FakeLandmarker.log = []
    mp = types.ModuleType("mediapipe")
    mp.__version__ = "9.9.9"
    mp.ImageFormat = NS(SRGB="SRGB")
    mp.Image = lambda image_format, data: NS(shape=data.shape, data=data)
    base = lambda **kw: NS(**kw)  # noqa: E731

    def landmarker(kind):
        cls = type(f"Fake{kind}", (FakeLandmarker,), {"kind": kind})
        return cls
    vision = NS(RunningMode=NS(VIDEO="VIDEO"), HandLandmarker=landmarker("hand"),
                FaceDetector=landmarker("face"), PoseLandmarker=landmarker("pose"),
                HandLandmarkerOptions=lambda **kw: NS(**kw), FaceDetectorOptions=lambda **kw: NS(**kw),
                PoseLandmarkerOptions=lambda **kw: NS(**kw))
    python = types.ModuleType("mediapipe.tasks.python")
    python.BaseOptions, python.vision = base, vision
    tasks = types.ModuleType("mediapipe.tasks")
    tasks.python = python
    mp.tasks = tasks
    for name, mod in (("mediapipe", mp), ("mediapipe.tasks", tasks), ("mediapipe.tasks.python", python)):
        monkeypatch.setitem(sys.modules, name, mod)
    return mp


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "hand.task").write_bytes(b"x")
    (tmp_path / "face.tflite").write_bytes(b"y")
    return {"tracking": {"hand_model": str(tmp_path / "hand.task"),
                         "face_model": str(tmp_path / "face.tflite"), "fps": 10}}


def test_status_says_what_is_missing(tmp_path, monkeypatch, cfg):
    monkeypatch.setitem(sys.modules, "mediapipe", None)                # "not installed"
    st = tracking.status(cfg)
    assert not st["available"] and "python -m pip install mediapipe" in st["problems"][0]
    make_fake_mediapipe(monkeypatch)
    st = tracking.status(cfg)
    assert st["available"] and st["hands"] and st["face"] and not st["pose"] and st["problems"] == []
    st = tracking.status({"tracking": {"hand_model": str(tmp_path / "nope.task")}})
    assert not st["available"] and "was not found" in " ".join(st["problems"])
    st = tracking.status({})
    assert not st["available"] and "No hand model yet" in " ".join(st["problems"])


def test_detect_video_fills_a_track_from_the_detector(tmp_path, monkeypatch, cfg):
    make_fake_mediapipe(monkeypatch)
    video = synthetic.make_video(tmp_path / "talk.mp4", width=360, height=640, duration=3.0)
    progress = []
    rep = NS(progress=lambda p, **kw: progress.append(p))
    track = tracking.detect_video(video, cfg, names=["right_index_tip", "face", "body"], reporter=rep)
    assert track.fps == 10 and track.source == "mediapipe 9.9.9"
    pt = track.points["right_index_tip"]
    assert len(pt) >= 30
    assert pt.c[0] == pytest.approx(0.9) and pt.x[0] == pytest.approx(0.1, abs=0.01)
    assert pt.y[0] == pytest.approx(0.5 - 0.12)
    assert pt.x[20] == pytest.approx(0.3, abs=0.01)
    assert all(pt.c[i] == 0 for i in range(10, 15))                   # not found: confidence 0
    assert track.points["face"].s[0] == pytest.approx(20 / 540, abs=1e-3)   # frames are scaled to 960 tall: 540 wide
    assert track.points["body"].c[0] < track.points["face"].c[0]
    assert progress and progress[-1] == 1.0
    # The detector got upright, 960-tall RGB frames, with rising timestamps; it was closed.
    calls = [c for c in FakeLandmarker.log if c[1] != "closed"]
    assert {c[2][0] for c in calls} == {960} and calls[0][1] == 0
    stamps = [c[1] for c in calls if c[0] == "hand"]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
    assert [c[0] for c in FakeLandmarker.log if c[1] == "closed"].count("hand") == 1


def test_detect_only_the_wanted_time_ranges(tmp_path, monkeypatch, cfg):
    make_fake_mediapipe(monkeypatch)
    video = synthetic.make_video(tmp_path / "talk.mp4", width=360, height=640, duration=4.0)
    track = tracking.detect_video(video, cfg, ranges=[(0.5, 1.0), (2.5, 3.0)], names=["right_palm"])
    pt = track.points["right_palm"]
    assert track.start == 0.5
    assert pt.c[0] > 0 and pt.c[3] > 0                                 # inside the first range
    assert all(c == 0 for c in pt.c[7:18])                             # between the ranges: nothing
    assert pt.c[20] > 0                                                # the second range
    assert tracking.merge_ranges([(1, 2), (2.2, 3), (6, 7)]) == [(1, 3), (6, 7)]


def test_detect_can_be_cancelled_and_explains_what_is_missing(tmp_path, monkeypatch, cfg):
    make_fake_mediapipe(monkeypatch)
    video = synthetic.make_video(tmp_path / "talk.mp4", width=360, height=640, duration=3.0)
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        tracking.detect_video(video, cfg, cancel=stop)
    monkeypatch.setitem(sys.modules, "mediapipe", None)
    with pytest.raises(EditorError, match="pip install mediapipe"):
        tracking.detect_video(video, cfg)
    make_fake_mediapipe(monkeypatch)
    with pytest.raises(EditorError, match="No hand model"):
        tracking.detect_video(video, {"tracking": {}})
    with pytest.raises(EditorError, match="range is empty"):
        tracking.detect_video(video, cfg, ranges=[(9, 10)])
