"""What a client may ask for, checked before anything is queued; the payload a worker receives; and
the job as the client sees it (status, progress, results with signed links and their expiry).

Job kinds:
    polish  the AI edit with a preset and a format, rendered and checked (autoedit/polish.py)
    render  render a project (e.g. after the client fixed captions or approved a storyboard); its
            media are references: "upload:<id>" (the client's uploads) or "output:<id>" (files of
            the client's earlier jobs)
"""

import time

from . import clients, jobqueue, security
from .db import dumps, loads, now

KINDS = ("polish", "render")
PROVIDERS = ("groq", "anthropic")
MAX_INSTRUCTION = 2000
MAX_ITEMS = 20
MAX_INPUT_FILES = 20
OUTPUT_NAMES = ("video", "project", "sidecar", "plan")
MAX_ASSETS = 200
CONTENT_TYPES = {"video": "video/mp4", "project": "application/json", "sidecar": "application/json",
                 "plan": "application/json"}
FEATURE_OF = {"format": "formats", "gpu": "gpu", "provider": "ai_planner"}
# Shown with every result: the edit (cuts, captions, effects, music) was planned by AI. Platforms ask
# creators to disclose realistic AI-made or AI-altered content; the person decides what to post.
AI_LABEL = {"edited_with_ai": True,
            "text": "Edited with AI: an AI planned the cuts, captions and effects. Check it before you post, and use "
                    "the platform's AI label if the video shows realistic people, places or events that were "
                    "made or changed by AI."}


class JobError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


MAX_OWN_PRESETS = 50
MAX_PRESET_BYTES = 8192


def own_presets(t, client_id):
    return {r["id"]: loads(r["body"], {}) for r in t.all("SELECT id, body FROM client_presets WHERE client_id = ? "
                                                         "ORDER BY id", (client_id,))}


def save_own_preset(t, client_id, preset_id, body):
    """A client's own preset (same id as a built-in one = replaces it for this client)."""
    from autoedit import presets
    if not isinstance(body, dict) or body.get("id") != preset_id:
        raise JobError("The preset must be a JSON object whose id is the same as in the address.")
    if len(dumps(body)) > MAX_PRESET_BYTES:
        raise JobError("The preset is too large.")
    problems = presets.preset_problems(body, None)
    if problems:
        raise JobError("The preset has problems: " + "; ".join(problems[:3]))
    exists = t.one("SELECT id FROM client_presets WHERE client_id = ? AND id = ?", (client_id, preset_id))
    if not exists and int(t.value("SELECT COUNT(*) FROM client_presets WHERE client_id = ?", (client_id,), 0)) >= MAX_OWN_PRESETS:
        raise JobError(f"At most {MAX_OWN_PRESETS} presets of your own.")
    if exists:
        t.run("UPDATE client_presets SET body = ?, updated_at = ? WHERE client_id = ? AND id = ?",
              (dumps(body), now(), client_id, preset_id))
    else:
        t.insert("client_presets", {"client_id": client_id, "id": preset_id, "body": dumps(body),
                                    "created_at": now(), "updated_at": now()})
    return body


def catalog(client=None, t=None):
    """The presets (built-in and the client's own) and formats this client can use."""
    from autoedit import formats, presets
    allowed = loads(client.get("presets")) if client else None
    items = [p for p in presets.summary({"presets_folder": ""}) if allowed is None or p["id"] in allowed]
    if client and t is not None:
        mine = own_presets(t, client["id"])
        items = [p for p in items if p["id"] not in mine]
        for pid, body in mine.items():
            items.append({k: body.get(k) for k in ("id", "name", "tl", "about", "about_tl", "format", "graphics")}
                         | {"builtin": False, "own": True})
    return {"presets": items, "formats": formats.summary()}


def _feature_check(t, client, requested):
    """A feature with a flag must be switched on for the client's channel."""
    defined = {r["name"] for r in t.all("SELECT name FROM flags")}
    enabled = set(jobqueue.flags_for(t, client["channel"]))
    blocked = [f for f in requested if f in defined and f not in enabled]
    if blocked:
        raise JobError(f"Not available yet on the {client['channel']} channel: {', '.join(blocked)}.", 403)


