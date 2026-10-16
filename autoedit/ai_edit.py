"""The AI edit: instruction + transcript + photo names -> plan -> Project -> finished video.

    transcript  (Groq Whisper or local; saved in the cache, so re-runs are free)
    plan        (Groq or Anthropic; checked against ai_plan.schema.json and by building the
                 Project; one retry with the problems listed; then the preset edit, said so)
    project     (built by the normal editing steps, reported stage by stage:
                 cuts, zooms, captions, photos)
    summary     (plain-language list of what was actually done)
    render      (optional: auto mode renders straight away)
"""

import copy
import json
import shutil
import time
from pathlib import Path

from .ai_plan import apply_plan, load_plan_schema, preset_plan, validate_plan
from .cache import Cache, key_for
from .config import project_path
from .costs import estimate_tokens, format_usd, plan_cost, total, transcription_cost
from .errors import Cancelled, EditorError
from .ffmpeg_tools import check_ffmpeg, probe_video_with_audio
from .llm import PROVIDERS, LLMError, ask_json
from .pipeline import build_edit_project, unique_output_path
from .project import save_project, timeline_duration
from .project_render import render_project
from .transcribe import transcribe
from .words import save_transcript, words_from_data

PROMPT_VERSION = 1
MAX_ATTEMPTS = 2

SYSTEM_PROMPT = """You plan edits for short vertical videos (TikTok / Facebook Reels) of a \
creator talking to the camera, usually in Filipino, English or Taglish. A program does the \
actual editing; you only fill in the plan.

What the program always does by itself: it cuts pauses longer than \
pacing.silence_threshold seconds and (if remove_fillers) the filler words ah/uh/um/uhm/eh; \
it adds punch-in zooms on jump cuts when zoom.enabled; it makes word-by-word captions in the \
chosen style; it evens out loudness and makes the video 1080x1920.

How to fill in the plan:
- Start from the DEFAULT EDIT and change only what the instruction asks for, or what \
clearly serves it (for example "mas mabilis" / "faster" means a lower silence_threshold).
- All times are seconds in the RAW video. Take them from the transcript; never guess times \
for words you cannot find.
- cuts: only content the creator wants removed (a retake, a mistake, a topic). A retake \
usually looks like the same sentence said twice: cut the earlier attempt, from its first \
word to just before the repeat starts.
- photos: only file names listed under PHOTOS. Show a photo when the speaker first mentions \
what it shows (match words in the file name, e.g. "gcash_receipt.png" when they say \
"GCash" or "resibo"); "at" is that word's start time; 2 to 4 seconds is usual.
- captions.highlight_words: words from the transcript worth emphasizing (prices, product \
names, key terms), only if asked or clearly useful.
- zooms: extra emphasis zoom-ins on key moments, only if asked (amount 1.2 to 1.4).
- If the instruction asks for something the program cannot do (music, transitions, face \
filters, changing what someone said), do not fake it: add a short note to notes.
- Never plan face swaps, deepfakes, voice cloning or lip-sync.
- summary: one to three short sentences to the creator, in the language of the \
instruction, describing the edit.

Output the JSON object only."""


