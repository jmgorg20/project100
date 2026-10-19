"""The Windows graphics bug ("Could not draw the graphics: FFmpeg failed (4294967274): Output file
does not contain any stream ... Invalid argument"): FFmpeg got no picture at all. Here: every file
the graphics cache writes is a valid Windows path, an empty or missing picture is a clear error
for that one graphic (never an FFmpeg pipe with nothing in it), one graphic that fails is left out
with a warning (clip, file, reason) instead of failing the edit, and what the app's drawing window
cannot draw is drawn by the command line renderer when there is one."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from autoedit import PROJECT_DIR, graphics
from autoedit.project import media_from_file, new_project
from autoedit.project_render import render_project
from tests.gfx_helpers import add_graphics_track, graphic, needs_chromium

WIN_CACHE = r"C:\Users\Admin\Documents\project100\work\cache\graphics"
NODE = shutil.which("node")
CAPTURE = (PROJECT_DIR / "desktop" / "graphics" / "capture.mjs").as_uri()


def node(code):
    if not NODE:
        pytest.skip("needs Node.js")
    return subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)


# ---------------------------------------------------------------- the cause, reproduced

def test_ffmpeg_with_no_picture_fails_exactly_like_on_the_users_pc(tmp_path):
    """The user's error is FFmpeg's answer when the frame pipe stays empty."""
    out = tmp_path / "x.mkv.part.mkv"
    run = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", "30",
                          "-c:v", "png", "-i", "-", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra", str(out)],
                         input=b"", capture_output=True)
    assert run.returncode != 0 and b"does not contain any stream" in run.stderr


def test_an_empty_pipe_is_now_a_clear_error_before_ffmpeg(tmp_path):
    out = str(tmp_path / "a.mkv").replace("\\", "/")
    r = node(f"""import {{ openSink, exitText }} from "{CAPTURE}";
const s = openSink("ffmpeg", "{out}", 30);
let msg = "";
try {{ await s.write(Buffer.alloc(0)); }} catch (e) {{ msg += e.message + "|"; }}
try {{ await s.finish(); }} catch (e) {{ msg += e.message + "|"; }}
console.log(JSON.stringify([msg, exitText(4294967274), exitText(1), exitText(null)]));""")
    msg, code, one, stopped = json.loads(r.stdout)
    assert f"an empty frame for {out}" in msg and f"no frames were drawn for {out}" in msg
    assert code == "exit code -22: invalid argument" and one == "exit code 1" and stopped == "it was stopped"


# ---------------------------------------------------------------- Windows paths

@pytest.mark.parametrize("path, problem", [
    (WIN_CACHE + r"\0123456789abcdef01234567.mkv", None),
    (r"C:\Users\Admin\Videos\a:b.mkv", "characters Windows does not allow"),
    (r"C:\Users\Admin\Videos\what?.mkv", "characters Windows does not allow"),
    (r"C:\Users\Admin\Videos\name.", "ends with a dot or a space"),
    (r"C:\Users\Admin\Videos\name ", "ends with a dot or a space"),
    (r"C:\Users\Admin\Videos\CON.mkv", "a name Windows reserves"),
    ("C:\\" + "x" * 270, "characters long"),
])
def test_windows_path_problems_are_found(path, problem):
    found = graphics.windows_path_problems(path)
    assert (not found) if problem is None else any(problem in f for f in found), found


@pytest.mark.parametrize("name, safe", [("a:b?.mkv. ", "a-b-.mkv"), ("CON.txt", "_CON.txt"), ("ok_name.mkv", "ok_name.mkv"),
                                        ("x" * 200, "x" * 80), ("", "file")])
def test_safe_filename(name, safe):
    assert graphics.safe_filename(name) == safe


@pytest.fixture
def red(tmp_path):
    video = tmp_path / "red.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=720x1280:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    p = new_project("g", normalize_audio=False)
    p["media"] = [media_from_file(video, "vid")]
    p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "vid", "start": 0, "duration": 2,
                                "in": 0, "out": 2}]
    return tmp_path, p


def test_every_cache_file_is_a_valid_windows_path(red):
    """The user's own cache folder: the video, its .part file, its sidecar and the jobs file."""
    tmp, p = red
    add_graphics_track(p, [graphic("g1", "stamp", 0, 1, text="Grabe: 3,600?!"),
                           graphic("g2", "pop-heavy", 1, 1, text='"Tatlo" <dalawa> | isa*')])
    for job in graphics.project_jobs(p, tmp, directory=WIN_CACHE):
        for path in (job["out"], job["out"] + ".part.mkv", job["meta"], str(Path(WIN_CACHE) / "jobs-12345-67890.json")):
            assert graphics.windows_path_problems(path) == [], path
        assert job["out"].startswith(WIN_CACHE)


def test_a_cache_folder_that_cannot_be_used_moves_to_the_users_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOEDIT_GRAPHICS_CACHE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "Local"))
    users = tmp_path / "Local" / "AutoEditor" / "graphics"
    monkeypatch.setattr(graphics, "PROJECT_DIR", tmp_path / "Program Files" / "AutoEditor")
    monkeypatch.setattr(graphics, "writable", lambda folder: False)             # read-only install
    assert graphics.cache_dir() == users
    monkeypatch.setattr(graphics, "writable", lambda folder: True)
    assert graphics.cache_dir() == tmp_path / "Program Files" / "AutoEditor" / "work" / "cache" / "graphics"
    monkeypatch.setattr(graphics, "PROJECT_DIR", tmp_path / ("very-long-folder-name-" * 12))   # too long
    assert graphics.cache_dir() == users