def _uploads(t, client, ids, want_kinds=None):
    out = []
    for uid in ids:
        u = t.one("SELECT * FROM uploads WHERE id = ? AND client_id = ?", (str(uid), client["id"]))
        if not u or u["status"] != "ready":
            raise JobError(f"Upload {uid} is not a finished upload of yours.", 404 if not u else 409)
        if want_kinds and u["kind"] not in want_kinds:
            raise JobError(f"Upload {uid} is a {u['kind']}; expected {' or '.join(want_kinds)}.")
        out.append(u)
    return out


def validate_polish(t, client, body):
    from autoedit import formats, presets
    preset = body.get("preset") or client.get("default_preset")
    allowed = loads(client.get("presets"))
    known = {p["id"] for p in presets.summary({"presets_folder": ""})}
    mine = own_presets(t, client["id"])
    preset_body = None
    if preset is not None:
        if preset in mine:
            preset_body = mine[preset]                    # the client's own preset
        elif preset not in known:
            raise JobError(f"Unknown preset '{preset}'. Presets: {', '.join(sorted(known | set(mine)))}")
        elif allowed is not None and preset not in allowed:
            raise JobError(f"The preset '{preset}' is not enabled for you.", 403)
    fmt = body.get("format")
    specs = {f["id"]: f for f in formats.summary()}
    if fmt is not None and fmt != "auto" and fmt not in specs:
        raise JobError(f"Unknown format '{fmt}'. Formats: auto, {', '.join(sorted(specs))}")
    inputs = body.get("inputs") or {}
    if not isinstance(inputs, dict) or not isinstance(inputs.get("main"), list) or len(inputs["main"]) != 1:
        raise JobError("inputs.main must be a list with exactly one upload id (the video, or the voice-over).")
    roles = {"main", "photos"}
    for spec in specs.values():
        roles |= {i["role"] for i in spec["inputs"] if "text" not in i["kinds"]}
    roles.discard("voiceover")
    bad = [r for r in inputs if r not in roles]
    if bad:
        raise JobError(f"Unknown input role(s): {', '.join(bad)}. Roles: {', '.join(sorted(roles))}")
    total = sum(len(v) for v in inputs.values() if isinstance(v, list))
    if total > MAX_INPUT_FILES or any(not isinstance(v, list) for v in inputs.values()):
        raise JobError(f"inputs must be lists of upload ids, at most {MAX_INPUT_FILES} files in all.")
    effective_format = fmt if fmt is not None else (
        (preset_body or presets.get(preset, {"presets_folder": ""}))["format"] if preset else None)
    main_kinds = ("audio", "video") if effective_format == "voiceover_broll" else ("video",)
    main = _uploads(t, client, inputs["main"], main_kinds)
    resolved = {"main": [main[0]["id"]]}
    for role, ids in inputs.items():
        if role == "main":
            continue
        kinds = ("image",) if role == "photos" else ("video", "image", "audio")
        resolved[role] = [u["id"] for u in _uploads(t, client, ids, kinds)]
    instruction = str(body.get("instruction") or "")
    if len(instruction) > MAX_INSTRUCTION:
        raise JobError(f"The instruction is too long (at most {MAX_INSTRUCTION} characters).")
    items = body.get("items") or []
    if not isinstance(items, list) or len(items) > MAX_ITEMS or any(not isinstance(i, str) or len(i) > 200 for i in items):
        raise JobError(f"items must be up to {MAX_ITEMS} texts of up to 200 characters.")
    offsets = body.get("offsets") or {}
    if not isinstance(offsets, dict) or any(r not in roles or not isinstance(v, (int, float)) or abs(v) > 3600
                                            for r, v in offsets.items()):
        raise JobError("offsets must map input roles to seconds (-3600 to 3600).")
    provider = body.get("provider")
    if provider is not None and provider not in PROVIDERS:
        raise JobError(f"provider must be one of {', '.join(PROVIDERS)} (the keys live on the workers).")
    gpu = bool(body.get("gpu"))
    _feature_check(t, client, [f for k, f in FEATURE_OF.items() if body.get(k) not in (None, False)])
    minutes = sum((u["duration"] or 0) for role in resolved for u in
                  [t.one("SELECT duration, kind FROM uploads WHERE id = ?", (i,)) for i in resolved[role]]
                  if u["kind"] in ("video", "audio")) / 60.0
    clients.check_job_quota(t, client, minutes, gpu)
    params = {"preset": preset, "format": fmt, "instruction": instruction, "items": [str(i) for i in items],
              "offsets": {k: float(v) for k, v in offsets.items()}, "provider": provider,
              "qc": body.get("qc", True) is not False, "retry": body.get("retry", True) is not False}
    if preset_body is not None:
        params["preset_body"] = preset_body
    return params, resolved, minutes, "gpu" if gpu else "cpu"