def mmss(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def transcript_lines(words, per_line=12):
    lines = []
    for i in range(0, len(words), per_line):
        lines.append("  ".join(f"{w.start:.2f} {w.text}" for w in words[i:i + per_line]))
    return "\n".join(lines)


def build_prompt(instruction, words, duration, photo_names, baseline, previous_plan=None):
    parts = [f"VIDEO LENGTH: {duration:.2f} seconds",
             "PHOTOS (file names you may use): " + (", ".join(photo_names) or "none"),
             "DEFAULT EDIT (keep these values unless the instruction asks otherwise):\n"
             + json.dumps(baseline, ensure_ascii=False)]
    if previous_plan:
        parts += ["CURRENT PLAN (the creator wants changes to it; return the whole updated "
                  "plan):\n" + json.dumps(previous_plan, ensure_ascii=False),
                  "CHANGE REQUEST FROM THE CREATOR:\n" + instruction.strip()]
    else:
        parts.append("INSTRUCTION FROM THE CREATOR:\n"
                     + (instruction.strip() or "(none: make a clean, punchy edit)"))
    parts.append("TRANSCRIPT (start time in seconds, then the word):\n"
                 + transcript_lines(words))
    return "\n\n".join(parts)


def provider_settings(cfg, provider=None, model=None):
    ai = cfg["ai"]
    provider = (provider or ai["provider"]).lower()
    if provider not in PROVIDERS:
        raise EditorError(f"Unknown AI provider '{provider}'. Choose: {', '.join(PROVIDERS)}")
    model = model or ai[f"{provider}_model"]
    return provider, model


class PlanResult:
    def __init__(self, plan, fallback=False, reason="", attempts=(), usage=None, model=None,
                 cached=False, cost=None, given=False):
        self.plan, self.fallback, self.reason = plan, fallback, reason
        self.attempts = list(attempts)
        self.usage = usage or {"input_tokens": 0, "output_tokens": 0}
        self.model, self.cached, self.cost, self.given = model, cached, cost, given

    def as_event(self):
        return {"plan": self.plan, "fallback": self.fallback, "reason": self.reason,
                "attempts": self.attempts, "cached": self.cached, "given": self.given,
                "model": self.model, "usage": self.usage, "cost": self.cost}


def request_plan(cfg, provider, model, instruction, words, duration, photo_names, cache,
                 previous_plan=None, check=None, cancel=None):
    """Ask the model for a plan; check it; retry once; else return the preset plan.

    `check(plan)` returns extra problems (e.g. from building the project with it).
    """
    ai = cfg["ai"]
    baseline = preset_plan(cfg)
    effort = ai.get("anthropic_effort", "medium")
    key = key_for({"v": PROMPT_VERSION, "provider": provider, "model": model,
                   "effort": effort if provider == "anthropic" else None,
                   "instruction": instruction.strip(), "duration": round(duration, 3),
                   "words": [(w.text, w.start, w.end) for w in words],
                   "photos": sorted(photo_names), "previous": previous_plan,
                   "baseline": baseline})
    cached = cache.get("plans", key) if cache else None
    if cached and not validate_plan(cached["plan"], duration, photo_names):
        extra = check(cached["plan"]) if check else []
        if not extra:
            return PlanResult(cached["plan"], cached=True, model=cached.get("model"), cost=0.0)

    schema = copy.deepcopy(load_plan_schema())
    if photo_names:
        schema["properties"]["photos"]["items"]["properties"]["file"]["enum"] = \
            sorted(photo_names)
    prompt = build_prompt(instruction, words, duration, sorted(photo_names), baseline,
                          previous_plan)
    attempts, usage, used_model = [], {"input_tokens": 0, "output_tokens": 0}, model
    request = prompt
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled while planning.")
        try:
            text, used, used_model = ask_json(provider, model, SYSTEM_PROMPT, request, schema,
                                              max_tokens=int(ai.get("max_tokens", 8000)),
                                              effort=effort)
        except LLMError as exc:
            reason = f"The AI could not be asked ({exc}) - this is the preset edit instead."
            return PlanResult(baseline, fallback=True, reason=reason, attempts=attempts,
                              usage=usage, model=used_model,
                              cost=_plan_cost(cfg, used_model, usage))
        usage = {k: usage[k] + used[k] for k in usage}
        try:
            plan = json.loads(text) if text.strip() else None
            problems = ["the answer was empty or cut off"] if plan is None else []
        except ValueError as exc:
            plan, problems = None, [f"the answer is not valid JSON ({exc})"]
        if not problems:
            problems = validate_plan(plan, duration, photo_names)
        if not problems and check:
            problems = check(plan)
        if not problems:
            if cache:
                cache.put("plans", key, {"plan": plan, "model": used_model})
            return PlanResult(plan, attempts=attempts, usage=usage, model=used_model,
                              cost=_plan_cost(cfg, used_model, usage))
        attempts.append({"attempt": attempt, "problems": problems[:20]})
        request = (prompt + "\n\nYOUR PREVIOUS ANSWER HAD THESE PROBLEMS:\n"
                   + "\n".join(f"- {p}" for p in problems[:20])
                   + "\n\nPREVIOUS ANSWER:\n" + text[:6000]
                   + "\n\nReturn a corrected, complete JSON plan.")
    first = attempts[0]["problems"][0] if attempts else "unknown problem"
    reason = (f"The AI plan failed the checks twice (first problem: {first}), so this is the "
              f"preset edit instead.")
    return PlanResult(baseline, fallback=True, reason=reason, attempts=attempts, usage=usage,
                      model=used_model, cost=_plan_cost(cfg, used_model, usage))


def _plan_cost(cfg, model, usage):
    return plan_cost(cfg["ai"].get("prices") or {}, model, usage["input_tokens"],
                     usage["output_tokens"])


def staged_projects(project):
    """Views of the project as each editing stage completes (for the live preview)."""
    stages = [("cuts", {"video"}), ("zooms", {"video", "effect"}),
              ("captions", {"video", "effect", "caption"}),
              ("photos", {"video", "effect", "caption", "overlay", "audio"})]
    for name, kinds in stages:
        view = copy.deepcopy(project)
        for track in view["tracks"]:
            if track["kind"] not in kinds:
                track["clips"] = []
        yield name, view


def describe(project, plan, result, raw_duration, photo_names):
    """Plain-language summary of what was actually done (from the finished project)."""
    tracks = project["tracks"]
    main = next(t for t in tracks if t["kind"] == "video")["clips"]
    final = timeline_duration(project)
    pacing = plan["pacing"]
    what = "pauses and filler words" if pacing["remove_fillers"] else "pauses"
    details = [f"Cut the {what} (longer than {pacing['silence_threshold']:g}s): "
               f"{mmss(raw_duration)} -> {mmss(final)}, {max(0, len(main) - 1)} jump "
               f"cut{'s' if len(main) != 2 else ''}."]
    for cut in plan["cuts"]:
        details.append(f"Removed {mmss(cut['start'])}-{mmss(cut['end'])} of the original"
                       + (f": {cut['reason']}" if cut.get("reason") else "."))
    zooms = [c for t in tracks if t["kind"] == "effect" for c in t["clips"] if c["type"] == "zoom"]
    if zooms:
        details.append(f"Added {len(zooms)} zoom-in{'s' if len(zooms) != 1 else ''}.")
    elif not plan["zoom"]["enabled"]:
        details.append("No automatic zooms.")
    captions = [c for t in tracks if t["kind"] == "caption" for c in t["clips"]]
    if captions:
        extra = []
        scale = plan["captions"]["size_scale"]
        if abs(scale - 1) > 1e-6:
            extra.append(f"{abs(scale - 1) * 100:.0f}% {'bigger' if scale > 1 else 'smaller'}")
        if plan["captions"]["position"]:
            extra.append(f"at the {plan['captions']['position']}")
        if plan["captions"]["highlight_words"]:
            extra.append("highlighting " + ", ".join(plan["captions"]["highlight_words"][:8]))
        details.append(f"Captions in the {plan['style']} style"
                       + (f" ({'; '.join(extra)})" if extra else "") + f": {len(captions)} lines.")
    else:
        details.append("No captions.")
    grade_line = f"Colour: {plan['grade'].replace('_', ' ')}."
    for g in plan["grades"]:
        grade_line += (f" {g['grade'].replace('_', ' ')} from {mmss(g['start'])} to "
                       f"{mmss(g['end'])}.")
    details.append(grade_line)
    shown = [c for t in tracks if t["kind"] == "overlay" and t["id"] != "logo"
             for c in t["clips"]]
    by_media = {m["id"]: m.get("name") or Path(m["path"]).name for m in project["media"]}
    shown_names = [by_media[c["media"]] for c in shown]
    for photo in plan["photos"]:
        if photo["file"] in shown_names:
            shown_names.remove(photo["file"])
            details.append(f"Photo {photo['file']} at {mmss(photo['at'])}"
                           + (f": {photo['reason']}" if photo.get("reason") else "."))
        else:
            details.append(f"Skipped photo {photo['file']}: that part was cut, or another "
                           f"photo was already on screen.")
    unused = sorted(set(photo_names) - {p["file"] for p in plan["photos"]})
    if unused:
        details.append("Photos not used: " + ", ".join(unused) + ".")
    for note in plan.get("notes") or []:
        details.append(f"Not done: {note}")
    if result.fallback:
        headline = "Heads up: " + result.reason
    else:
        headline = plan.get("summary") or "Done."
    return {"headline": headline, "details": details, "fallback": result.fallback,
            "duration_before": raw_duration, "duration_after": final}


def load_words(video, cfg, cache, job_dir, duration):
    """The transcript, from the cache when this exact video was transcribed before."""
    t = cfg["transcription"]
    provider = str(t["provider"]).lower()
    model = t["groq_model"] if provider == "groq" else t["local_model"]
    key = f"{cache.fingerprint(video)}-{provider}-{model}-{cfg['language']}" if cache else None
    data = cache.get("transcripts", key) if cache else None
    if data:
        return words_from_data(data), True, 0.0
    words = transcribe(video, cfg, job_dir)
    if cache:
        path = cache.folder / "transcripts" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        save_transcript(words, path, cfg["language"])
    cost = transcription_cost(cfg["ai"].get("prices") or {}, model, duration) \
        if provider == "groq" else 0.0
    return words, False, cost


def ai_edit_video(video, cfg, instruction="", photos=(), provider=None, model=None,
                  render=True, output=None, previous_plan=None, plan=None, reporter=None,
                  cancel=None):
    """Make an AI edit of one video. Returns a dict describing the result.

    `plan`: use this plan as is (e.g. the creator accepted only some AI changes); no AI call.
    `previous_plan`: change this plan according to `instruction` (a follow-up).
    `render`: False = stop after the project (auto mode off: review first).
    """
    from .progress import TextReporter

    reporter = reporter or TextReporter()
    started = time.time()
    video = Path(video).resolve()
    check_ffmpeg()
    info = probe_video_with_audio(video)
    duration = info["duration"]
    paths = [Path(p).resolve() for p in photos]
    photos = {p.name: p for p in paths}
    if len(photos) != len(paths):
        raise EditorError("Two photos have the same file name. Rename one so the AI can tell "
                          "them apart.")
    for path in paths:
        if not path.exists():
            raise EditorError(f"Photo not found: {path}")
    provider, model = provider_settings(cfg, provider, model)
    cache = Cache(project_path(cfg["ai"]["cache_folder"]))
    job_dir = project_path(cfg["work_folder"]) / f"{video.stem}-ai-{time.strftime('%Y%m%d-%H%M%S')}"
    job_dir.mkdir(parents=True, exist_ok=True)
    out_folder = project_path(cfg["output"]["folder"])
    output = Path(output).resolve() if output else unique_output_path(out_folder, video.stem)

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled.")

    try:
        reporter.stage("transcript", "Listening to your video")
        words, cached, transcript_cost = load_words(video, cfg, cache, job_dir, duration)
        reporter.event("transcript", words=len(words), cached=cached,
                       text=" ".join(w.text for w in words)[:4000])
        check_cancel()

        reporter.stage("plan", "Planning the edit")
        built = {}

        def build(candidate):
            new_cfg, pipeline_plan = apply_plan(cfg, candidate, photos)
            return build_edit_project(video, new_cfg, plan=pipeline_plan, job_dir=job_dir,
                                      words=words)

        def check(candidate):
            try:
                built["project"] = build(candidate)
                built["plan"] = candidate
                return []
            except EditorError as exc:      # includes ProjectError (schema check)
                return [f"the edit could not be built from this plan: {exc}"]

        if plan is not None:
            problems = validate_plan(plan, duration, photos)
            if problems:
                raise EditorError("The plan has problems:\n  - " + "\n  - ".join(problems))
            result = PlanResult(plan, given=True, model=None, cost=0.0)
        else:
            result = request_plan(cfg, provider, model, instruction, words, duration,
                                  list(photos), cache, previous_plan, check, cancel)
        reporter.event("plan", **result.as_event(), baseline=preset_plan(cfg))
        check_cancel()

        if built.get("plan") is not result.plan:
            built["project"] = build(result.plan)
        project = built["project"]
        project["meta"].update({"made_by": "AI edit", "instruction": instruction,
                                "provider": provider if not result.given else None,
                                "model": result.model, "fallback": result.fallback})
        for stage, view in staged_projects(project):
            reporter.stage(stage, {"cuts": "Cutting pauses", "zooms": "Adding zooms",
                                   "captions": "Making captions",
                                   "photos": "Placing photos"}[stage])
            reporter.event("project", stage=stage, project=view)

        summary = describe(project, result.plan, result, duration, list(photos))
        # Token counts are the provider's own; the prices are from config.yaml (ai.prices).
        cost = {"transcription": transcript_cost, "plan": result.cost,
                "total": total(transcript_cost, result.cost), "currency": "USD",
                "provider": provider, "model": result.model or model,
                "paid_provider": provider == "anthropic", "usage": result.usage,
                "transcript_cached": cached, "plan_cached": result.cached}
        summary["cost"] = cost
        summary["cost_text"] = format_usd(cost["total"])
        reporter.event("summary", **summary)

        project_file = save_project(project, output.with_suffix(".project.json"))
        plan_file = output.with_suffix(".plan.json")
        plan_file.write_text(json.dumps({
            "plan": result.plan, "instruction": instruction, "provider": provider,
            "model": result.model, "fallback": result.fallback, "reason": result.reason,
            "photos": {k: str(v) for k, v in photos.items()}, "summary": summary,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        check_cancel()

        rendered = None
        if render:
            o = cfg["output"]
            rendered = render_project(
                project, output, work_dir=job_dir,
                fonts_folder=project_path(cfg["captions"]["fonts_folder"]),
                export={"crf": o["crf"], "encoder_speed": o["encoder_speed"],
                        "audio_bitrate": o["audio_bitrate"]},
                reporter=reporter, cancel=cancel)
    except BaseException:
        if not cfg.get("keep_work_files"):
            shutil.rmtree(job_dir, ignore_errors=True)
        raise
    if not cfg.get("keep_work_files"):
        shutil.rmtree(job_dir, ignore_errors=True)
    print(f"Done in {(time.time() - started) / 60:.1f} min")
    return {"output": str(rendered) if rendered else None, "project": str(project_file),
            "plan": str(plan_file), "summary": summary, "fallback": result.fallback,
            "reason": result.reason, "cost": cost}


def estimate_cost(video, cfg, instruction="", photo_names=(), provider=None, model=None):
    """Cost estimate before running (no API call; the transcript cache is honoured)."""
    provider, model = provider_settings(cfg, provider, model)
    prices = cfg["ai"].get("prices") or {}
    info = probe_video_with_audio(video)
    t = cfg["transcription"]
    cache = Cache(project_path(cfg["ai"]["cache_folder"]))
    tmodel = t["groq_model"] if t["provider"] == "groq" else t["local_model"]
    key = f"{cache.fingerprint(video)}-{t['provider']}-{tmodel}-{cfg['language']}"
    cached = cache.get("transcripts", key) is not None
    transcript = 0.0 if cached or t["provider"] != "groq" else \
        transcription_cost(prices, tmodel, info["duration"])
    words_guess = info["duration"] * 2.6          # about 2.6 words per second of talking
    prompt_tokens = estimate_tokens(SYSTEM_PROMPT) + 800 + estimate_tokens(instruction) \
        + int(words_guess * 4)
    plan = plan_cost(prices, model, prompt_tokens, 1500)
    return {"transcription": transcript, "plan": plan, "total": total(transcript, plan),
            "currency": "USD", "provider": provider, "model": model,
            "paid_provider": provider == "anthropic", "estimated": True,
            "transcript_cached": cached, "text": format_usd(total(transcript, plan))}
