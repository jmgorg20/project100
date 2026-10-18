"""`polish` (edit, render, check, fix once, sidecar) and `polish-watch` (inbox -> outbox / failed,
half-copied files, restarts, one job at a time)."""

import json
import threading
import time
from pathlib import Path

import pytest

from autoedit import ai_edit, polish, qc
from autoedit.polish_watch import Watcher
from autoedit.project import load_project, media_from_file, new_project, save_project
from autoedit.project_render import render_project
from tests.test_ai import talk  # noqa: F401  (fixture)
from tests.test_qc import mp4


@pytest.fixture
def cfg(tmp_path):
    from autoedit.config import load_config
    c = load_config()
    c["output"]["folder"] = str(tmp_path / "out")
    c["work_folder"] = str(tmp_path / "work")
    c["ai"]["cache_folder"] = str(tmp_path / "cache")
    c["output"]["encoder_speed"] = "ultrafast"
    c["presets_folder"] = ""
    return c


def fake_edit(loud=False, broken=False, calls=None):
    """Stands in for the AI edit: the video as is, one caption, rendered. `loud`: a music track
    that clips (normalising off); `broken`: the first render is cut short (a damaged file)."""
    def run(video, cfg, instruction="", photos=(), provider=None, model=None, render=True, output=None,
            reporter=None, cancel=None, preset=None, format=None, inputs=None, **kw):
        if calls is not None:
            calls.append({"video": str(video), "preset": preset, "format": format, "instruction": instruction,
                          "inputs": inputs})
        output = Path(output)
        p = new_project(Path(video).stem, normalize_audio=not loud)
        m = media_from_file(video, "m1")
        p["media"].append(m)
        d = round(m["duration"], 3)
        p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": d,
                                    "in": 0, "out": d}]
        p["tracks"][3]["clips"] = [{"id": "t1", "type": "caption", "start": 0.2, "duration": 1.0, "style": "classic",
                                    "words": [{"text": "Kumusta", "start": 0, "end": 0.5}]}]
        if loud:
            p["tracks"][0]["clips"][0]["volume"] = 4.0
        project_file = save_project(p, output.with_suffix(".project.json"))
        render_project(p, output, export={"crf": 28, "encoder_speed": "ultrafast", "audio_bitrate": "96k"})
        if broken:
            data = output.read_bytes()
            output.write_bytes(data[: len(data) // 3])
        return {"output": str(output), "project": str(project_file),
                "summary": {"headline": "Mabilis na edit.", "details": ["Cut 2 pauses."], "format": format or "talking_head"}}
    return run


def test_polish_writes_video_project_and_sidecar(tmp_path, cfg, monkeypatch):
    video = mp4(tmp_path / "talk.mp4", seconds=2.0, size="720x1280")
    calls = []
    monkeypatch.setattr(ai_edit, "ai_edit_video", fake_edit(calls=calls))
    out = tmp_path / "outbox"
    side = polish.polish(video, cfg, preset="viral_tiktok", out_folder=out, instruction="mabilis")
    assert side["status"] == "ok", side["qc"]["failed"]
    assert calls[0]["preset"] == "viral_tiktok" and calls[0]["format"] is None
    assert Path(side["output"]) == out / "talk.mp4" and Path(side["output"]).exists()
    assert Path(side["project"]).exists() and load_project(side["project"])
    on_disk = json.loads((out / "talk.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "ok" and on_disk["preset"] == "viral_tiktok"
    assert {c["id"] for c in on_disk["qc"]["checks"]} == set(qc.LABELS)
    assert "Not checked" in on_disk["opinions"]["note"] and on_disk["opinions"]["headline"] == "Mabilis na edit."
    assert not (out / ".polishing").exists()
    # A second polish of the same name never overwrites the first.
    side2 = polish.polish(video, cfg, out_folder=out)
    assert Path(side2["output"]).name == "talk_2.mp4"


def test_clipping_is_fixed_and_rendered_again(tmp_path, cfg, monkeypatch):
    video = mp4(tmp_path / "loud.mp4", seconds=2.0, size="720x1280", audio="aevalsrc='0.9*sin(2*PI*330*t)':s=48000")
    monkeypatch.setattr(ai_edit, "ai_edit_video", fake_edit(loud=True))
    side = polish.polish(video, cfg, out_folder=tmp_path / "o")
    [retry] = side["retries"]
    assert "clipping" in retry["failed"] and "clipping" not in retry["still_failed"]
    assert any("sound" in a for a in retry["actions"])
    assert side["status"] in ("ok", "warnings")
    assert load_project(side["project"])["settings"]["audio"]["normalize"] is True


def test_a_damaged_render_is_rendered_again(tmp_path, cfg, monkeypatch):
    video = mp4(tmp_path / "talk.mp4", seconds=2.0, size="720x1280")
    monkeypatch.setattr(ai_edit, "ai_edit_video", fake_edit(broken=True))
    side = polish.polish(video, cfg, out_folder=tmp_path / "o")
    assert side["retries"] and "valid_mp4" in side["retries"][0]["failed"]
    assert side["status"] == "ok"


def test_no_retry_and_no_time_left(tmp_path, cfg, monkeypatch):
    video = mp4(tmp_path / "talk.mp4", seconds=2.0, size="720x1280")
    monkeypatch.setattr(ai_edit, "ai_edit_video", fake_edit(broken=True))
    side = polish.polish(video, cfg, out_folder=tmp_path / "a", retry=False)
    assert side["status"] == "failed" and not side["retries"] and "valid_mp4" in side["error"]
    side = polish.polish(video, cfg, out_folder=tmp_path / "b", max_minutes=0)
    assert side["status"] == "failed" and "no time left" in side["retries"][0]["skipped"]


def test_fix_for_retry_removes_graphics_on_the_face_but_not_locked_ones():
    p = new_project("x")
    p["tracks"].insert(2, {"id": "graphics", "kind": "graphics", "name": "Graphics", "clips": [
        {"id": "a", "type": "graphic", "template": "stamp", "start": 0, "duration": 1, "params": {"text": "x"}, "x": 0.5, "y": 0.3},
        {"id": "b", "type": "graphic", "template": "stamp", "start": 2, "duration": 1, "params": {"text": "x"}, "x": 0.5, "y": 0.3,
         "locked": True}]})
    checks = [{"id": "face", "ok": False, "details": {"clips": ["a", "b"]}}, {"id": "black_frames", "ok": False, "details": {}}]
    fixed, actions = polish.fix_for_retry(p, checks)
    assert [c["id"] for c in fixed["tracks"][2]["clips"]] == ["b"] and "removed 1 graphic" in actions[0]
    assert polish.fix_for_retry(p, [{"id": "black_frames", "ok": False, "details": {}}]) == (None, [])


# ---------------------------------------------------------------- the watch folder

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def fake_polish(status="ok", record=None, fail=None, sleep=0.0, active=None):
    """Stands in for polish(): writes the outputs a real one writes."""
    def run(path, cfg, preset=None, format=None, out_folder=None, instruction="", inputs=None, unique=True, **kw):
        if active is not None:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        try:
            if record is not None:
                record.append({"path": str(path), "preset": preset, "format": format, "instruction": instruction,
                               "inputs": inputs})
            if sleep:
                time.sleep(sleep)
            if fail:
                raise fail
            names = polish.output_names(out_folder, Path(path).stem, unique)
            names["video"].write_bytes(b"mp4")
            p = new_project("x")
            p["media"].append({"id": "m1", "kind": "video", "path": str(path), "duration": 1, "width": 10,
                               "height": 10, "has_audio": False})
            p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": 1,
                                        "in": 0, "out": 1}]
            save_project(p, names["project"])
            side = {"status": status, "input": str(path), "output": str(names["video"]),
                    "project": str(names["project"]), "error": "Quality checks failed: valid_mp4" if status == "failed" else None}
            polish.write_json(names["sidecar"], side)
            return side
        finally:
            if active is not None:
                active["now"] -= 1
    return run


def folders(tmp_path):
    return {k: tmp_path / "robot" / k for k in ("inbox", "outbox", "failed", "done")}


def watcher(tmp_path, cfg, polish_fn, clock=None, **kw):
    f = folders(tmp_path)
    return Watcher(cfg, f["inbox"], f["outbox"], f["failed"], f["done"], settle=10, clock=clock or Clock(),
                   polish_fn=polish_fn, **kw), f


def test_half_copied_and_temporary_files_wait(tmp_path, cfg):
    clock, record = Clock(), []
    w, f = watcher(tmp_path, cfg, fake_polish(record=record), clock=clock)
    (f["inbox"] / "a.mp4").write_bytes(b"x" * 10)
    (f["inbox"] / "b.mp4.part").write_bytes(b"x")
    (f["inbox"] / "c.crdownload").write_bytes(b"x")
    (f["inbox"] / "notes.txt").write_text("hi")
    (f["inbox"] / ".hidden.mp4").write_bytes(b"x")
    assert w.once() == []                                   # first look: just noted
    clock.t += 5
    with open(f["inbox"] / "a.mp4", "ab") as fh:          # still being copied
        fh.write(b"y" * 10)
    assert w.once() == []
    clock.t += 9
    assert w.once() == []                                   # unchanged for 9 s only
    clock.t += 2
    [r] = w.once()
    assert r["status"] == "ok" and [Path(x["path"]).name for x in record] == ["a.mp4"]
    assert sorted(p.name for p in f["inbox"].iterdir() if p.is_file()) == [".hidden.mp4", "b.mp4.part", "c.crdownload", "notes.txt"]


def ready_now(w, f, name="talk.mp4", data=b"video"):
    (f["inbox"] / name).write_bytes(data)
    w.once()
    w.clock.t += 11
    return w.once()


def test_success_goes_to_outbox_and_the_original_to_done(tmp_path, cfg):
    w, f = watcher(tmp_path, cfg, fake_polish())
    [r] = ready_now(w, f)
    assert r["status"] == "ok"
    assert sorted(p.name for p in f["outbox"].iterdir()) == ["talk.json", "talk.mp4", "talk.project.json"]
    assert (f["done"] / "talk.mp4").exists() and not list(f["inbox"].glob("*.mp4"))
    side = json.loads((f["outbox"] / "talk.json").read_text(encoding="utf-8"))
    assert side["input"] == str(f["done"] / "talk.mp4")
    assert load_project(f["outbox"] / "talk.project.json")["media"][0]["path"] == str(f["done"] / "talk.mp4")
    assert not list((f["inbox"] / ".processing").iterdir())


def test_an_error_goes_to_failed_with_a_log(tmp_path, cfg):
    from autoedit.errors import EditorError
    w, f = watcher(tmp_path, cfg, fake_polish(fail=EditorError("The video has no sound.")))
    [r] = ready_now(w, f)
    assert r["status"] == "failed"
    assert (f["failed"] / "talk.mp4").exists()
    log = (f["failed"] / "talk.log").read_text(encoding="utf-8")
    assert "The video has no sound." in log and "polishing talk.mp4" in log
    side = json.loads((f["failed"] / "talk.json").read_text(encoding="utf-8"))
    assert side["status"] == "failed" and side["error"] == "The video has no sound."
    assert not list(f["outbox"].iterdir())
    # A bug (not an EditorError) is caught the same way, with the traceback in the log.
    w2, f2 = watcher(tmp_path / "b", cfg, fake_polish(fail=ZeroDivisionError("oops")))
    ready_now(w2, f2)
    assert "Traceback" in (f2["failed"] / "talk.log").read_text(encoding="utf-8")


def test_failed_checks_leave_nothing_in_the_outbox(tmp_path, cfg):
    w, f = watcher(tmp_path, cfg, fake_polish(status="failed"))
    [r] = ready_now(w, f)
    assert r["status"] == "failed" and not list(f["outbox"].iterdir())
    names = {p.name for p in f["failed"].iterdir()}
    # the original, why, the log, and the rejected render with its project (to look at)
    assert names == {"talk.mp4", "talk.json", "talk.log", "talk.rejected.mp4", "talk.rejected.project.json"}
    assert json.loads((f["failed"] / "talk.json").read_text(encoding="utf-8"))["error"].startswith("Quality checks failed")


def test_job_file_settings(tmp_path, cfg):
    record = []
    w, f = watcher(tmp_path, cfg, fake_polish(record=record), preset="meme")
    (f["inbox"] / "b1.mp4").write_bytes(b"b")
    (f["inbox"] / "vo.job.json").write_text(json.dumps({
        "preset": "faceless_automation", "instruction": "Tara na",
        "inputs": {"broll": ["b1.mp4", "/abs/b2.jpg"], "items": ["Una"]}}), encoding="utf-8")
    (f["inbox"] / "vo.wav").write_bytes(b"audio")
    (f["inbox"] / "plain.mp4").write_bytes(b"v")
    w.once()
    w.clock.t += 11
    w.once()
    by = {Path(r["path"]).name: r for r in record}
    assert by["vo.wav"]["preset"] == "faceless_automation" and by["vo.wav"]["instruction"] == "Tara na"
    assert by["vo.wav"]["inputs"]["broll"] == [str((f["inbox"] / "b1.mp4").resolve()), "/abs/b2.jpg"]
    assert by["vo.wav"]["inputs"]["items"] == ["Una"]
    assert by["plain.mp4"]["preset"] == "meme"
    assert (f["done"] / "vo.job.json").exists()


def test_restart_keeps_finished_work_and_redoes_the_rest(tmp_path, cfg):
    record = []
    w, f = watcher(tmp_path, cfg, fake_polish(record=record))
    proc = f["inbox"] / ".processing"
    # 1) finished just before the stop: its sidecar is in the outbox
    (proc / "done_one.mp4").write_bytes(b"v")
    (f["outbox"] / "done_one.mp4").write_bytes(b"mp4")
    polish.write_json(f["outbox"] / "done_one.json", {"status": "ok", "input": str(proc / "done_one.mp4"),
                                                       "output": str(f["outbox"] / "done_one.mp4")})
    # 2) stopped half way: polished again
    (proc / "half.mp4").write_bytes(b"v")
    # 3) crashed the editor three times already: given up
    (proc / "crasher.mp4").write_bytes(b"v")
    (proc / "crasher.mp4.attempts").write_text("3")
    notes = w.recover()
    assert any("already polished" in n for n in notes) and any("failed after 3" in n for n in notes)
    assert (f["done"] / "done_one.mp4").exists() and (f["failed"] / "crasher.mp4").exists()
    assert "Stopped after 3 attempts" in (f["failed"] / "crasher.log").read_text(encoding="utf-8")
    w.once()
    assert [Path(r["path"]).name for r in record] == ["half.mp4"]
    assert (f["outbox"] / "half.mp4").exists() and (f["done"] / "half.mp4").exists()


def test_one_job_at_a_time_across_watchers(tmp_path, cfg):
    active = {"now": 0, "max": 0}
    ws = []
    for name in ("one", "two"):
        w, f = watcher(tmp_path / name, cfg, fake_polish(sleep=0.4, active=active))
        for k in range(2):
            (f["inbox"] / f"v{k}.mp4").write_bytes(b"v")
        w.once()
        w.clock.t += 11
        ws.append(w)
    threads = [threading.Thread(target=w.once) for w in ws]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert active["max"] == 1
    assert sum(len(list(w.outbox.glob("*.mp4"))) for w in ws) == 4


def test_cli_polish_watch_once_and_polish(tmp_path, cfg):
    import subprocess
    import sys
    from tests.test_ai import PROJECT_DIR
    conf = tmp_path / "cfg.yaml"
    conf.write_text(f"work_folder: '{(tmp_path / 'work').as_posix()}'\n"
                    f"polish: {{inbox: '{(tmp_path / 'in').as_posix()}', outbox: '{(tmp_path / 'outb').as_posix()}', "
                    f"failed: '{(tmp_path / 'bad').as_posix()}', done: '{(tmp_path / 'ok').as_posix()}', "
                    "settle_seconds: 0}\n", encoding="utf-8")
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "broken.mp4").write_text("not a video")
    run = subprocess.run([sys.executable, str(PROJECT_DIR / "editor.py"), "--config", str(conf), "--json",
                          "polish-watch", "--once", "--settle", "0"], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.splitlines()[-1])
    assert result["type"] == "result" and result["items"] == []            # first look: only noted
    run = subprocess.run([sys.executable, str(PROJECT_DIR / "editor.py"), "--config", str(conf), "polish",
                          str(tmp_path / "in" / "broken.mp4"), "--out", str(tmp_path / "outb")],
                         capture_output=True, text=True, timeout=300)
    assert run.returncode != 0 and "broken.mp4" in (run.stderr + run.stdout)


def test_polish_a_real_ai_edit_end_to_end(talk, cfg, monkeypatch):  # noqa: F811  (the fixture)
    """The real AI edit (stand-in AI and Whisper) with a preset, the real render and the real
    checks: a synthetic talking video comes out clean."""
    from tests.test_ai import photo_plan, scripted
    tmp, video, photo, _ = talk
    fake, calls = scripted([photo_plan(cfg)])
    monkeypatch.setattr(ai_edit, "ask_json", fake)
    side = polish.polish(video, cfg, preset="podcast_clips", out_folder=tmp / "outbox",
                         inputs={"photos": [str(photo)]})
    failed = [c for c in side["qc"]["checks"] if not c["ok"]]
    assert side["status"] == "ok", failed
    assert side["preset"] == "podcast_clips" and "Keep the speaker" in calls[0]
    assert load_project(side["project"])["meta"]["preset"] == "podcast_clips"
    assert json.loads((tmp / "outbox" / "talk.json").read_text(encoding="utf-8"))["output"] == side["output"]