def media_refs(project):
    return [m.get("path", "") for m in project.get("media", [])]


# Export choices for a render (the same as the desktop app's export dialog)
EXPORT_HEIGHTS = (1920, 1280, 960)            # 1080x1920, 720x1280, 540x960
EXPORT_FPS = (24, 25, 30, 50, 60)
EXPORT_QUALITY = {"high": (18, "medium"), "standard": (21, "medium"), "small": (26, "fast"), "draft": (28, "veryfast")}


def validate_export(value):
    """{height, fps, quality} for a render job, each optional."""
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"height", "fps", "quality"}:
        raise JobError("export may have height, fps and quality.")
    out = {}
    if value.get("height") is not None:
        if value["height"] not in EXPORT_HEIGHTS:
            raise JobError(f"export.height must be one of {', '.join(map(str, EXPORT_HEIGHTS))}.")
        out["height"] = int(value["height"])
    if value.get("fps") is not None:
        if value["fps"] not in EXPORT_FPS:
            raise JobError(f"export.fps must be one of {', '.join(map(str, EXPORT_FPS))}.")
        out["fps"] = int(value["fps"])
    if value.get("quality") is not None:
        if value["quality"] not in EXPORT_QUALITY:
            raise JobError(f"export.quality must be one of {', '.join(EXPORT_QUALITY)}.")
        out["quality"] = value["quality"]
    return out


def validate_render(t, client, body):
    from autoedit.project import validate_project
    project = body.get("project")
    if not isinstance(project, dict):
        raise JobError("project must be a project object (see docs/project-format.md).")
    if len(dumps(project)) > 2 * 1024 * 1024:
        raise JobError("The project is too large.")
    problems = validate_project(project)
    if problems:
        raise JobError("The project has problems: " + "; ".join(problems[:3]))
    uploads, outputs = [], []
    for ref in media_refs(project):
        kind, _, rid = ref.partition(":")
        if kind == "upload":
            uploads.append(rid)
        elif kind == "output":
            row = t.one("SELECT * FROM outputs WHERE id = ? AND client_id = ? AND deleted_at IS NULL", (rid, client["id"]))
            if not row:
                raise JobError(f"Media {ref} is not a file of yours (or it expired).", 404)
            outputs.append(rid)
        else:
            raise JobError("In a render job every media path must be 'upload:<id>' or 'output:<id>'.")
    ups = _uploads(t, client, uploads)
    minutes = sum((u["duration"] or 0) for u in ups if u["kind"] in ("video", "audio")) / 60.0
    from autoedit.project import timeline_duration
    minutes = max(minutes, timeline_duration(project) / 60.0)
    clients.check_job_quota(t, client, minutes, False)
    params = {"project": project}
    export = validate_export(body.get("export"))
    if export:
        params["export"] = export
    return params, {"uploads": [u["id"] for u in ups], "outputs": outputs}, minutes, "cpu"


