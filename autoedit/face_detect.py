"""Finding the speaker's face with no setup: OpenCV's built-in frontal-face detector.

The graphics keep off the face. MediaPipe tracking (docs/tracking.md) is used when it is set up;
otherwise this light detector runs: OpenCV's Haar cascade, which ships inside the
`opencv-python-headless` package (no model download). It is in requirements.txt; when it is
missing it is installed once on first use (`tracking: auto_install: false` turns that off).

A face is looked for 4 times a second on a small copy of the frame. Boxes much smaller than a
talking head's face, or far from where the face is the rest of the time (a logo on a shirt),
are dropped; gaps are filled from the neighbours; the path is smoothed. The result is the same
face track MediaPipe gives (center x / y and size, as fractions of the frame), so placement
works the same way.
"""

import subprocess
import sys

from .errors import EditorError

PACKAGE = "opencv-python-headless<5"      # 5.x no longer ships the cascades
SAMPLE_FPS = 4.0
DETECT_W = 360


def import_cv2(auto_install=True, reporter=None):
    try:
        import cv2
        if hasattr(cv2, "CascadeClassifier") and cascade_path(cv2):
            return cv2
    except ImportError:
        pass
    if not auto_install:
        raise EditorError("Face detection needs OpenCV: python -m pip install \"opencv-python-headless<5\"")
    if reporter:
        reporter.stage("tracking", "Installing the face finder (once, about 40 MB)")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", PACKAGE],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise EditorError("Could not install the face finder (OpenCV): "
                          + (proc.stderr or proc.stdout).strip()[-300:])
    import importlib
    importlib.invalidate_caches()
    try:
        import cv2
    except ImportError as exc:
        raise EditorError(f"OpenCV was installed but cannot be loaded: {exc}")
    if not cascade_path(cv2):
        raise EditorError("This OpenCV has no built-in face detector (cascades missing).")
    return cv2


def cascade_path(cv2):
    import os
    base = getattr(getattr(cv2, "data", None), "haarcascades", "") or ""
    path = os.path.join(base, "haarcascade_frontalface_default.xml")
    return path if os.path.isfile(path) else None


def detect_face_track(video, cfg=None, reporter=None, cancel=None):
    """The speaker's face over the video as a tracking.Track (point "face": center x / y and size
    as fractions of the frame, confidence 0-1), sampled SAMPLE_FPS times a second."""
    from .errors import Cancelled
    from .tracking import Point, Track
    settings = (cfg or {}).get("tracking") or {}
    cv2 = import_cv2(bool(settings.get("auto_install", True)), reporter)
    cascade = cv2.CascadeClassifier(cascade_path(cv2))
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise EditorError(f"Could not open the video to find the face: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    raw, n = [], 0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled("Cancelled while finding the face.")
            if not cap.grab():
                break
            if n % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                h, w = frame.shape[:2]
                scale = DETECT_W / float(w)
                small = cv2.resize(frame, (DETECT_W, max(1, int(h * scale))))
                gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
                found = cascade.detectMultiScale(gray, 1.1, 5, minSize=(int(DETECT_W * 0.12),) * 2)
                if len(found):
                    x, y, fw, fh = max(found, key=lambda r: r[2] * r[3])
                    raw.append(((x + fw / 2) / DETECT_W, (y + fh / 2) / (h * scale), fw / DETECT_W))
                else:
                    raw.append(None)
            n += 1
    finally:
        cap.release()
    xs, ys, cs, ss = clean_samples(raw)
    track = Track(fps / step, 0.0, {"face": Point(xs, ys, cs, ss)}, source="opencv-haar")
    track.notes.append(f"Face found by the built-in detector in {sum(1 for r in raw if r)} of {len(raw)} samples.")
    return track


def clean_samples(raw):
    """(x, y, confidence, size) lists from the raw detections ((x, y, size) or None per sample):
    boxes that are not the speaker's face are dropped (much smaller, or far from where the face
    usually is: a logo on a shirt), short gaps filled, the path smoothed; long gaps keep the usual
    position at a lower confidence."""
    from statistics import median
    hits = [r for r in raw if r]
    if len(hits) < max(3, len(raw) // 5):
        raise EditorError("The face was not found in enough of the video.")
    mx, my, ms = (median(r[i] for r in hits) for i in range(3))
    clean = [r if r and r[2] >= ms * 0.6 and abs(r[0] - mx) < 0.3 and abs(r[1] - my) < 0.25 else None
             for r in raw]
    filled = fill_gaps(clean, max_gap=int(SAMPLE_FPS * 1.5))
    xs, ys, cs, ss = [], [], [], []
    for k, r in enumerate(filled):
        window = [v for v in filled[max(0, k - 2):k + 3] if v]
        if r is None or not window:
            # not found here for long: the speaker is assumed where they usually are (a talking
            # head barely moves), so graphics still keep off that spot
            xs.append(mx), ys.append(my), ss.append(ms), cs.append(0.55)
            continue
        xs.append(sum(v[0] for v in window) / len(window))
        ys.append(sum(v[1] for v in window) / len(window))
        ss.append(sum(v[2] for v in window) / len(window))
        cs.append(0.9 if clean[k] else 0.6)
    return xs, ys, cs, ss


def fill_gaps(samples, max_gap):
    """Short runs of misses filled by straight lines between the hits around them."""
    out = list(samples)
    k = 0
    while k < len(out):
        if out[k] is not None:
            k += 1
            continue
        j = k
        while j < len(out) and out[j] is None:
            j += 1
        before = out[k - 1] if k > 0 else None
        after = out[j] if j < len(out) else None
        if j - k <= max_gap and (before or after):
            a, b = before or after, after or before
            for m in range(k, j):
                f = (m - k + 1) / (j - k + 1)
                out[m] = tuple(a[i] + (b[i] - a[i]) * f for i in range(3))
        k = j
    return out
