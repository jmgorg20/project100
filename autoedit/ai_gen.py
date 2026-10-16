"""Making the AI edit's generated clips and voice-overs with WanGP, inside the limits.

    draft pass:  every item with the preview tier (Draft when installed), for a quick preview
    final pass:  every item with the final tier (pinned > your default > highest that passed
                 its benchmark > highest installed); if a job fails or runs out of time, the
                 next tier down is tried, and the summary says so

Per video: at most `max_ai_clips` pictures/clips, and all generation together stops at
`max_generation_minutes` (items not finished in time keep their draft, or are left out).
One GPU job at a time.
"""

import hashlib
import time

from .errors import Cancelled, EditorError
from .generation import (CONTENT_TYPES, Generator, Paths, cached_models, choose, load_settings,
                         read_json, tier_table, usable)
from .wangp import WanGPError, check_setup

LABEL = {"image": "AI picture", "video": "AI video clip", "voice": "AI voice-over"}


def mmss(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def hardware_key(paths):
    from .hardware import detect
    return (read_json(paths.hardware, {}) or {}).get("key") or detect()["key"]


def availability(paths):
    """{content type: usable?} from the last WanGP check, plus a line for the AI's prompt."""
    settings, _ = load_settings(paths)
    ok = {c: False for c in CONTENT_TYPES}
    if not check_setup(settings):
        table = tier_table(paths, settings, hardware_key(paths), cached_models(paths))
        ok = {c: bool(usable(table[c])) for c in CONTENT_TYPES}
    words = {True: "available", False: "NOT available"}
    limit = settings["limits"]["max_ai_clips"]
    text = (f"AI GENERATION: pictures {words[ok['image']]}; video clips {words[ok['video']]}; "
            f"voice-over {words[ok['voice']]}. At most {limit} AI pictures/clips in total. "
            f"Only plan ai_clips or voiceovers of an available kind, and only when the creator "
            f"asks for them or they clearly help; otherwise leave them empty.")
    return ok, text


def describe_item(plan, list_name, index):
    """e.g. 'AI video clip at 0:12'."""
    item = plan[list_name][index]
    kind = "voice" if list_name == "voiceovers" else item["kind"]
    return f"{LABEL[kind]} at {mmss(item['at'])}"


def seed_for(text):
    """The same item gets the same seed in the draft and the final pass."""
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16) % (2 ** 31)


def items_of(plan):
    items = []
    for i, clip in enumerate(plan.get("ai_clips", [])):
        extra = {"video_length": f"{clip['duration']:g}s"} if clip["kind"] == "video" else {}
        items.append({"list": "ai_clips", "index": i, "type": clip["kind"], "at": clip["at"],
                      "prompt": clip["prompt"], "extra": extra, "reason": clip.get("reason")})
    for i, line in enumerate(plan.get("voiceovers", [])):
        items.append({"list": "voiceovers", "index": i, "type": "voice", "at": line["at"],
                      "prompt": line["text"], "extra": {}, "reason": line.get("reason")})
    return items


def empty(plan):
    return {"ai_clips": [None] * len(plan.get("ai_clips", [])),
            "voiceovers": [None] * len(plan.get("voiceovers", []))}