def create(t, settings, client, body, idempotency_key=None):
    kind = body.get("kind", "polish")
    if kind not in KINDS:
        raise JobError(f"kind must be one of {', '.join(KINDS)}")
    project_id = body.get("project_id")
    if project_id is not None and (not isinstance(project_id, str) or not t.one(
            "SELECT id FROM projects WHERE id = ? AND client_id = ?", (project_id, client["id"]))):
        raise JobError("No such project.")
    params, inputs, minutes, queue = (validate_polish if kind == "polish" else validate_render)(t, client, body)
    job, created = jobqueue.enqueue(t, settings, client, kind, params, inputs, queue=queue, input_minutes=minutes,
                                    idempotency_key=(idempotency_key or None) and str(idempotency_key)[:100])
    if created and (project_id or client.get("user_id")):
        t.run("UPDATE jobs SET project_id = ?, user_id = ? WHERE id = ?", (project_id, client.get("user_id"), job["id"]))
        job = t.one("SELECT * FROM jobs WHERE id = ?", (job["id"],))
    return job, created


# ---------------------------------------------------------------- what the worker receives

def worker_payload(t, job, private_key, lease_seconds):
    inputs = loads(job["inputs"], {})
    files = {}
    ids = [i for ids in inputs.values() for i in ids] if job["kind"] == "polish" else inputs.get("uploads", [])
    for uid in ids:
        u = t.one("SELECT id, filename, kind, size_received, sha256 FROM uploads WHERE id = ?", (uid,))
        if u:
            files[uid] = {"filename": u["filename"], "kind": u["kind"], "size": u["size_received"], "sha256": u["sha256"]}
    outputs = {}
    for oid in (inputs.get("outputs", []) if job["kind"] == "render" else []):
        o = t.one("SELECT id, name, size, sha256 FROM outputs WHERE id = ?", (oid,))
        if o:
            outputs[oid] = {"name": o["name"], "size": o["size"], "sha256": o["sha256"]}
    payload = {"job_id": job["id"], "kind": job["kind"], "queue": job["queue"], "attempt": job["attempts"],
               "params": loads(job["params"], {}),
               "inputs": inputs, "files": files, "outputs": outputs,
               "flags": jobqueue.flags_for(t, job["channel"]), "timeout_seconds": job["timeout_seconds"],
               "issued_at": int(time.time()), "lease_seconds": lease_seconds}
    return {"payload": payload, "signature": security.sign_payload(private_key, payload)}


# ---------------------------------------------------------------- the job as the client sees it

def view(t, settings, job, base_url):
    result = loads(job["result"], None)
    outs = t.all("SELECT * FROM outputs WHERE job_id = ? AND deleted_at IS NULL ORDER BY name", (job["id"],))
    links = []
    exp = now() + settings.file_link_minutes * 60
    for o in outs:
        token = security.sign_link(settings.secret_key, "out", o["id"], exp)
        links.append({"id": o["id"], "name": o["name"], "size": o["size"], "sha256": o["sha256"],
                      "content_type": o["content_type"], "held": bool(o.get("held_at")),
                      "url": f"{base_url}/files/out/{o['id']}?t={token}&download=1",       # save (starts the clock)
                      "preview_url": f"{base_url}/files/out/{o['id']}?t={token}",          # play in the page
                      "url_expires_at": int(exp), "expires_at": o["expires_at"],
                      "expires_in_seconds": max(0, int(o["expires_at"] - now()))})
    public_result = None
    if result:
        public_result = {k: result.get(k) for k in ("status", "qc", "retries", "opinions", "format", "preset", "error",
                                                    "cost", "seconds")}
    return {"id": job["id"], "kind": job["kind"], "status": job["status"], "queue": job["queue"],
            "channel": job["channel"], "progress": job["progress"], "stage": job["stage"], "error": job["error"],
            "attempts": job["attempts"], "created_at": job["created_at"], "started_at": job["started_at"],
            "finished_at": job["finished_at"], "input_minutes": job["input_minutes"],
            "project_id": job.get("project_id"),
            "params": loads(job["params"], {}), "inputs": loads(job["inputs"], {}),
            "result": public_result, "outputs": links,
            "ai_label": AI_LABEL if job["status"] == "succeeded" else None}
