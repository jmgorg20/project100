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

from .ai_gen import availability
from .ai_plan import apply_plan, load_plan_schema, preset_plan, upgrade_plan, validate_plan
from .broll import resolve_plan, sources_text
from .tracking import track_for_plan, tracking_text
from .cache import Cache, key_for
from .config import project_path
from .costs import estimate_tokens, format_usd, plan_cost, total, transcription_cost
from .errors import Cancelled, EditorError
from .ffmpeg_tools import check_ffmpeg, probe_video_with_audio
from .generation import Paths as GenPaths
from .llm import PROVIDERS, LLMError, ask_json
from .pipeline import build_edit_project, unique_output_path
from .project import save_project, timeline_duration
from .project_render import render_project
from .transcribe import transcribe
from .words import save_transcript, words_from_data

PROMPT_VERSION = 4
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
- effects: short accents (flash, whip, shake, glitch, dip) only if the creator asks for \
effects or transitions ("lagyan ng transitions", "may effects"), or for a clear punchline. \
Transitions (flash, whip, dip) go between topics with on_cut true; shake or glitch on a \
punchline word. At most one every 3 seconds; 0.2 to 0.5 seconds each.
- If the instruction asks for something the program cannot do (music, face filters, \
changing what someone said), do not fake it: add a short note to notes.
- tracked_effects: an effect that follows the speaker's hand, face or body, only if TRACKED \
EFFECTS says tracking is available AND the creator asks for it ("glow sa kamay pag sinabi \
kong ...", "aura around me", "sparks on my palm"). `at` is when the matching word starts; \
1.5 to 4 seconds. glow / spark / energy follow a hand (palm, index_tip, fingertips...), aura \
follows face or body. The effect fades out by itself when the point is not visible, so it \
may be a little longer than the moment. If tracking is not available, leave it empty and say \
so in notes.
- ai_clips are B-roll (pictures or short clips over the speaker), when the creator asks \
for B-roll / visuals, or it clearly helps. Follow B-ROLL SOURCES below: plan none if no \
source is available. Put each one where the speaker mentions what it shows. prompt: \
concrete and visual, in English, never real, identifiable people or brands. search: 2 to 4 \
English keywords. style: realistic unless the creator asks for a look (cartoon, drawing, \
low-poly / boxy, robot / 3D, anime). source: auto unless the creator names one. A \
full-screen clip covers the speaker, so keep it short (1.5 to 3 seconds).
- voiceovers: follow AI GENERATION below, only if voice-over is available and asked for.
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


def build_prompt(instruction, words, duration, photo_names, baseline, previous_plan=None,
                 generation_text=None):
    parts = [f"VIDEO LENGTH: {duration:.2f} seconds",
             "PHOTOS (file names you may use): " + (", ".join(photo_names) or "none"),
             generation_text or "AI GENERATION: NOT available. Leave ai_clips and voiceovers "
                                "empty.",
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
                 previous_plan=None, check=None, cancel=None, generation_text=None):
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
                   "baseline": baseline, "generation": generation_text})
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
                          previous_plan, generation_text)
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
            plan = upgrade_plan(json.loads(text)) if text.strip() else None
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


def describe(project, plan, result, raw_duration, photo_names, generation=None, tracking=None):
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
    fx = [c for t in tracks if t["kind"] == "effect" for c in t["clips"] if c["type"] == "fx"]
    if fx:
        names = ", ".join(f"{c['effect']} at {mmss(c['start'])}" for c in fx[:8])
        details.append(f"Added {len(fx)} effect{'s' if len(fx) != 1 else ''}: {names}"
                       + ("..." if len(fx) > 8 else "."))
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
    for t in tracks:
        for c in t["clips"]:
            if c["type"] == "trackfx":
                follows = {"fingertips": "the fingertips", "face": "the face", "body": "the body"}.get(
                    c["point"], f"the {c['point'].replace('_', ' ')}")
                hand = "" if c["point"] in ("face", "body") or c.get("hand", "any") == "any" \
                    else f" ({c['hand']} hand)"
                details.append(f"Tracked {c['effect']} on {follows}{hand} at {mmss(c['start'])}.")
    if tracking:
        details += tracking["notes"]
    if generation:
        details += generation.get("sourced", [])
        for item in generation["done"]:
            details.append(f"{item['item']}: {item['tier']} tier, {item['seconds']:.0f}s"
                           + (f" ({item['reason_text']})" if item.get("reason_text") else "."))
        if generation["passes"] == ["draft"]:
            made = sum(1 for files in generation["draft"].values() for f in files if f)
            if made:
                details.append(f"{made} AI item(s) made with the quick preview tier; the final "
                               f"tier is used when you apply the edit.")
        details += generation["notes"]
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
    from .vocabulary import fix_words
    data = cache.get("transcripts", key) if cache else None
    if data:
        return fix_words(words_from_data(data), cfg), True, 0.0
    words = transcribe(video, cfg, job_dir)
    if cache:
        path = cache.folder / "transcripts" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        save_transcript(words, path, cfg["language"])
    cost = transcription_cost(cfg["ai"].get("prices") or {}, model, duration) \
        if provider == "groq" else 0.0
    return fix_words(words, cfg), False, cost