def test_writable_is_checked_for_real(tmp_path):
    graphics._WRITABLE.clear()
    assert graphics.writable(tmp_path / "new" / "folder")
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    assert not graphics.writable(blocker / "sub")


# ---------------------------------------------------------------- one graphic never stops the edit

def test_one_graphic_that_fails_is_left_out_with_a_warning(red, monkeypatch, tmp_path, capsys):
    tmp, p = red
    monkeypatch.setenv("AUTOEDIT_GRAPHICS_CACHE", str(tmp_path / "cache"))
    add_graphics_track(p, [graphic("g1", "stamp", 0, 1, text="OK"), graphic("g2", "stamp", 1, 1, text="BAD")])
    bad = next(j for j in graphics.project_jobs(p, tmp) if j["clip"] == "g2")
    events = []

    class Rep:
        def event(self, kind, **data):
            events.append((kind, data))

    def draw(missing, reporter=None, cancel=None):
        good = next(j for j in missing if j["clip"] == "g1")
        Path(good["out"]).parent.mkdir(parents=True, exist_ok=True)
        Path(good["out"]).write_bytes(b"x")
        Path(good["meta"]).write_text("{}")
        return {bad["key"]: "FFmpeg could not write ... (exit code -22: invalid argument)"}
    monkeypatch.setattr(graphics, "draw_jobs", draw)
    failed = graphics.ensure_assets(p, tmp, Rep())
    assert [f["clip"] for f in failed] == ["g2"] and "-22" in failed[0]["error"]
    kind, data = events[0]
    assert kind == "warning" and data["clip"] == "g2" and data["path"] == bad["out"]
    assert bad["out"] in data["message"] and "invalid argument" in data["message"]
    assert "g2" in capsys.readouterr().err


def app_service(answer):
    """A stand-in for the app's drawing window: answers every job with `answer(job)` lines."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            spec = json.loads(self.rfile.read(int(self.headers["content-length"])))
            self.send_response(200)
            self.end_headers()
            for job in spec["jobs"]:
                self.wfile.write((json.dumps(answer(job)) + "\n").encode())
            self.wfile.write(b'{"type":"done"}\n')

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@needs_chromium
def test_what_the_app_window_cannot_draw_is_drawn_from_the_command_line(red, monkeypatch, tmp_path):
    """The user's case: the app's window fails every graphic (empty pictures). The command line
    renderer draws them instead and the video renders with them."""
    tmp, p = red
    monkeypatch.setenv("AUTOEDIT_GRAPHICS_CACHE", str(tmp_path / "cache"))
    add_graphics_track(p, [graphic("g1", "stamp", 0, 1.5, text="OK")])
    server = app_service(lambda job: {"type": "job_error", "key": job["key"],
                                      "message": "the drawing window gave an empty picture for a 600x300 graphic"})
    monkeypatch.setenv("AUTOEDIT_GRAPHICS_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        assert graphics.ensure_assets(p, tmp) == []
    finally:
        server.shutdown()
    assert all(graphics.is_drawn(j) for j in graphics.project_jobs(p, tmp))
    out = render_project(p, tmp / "out.mp4", base_dir=tmp, export={"crf": 30, "encoder_speed": "ultrafast",
                                                                   "audio_bitrate": "96k"})
    assert out.exists()


def test_without_a_fallback_the_edit_still_renders_without_that_graphic(red, monkeypatch, tmp_path):
    tmp, p = red
    monkeypatch.setenv("AUTOEDIT_GRAPHICS_CACHE", str(tmp_path / "cache2"))
    monkeypatch.setattr(graphics, "renderer_command", lambda: None)
    add_graphics_track(p, [graphic("g1", "stamp", 0, 1.5, text="OK")])
    server = app_service(lambda job: {"type": "job_error", "key": job["key"], "message": "no frames were drawn"})
    monkeypatch.setenv("AUTOEDIT_GRAPHICS_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        out = render_project(p, tmp / "out2.mp4", base_dir=tmp, export={"crf": 30, "encoder_speed": "ultrafast",
                                                                        "audio_bitrate": "96k"})
    finally:
        server.shutdown()
    assert out.exists()


@needs_chromium
def test_the_cli_renderer_skips_a_broken_graphic_and_draws_the_rest(red, monkeypatch, tmp_path):
    tmp, p = red
    monkeypatch.setenv("AUTOEDIT_GRAPHICS_CACHE", str(tmp_path / "cache3"))
    add_graphics_track(p, [graphic("g1", "stamp", 0, 1.5, text="OK")])
    jobs = graphics.project_jobs(p, tmp)
    broken = {**jobs[0], "key": "broken", "template": "no-such-template", "clip": "gX",
              "out": str(tmp_path / "cache3" / "broken.mkv"), "meta": str(tmp_path / "cache3" / "broken.json")}
    errors = graphics.draw_jobs([broken, *jobs])
    assert list(errors) == ["broken"] and errors["broken"]
    assert graphics.is_drawn(jobs[0])
