"""Per-sound levels in the real export: the export with sound effects minus the same export with them
Usage: python scripts/sfx_levels.py RUNS OUT  (RUNS holds g_auto/ and g_off/ from scripts/acceptance.py
run with --sfx auto and --sfx off; OUT gets levels.md)
off (aligned to the sample and gain-matched on the stretches with no sound), against the noise floor
of that difference where no sound plays."""
import json, re, subprocess, sys
import numpy as np
S, OUT = sys.argv[1], sys.argv[2]
R = 48000


def pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(R), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


a, b = pcm(f"{S}/g_auto/edit.mp4"), pcm(f"{S}/g_off/edit.mp4")
seg = slice(R, 6 * R)
lag = int(np.argmax(np.correlate(a[seg], b[R - 400:6 * R + 400], "valid"))) - 400
b = np.roll(b, lag)
n = min(len(a), len(b)) - 1000
a, b = a[1000:n], b[1000:n]
off = 1000 / R
proj = json.load(open(f"{S}/g_auto/edit.project.json"))
media = {m["id"]: m["path"] for m in proj["media"]}
clips = sorted((c for t in proj["tracks"] if t.get("role") == "sfx" for c in t["clips"]), key=lambda c: c["start"])
busy = np.zeros(len(a), bool)
for c in clips:
    busy[max(0, int((c["start"] - off - 0.1) * R)):int((c["start"] - off + c["duration"] + 0.6) * R)] = True
gain = float(np.dot(a[~busy], b[~busy]) / np.dot(b[~busy], b[~busy]))
d = a - gain * b
rms = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)          # noqa: E731
peak = lambda x: 20 * np.log10(np.abs(x).max() + 1e-9)                 # noqa: E731
W = int(0.15 * R)
floor = float(np.median([rms(d[i:i + W]) for i in range(0, len(d) - W, W) if not busy[i:i + W].any()]))
rows = []
for c in clips:
    i = int((c["start"] - off) * R)
    name = re.sub(r"-v\d+$", "", media[c["media"]].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0])
    w = int(max(c["duration"], 0.04) * R)
    rows.append((c["start"], name, c["volume"], rms(b[i:i + W] * gain), peak(d[i:i + w]), rms(d[i:i + w])))
lines = [f"Lag between the two exports: {lag} samples (aligned). Gain match: {gain:.3f}. "
         f"Noise floor of the difference where no sound plays: {floor:.1f} dB RMS.", "",
         "| time | sound | volume | voice there, RMS dB | sound, peak dB | sound, RMS dB | above floor |",
         "|---|---|---|---|---|---|---|"]
for t, name, vol, voice, pk, r in rows:
    lines.append(f"| {t:.2f}s | {name} | {vol} | {voice:.1f} | {pk:.1f} | {r:.1f} | {r - floor:+.1f} dB |")
above = sum(1 for r in rows if r[5] - floor > 6)
lines += ["", f"{above} of {len(rows)} sounds are more than 6 dB above the floor in the exported audio.",
          f"Loudest sound peak {max(r[4] for r in rows):.1f} dB; the voice's loudest 150 ms "
          f"{max(rms(b[i:i + W] * gain) for i in range(0, len(b) - W, W)):.1f} dB RMS."]
open(f"{OUT}/levels.md", "w").write("\n".join(lines) + "\n")
d.astype(np.float32).tofile(f"{S}/sfx_only.f32")             # the sounds alone, for a waveform picture
print(lines[0]); print("\n".join(lines[-2:]))