def ai_edit_video(video, cfg, instruction="", photos=(), provider=None, model=None,
                  render=True, output=None, previous_plan=None, plan=None, reporter=None,
                  cancel=None, gen_paths=None, max_gen_minutes=None, max_ai_clips=None):
    """Make an AI edit of one video. Returns a dict describing the result.

    `plan`: use this plan as is (e.g. the creator accepted only some AI changes); no AI call.
    `previous_plan`: change this plan according to `instruction` (a follow-up).
    `render`: False = stop after the project (auto mode off: review first).
    AI pictures, clips and voice-over in the plan are made with WanGP (see ai_gen.py):
    a Draft pass for the preview, then the final tier when rendering; `max_gen_minutes`
    and `max_ai_clips` limit generation for this video.
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

        extra = {}                        # e.g. the tracked points, once found

        def build(candidate, generated=None):
            new_cfg, pipeline_plan = apply_plan(cfg, candidate, photos, {**(generated or {}), **extra})
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
            plan = upgrade_plan(plan)
            problems = validate_plan(plan, duration, photos)
            if problems:
                raise EditorError("The plan has problems:\n  - " + "\n  - ".join(problems))
            result = PlanResult(plan, given=True, model=None, cost=0.0)
        else:
            try:
                gen_ok, generation_text = availability(gen_paths or GenPaths())
            except Exception as exc:          # generation must never block the edit
                print(f"  ! could not check AI generation: {exc}")
                gen_ok, generation_text = {}, None
            generation_text = (generation_text or "AI GENERATION: NOT available. Leave "
                               "voiceovers empty.") + "\n" + sources_text(cfg, gen_ok) \
                + "\n" + tracking_text(cfg)
            result = request_plan(cfg, provider, model, instruction, words, duration,
                                  list(photos), cache, upgrade_plan(previous_plan), check,
                                  cancel, generation_text)
        reporter.event("plan", **result.as_event(), baseline=preset_plan(cfg))
        check_cancel()

        if built.get("plan") is not result.plan:
            built["project"] = build(result.plan)
        project = built["project"]
        tracking = None
        if result.plan.get("tracked_effects"):
            tracking = track_for_plan(result.plan, video, cfg, cache, reporter, cancel)
            if tracking["track"] is not None:
                extra["track"] = tracking["track"]
                project = build(result.plan)
            check_cancel()
        generation = None
        if result.plan.get("ai_clips") or result.plan.get("voiceovers"):
            if plan is not None and render:
                passes = ["final"]               # reviewed plan: its draft was already seen
            elif render:
                passes = ["draft", "final"]      # Auto mode: quick preview, then final
            else:
                passes = ["draft"]               # review first: final when applied
            generation = resolve_plan(result.plan, cfg, passes, gen_paths, max_gen_minutes,
                                      max_ai_clips, reporter, cancel,
                                      download_folder=output.parent / "broll")
            if passes == ["draft", "final"]:
                reporter.event("project", stage="ai_draft",
                               project=build(result.plan, {**generation["draft"],
                                                           "meta": generation["meta"]}))
            project = build(result.plan, {**generation["final" if "final" in passes else "draft"],
                                          "meta": generation["meta"]})
            generation["passes"] = passes
            check_cancel()
        project["meta"].update({"made_by": "AI edit", "instruction": instruction,
                                "provider": provider if not result.given else None,
                                "model": result.model, "fallback": result.fallback})
        for stage, view in staged_projects(project):
            reporter.stage(stage, {"cuts": "Cutting pauses", "zooms": "Adding zooms",
                                   "captions": "Making captions",
                                   "photos": "Placing photos"}[stage])
            reporter.event("project", stage=stage, project=view)

        summary = describe(project, result.plan, result, duration, list(photos), generation, tracking)
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