def generate_for_plan(plan, passes, gen_paths=None, max_minutes=None, max_clips=None,
                      reporter=None, cancel=None, log=print):
    """Run the requested passes ("draft", "final"). Returns a dict:

    {"draft": {...}, "final": {...}, "notes": [...], "done": [...]}, where draft/final map
    "ai_clips"/"voiceovers" to lists of file paths (None = not made).
    """
    paths = gen_paths or Paths()
    items = items_of(plan)
    outcome = {"draft": empty(plan), "final": empty(plan), "notes": [], "done": []}
    if not items:
        return outcome
    settings, _ = load_settings(paths)
    limits = dict(settings["limits"])
    if max_minutes is not None:
        limits["max_generation_minutes"] = max_minutes
    if max_clips is not None:
        limits["max_ai_clips"] = max_clips
    notes = outcome["notes"]

    clips = [it for it in items if it["list"] == "ai_clips"]
    if len(clips) > limits["max_ai_clips"]:
        dropped = clips[limits["max_ai_clips"]:]
        notes.append(f"Not done: {len(dropped)} AI picture(s)/clip(s) over this video's limit "
                     f"of {limits['max_ai_clips']}.")
        items = [it for it in items if it not in dropped]

    problems = check_setup(settings)
    if problems:
        notes.append("Not done: AI pictures, clips and voice-over (WanGP is not set up: "
                     + " ".join(problems) + ")")
        return outcome

    budget_end = time.monotonic() + limits["max_generation_minutes"] * 60
    job_limit = limits["job_timeout_minutes"] * 60
    try:
        with Generator(paths, settings, hardware_key(paths), log=log, cancel=cancel) as gen:
            models = gen.bridge.models()                  # WanGP's own installed check, now
            info = {"version": gen.version, "models": models}
            table = tier_table(paths, settings, gen.hardware_key, info)
            plans = {c: choose(table[c], settings, c) for c in CONTENT_TYPES}
            for ctype in CONTENT_TYPES:
                wanted = [it for it in items if it["type"] == ctype]
                if wanted and not plans[ctype][1]:
                    notes.append(f"Not done: {len(wanted)} {LABEL[ctype].lower()}(s): no "
                                 f"{ctype} tier is installed and set up.")
            items = [it for it in items if plans[it["type"]][1]]
            out_of_time = False
            for pass_name in passes:
                if reporter:
                    reporter.stage(f"ai_{pass_name}", "Making AI clips (draft)"
                                   if pass_name == "draft" else "Making AI clips (final)")
                for n, it in enumerate(items):
                    if reporter:
                        reporter.progress(n / max(1, len(items)), stage=f"ai_{pass_name}")
                    preview, order = plans[it["type"]]
                    what = describe_item(plan, it["list"], it["index"])
                    draft_file = outcome["draft"][it["list"]][it["index"]]
                    if pass_name == "final" and draft_file and order[0] == preview:
                        outcome["final"][it["list"]][it["index"]] = draft_file  # same tier
                        continue
                    tiers = [preview] if pass_name == "draft" else order
                    for k, tier in enumerate(tiers):
                        remaining = budget_end - time.monotonic()
                        if remaining < 5:
                            out_of_time = True
                            break
                        row = next(r for r in table[it["type"]] if r["name"] == tier)
                        result, output = gen.run(it["type"], row, it["prompt"],
                                                 seed_for(it["prompt"]), f"edit-{pass_name}",
                                                 it["extra"], timeout=min(job_limit, remaining))
                        event = {"item": what, "tier": tier, "pass": pass_name,
                                 "success": result.success, "reason": result.reason,
                                 "seconds": round(result.seconds, 1), "file": output}
                        if reporter:
                            reporter.event("generation", **event)
                        if result.success:
                            outcome[pass_name][it["list"]][it["index"]] = output
                            if pass_name == "final":
                                outcome["done"].append({**event, "reason_text": it["reason"]})
                            break
                        nxt = tiers[k + 1] if k + 1 < len(tiers) else None
                        notes.append(f"{what}: the {tier} tier {result.reason}"
                                     + (f", so the {nxt} tier was used instead." if nxt
                                        else "."))
                    if out_of_time:
                        break
                if out_of_time:
                    notes.append(f"Stopped making AI clips: this video's limit of "
                                 f"{limits['max_generation_minutes']} minutes was reached.")
                    break
    except WanGPError as exc:
        notes.append(f"Not done: AI pictures, clips and voice-over (WanGP: {exc})")
    except Cancelled:
        raise
    except EditorError as exc:
        notes.append(f"Not done: AI generation stopped ({exc})")
    if "final" in passes:
        for name in ("ai_clips", "voiceovers"):
            for i, path in enumerate(outcome["final"][name]):
                draft = outcome["draft"][name][i]
                if path is None and draft:
                    outcome["final"][name][i] = draft
                    notes.append(f"{describe_item(plan, name, i)}: kept the draft version.")
    return outcome
