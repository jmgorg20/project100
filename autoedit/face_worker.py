"""The face finder's own process (started by autoedit/face_detect.py, never imported by the edit).

    python -m autoedit.face_worker --self-test OUT.json
    python -m autoedit.face_worker --video VIDEO --fps 4 --ffmpeg FFMPEG [--keyframes 1] OUT.json

It runs on its own so that nothing it does can stop the edit: if OpenCV cannot load (a DLL, numpy or
protobuf conflict), crashes, or hangs, the edit kills this process after its time limit and carries
on with the safe-zone layout. The frames come from FFmpeg (the same FFmpeg the edit uses), not from
OpenCV's own video reader, which on Windows (Media Foundation) can hang on some MP4 files.

It writes OUT.json: {"ok": true, ...} or {"ok": false, "error": ...}, and a line per step on stdout
(the parent puts them in the face finder's log). AUTOEDIT_FACE_SIMULATE=hang|crash|error makes it
hang / crash / fail on purpose (tests; see simulate)."""

import json
import os
import subprocess
import sys
import time

DETECT_W = 360


def say(message):
    print(f"{time.strftime('%H:%M:%S')} worker: {message}", flush=True)


def simulate(where):
    """AUTOEDIT_FACE_SIMULATE=KIND[:WHERE] (tests): KIND hang | crash | error, WHERE selftest or
    detect (the default)."""
    what = os.environ.get("AUTOEDIT_FACE_SIMULATE", "")
    kind, _, at = what.partition(":")
    if kind and (at or "detect") == where:
        say(f"simulating a {kind} ({where})")
        if kind == "hang":
            time.sleep(10 ** 6)
        if kind == "crash":
            os._exit(3)
        raise RuntimeError("simulated failure")


def load_cv2():
    say(f"python {sys.version.split()[0]} at {sys.executable}")
    import numpy
    say(f"numpy {numpy.__version__}")
    import cv2
    cv2.setNumThreads(1)               # OpenCV's own thread pool is not needed for small frames
    say(f"cv2 {cv2.__version__} from {os.path.dirname(cv2.__file__)}")
    base = getattr(getattr(cv2, "data", None), "haarcascades", "") or ""
    path = os.path.join(base, "haarcascade_frontalface_default.xml")
    if not os.path.isfile(path):
        raise RuntimeError("this OpenCV has no built-in face detector (haarcascade_frontalface_default.xml "
                           "is missing)")
    cascade = cv2.CascadeClassifier(path)
    if cascade.empty():
        raise RuntimeError(f"the face detector could not be loaded from {path}")
    return cv2, numpy, cascade


def self_test():
    """Load OpenCV and run the detector once on a tiny frame."""
    simulate("selftest")
    cv2, numpy, cascade = load_cv2()
    frame = numpy.zeros((120, 160), dtype=numpy.uint8)
    cascade.detectMultiScale(cv2.equalizeHist(frame), 1.1, 5)
    say("self-test passed")
    return {"ok": True, "cv2": cv2.__version__, "numpy": numpy.__version__,
            "python": sys.version.split()[0], "executable": sys.executable}


def read_pgm(stream):
    """One frame of FFmpeg's PGM stream (P5 header, 8-bit), or None at the end."""
    fields = []
    while len(fields) < 4:
        token = b""
        while True:
            c = stream.read(1)
            if not c:
                return None
            if c.isspace():
                if token:
                    break
                continue
            token += c
        fields.append(token)
    if fields[0] != b"P5":
        raise RuntimeError(f"unexpected frame format from FFmpeg: {fields[0]!r}")
    w, h = int(fields[1]), int(fields[2])
    data = stream.read(w * h)
    if len(data) < w * h:
        return None
    return w, h, data


def detect(video, fps, ffmpeg, keyframes=False):
    simulate("detect")
    cv2, numpy, cascade = load_cv2()
    cmd = [ffmpeg, "-v", "error", "-nostdin", *(["-skip_frame", "nokey"] if keyframes else []), "-i", video, "-an", "-sn",
           "-vf", f"fps={fps},scale={DETECT_W}:-2,format=gray", "-f", "image2pipe", "-vcodec", "pgm", "-"]
    say("frames from FFmpeg: " + " ".join(cmd[1:]))
    # FFmpeg's messages go to a file, never to a pipe nobody reads (a full pipe would block it)
    err_path = os.environ.get("AUTOEDIT_FACE_FFMPEG_LOG") or os.devnull
    with open(err_path, "ab") as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err)
        raw, n = [], 0
        try:
            while True:
                frame = read_pgm(proc.stdout)
                if frame is None:
                    break
                w, h, data = frame
                gray = cv2.equalizeHist(numpy.frombuffer(data, dtype=numpy.uint8).reshape(h, w))
                found = cascade.detectMultiScale(gray, 1.1, 5, minSize=(int(w * 0.12),) * 2)
                if len(found):
                    x, y, fw, fh = max(found, key=lambda r: r[2] * r[3])
                    raw.append([(x + fw / 2) / w, (y + fh / 2) / h, fw / w])
                else:
                    raw.append(None)
                n += 1
                if n % 40 == 0:
                    say(f"{n} frames looked at")
        finally:
            proc.stdout.close()
            code = proc.wait()
    if code != 0 and not raw:
        raise RuntimeError(f"FFmpeg could not read the video for the face finder (exit {code})")
    say(f"done: {n} frames, a face in {sum(1 for r in raw if r)}")
    return {"ok": True, "fps": fps, "raw": raw, "cv2": cv2.__version__}


def main(argv):
    out = argv[-1]
    try:
        if "--self-test" in argv:
            result = self_test()
        else:
            opt = {argv[i]: argv[i + 1] for i in range(len(argv) - 2) if argv[i].startswith("--")}
            result = detect(opt["--video"], float(opt.get("--fps", 4)), opt.get("--ffmpeg", "ffmpeg"),
                            opt.get("--keyframes") == "1")
    except BaseException as exc:          # report anything (an ImportError from a DLL, numpy ...)
        say(f"failed: {type(exc).__name__}: {exc}")
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    tmp = out + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f)
    os.replace(tmp, out)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
