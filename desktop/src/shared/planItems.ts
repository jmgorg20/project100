// The AI plan as a list of changes the creator can accept or reject one by one
// (used when Auto mode is off). Pure functions.
import type { Plan, PlanAiClip } from "./types";

export interface PlanItem {
  id: string;
  group: "Look" | "Pacing" | "Cuts" | "Zooms" | "Colour" | "Photos" | "B-roll & AI clips";
  label: string;
  detail?: string;
}

export function mmss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Items that differ from the preset edit (`base`), so only real AI decisions are listed. */
export function planItems(plan: Plan, base: Plan): PlanItem[] {
  const items: PlanItem[] = [];
  if (plan.style !== base.style) items.push({ id: "style", group: "Look", label: `Caption style: ${plan.style}` });
  const c = plan.captions;
  if (c.enabled !== base.captions.enabled) items.push({ id: "captions.enabled", group: "Look", label: c.enabled ? "Captions on" : "No captions" });
  if (Math.abs(c.size_scale - base.captions.size_scale) > 1e-6) {
    const pct = Math.round(Math.abs(c.size_scale - 1) * 100);
    items.push({ id: "captions.size_scale", group: "Look", label: `Captions ${pct}% ${c.size_scale > 1 ? "bigger" : "smaller"}` });
  }
  if (c.position !== base.captions.position) items.push({ id: "captions.position", group: "Look", label: `Captions at the ${c.position ?? "style's usual place"}` });
  if (c.highlight_words.length) items.push({ id: "captions.highlight_words", group: "Look", label: `Highlight: ${c.highlight_words.join(", ")}` });
  if (plan.pacing.silence_threshold !== base.pacing.silence_threshold) {
    items.push({ id: "pacing.silence_threshold", group: "Pacing", label: `Cut pauses longer than ${plan.pacing.silence_threshold}s` });
  }
  if (plan.pacing.remove_fillers !== base.pacing.remove_fillers) {
    items.push({ id: "pacing.remove_fillers", group: "Pacing", label: plan.pacing.remove_fillers ? "Cut filler words" : "Keep filler words" });
  }
  if (plan.zoom.enabled !== base.zoom.enabled || plan.zoom.amount !== base.zoom.amount) {
    items.push({ id: "zoom", group: "Pacing", label: plan.zoom.enabled ? `Jump-cut zoom ${Math.round(plan.zoom.amount * 100)}%` : "No jump-cut zoom" });
  }
  if (plan.grade !== base.grade) items.push({ id: "grade", group: "Colour", label: `Colour: ${plan.grade.replace(/_/g, " ")}` });
  plan.cuts.forEach((r, i) => items.push({ id: `cuts.${i}`, group: "Cuts", label: `Remove ${mmss(r.start)}–${mmss(r.end)}`, detail: r.reason }));
  plan.zooms.forEach((r, i) => items.push({ id: `zooms.${i}`, group: "Zooms", label: `Zoom ${Math.round((r.amount ?? 1) * 100)}% at ${mmss(r.start)}–${mmss(r.end)}` }));
  plan.grades.forEach((r, i) => items.push({ id: `grades.${i}`, group: "Colour", label: `${(r.grade ?? "").replace(/_/g, " ")} at ${mmss(r.start)}–${mmss(r.end)}` }));
  plan.photos.forEach((p, i) => items.push({ id: `photos.${i}`, group: "Photos", label: `${p.file} at ${mmss(p.at)}`, detail: p.reason }));
  (plan.ai_clips ?? []).forEach((c, i) =>
    items.push({
      id: `ai_clips.${i}`,
      group: "B-roll & AI clips",
      label: `${brollWhere(c.source)} ${c.kind === "image" ? "picture" : "video clip"} at ${mmss(c.at)}: “${c.prompt}”${c.style && c.style !== "realistic" ? ` (${c.style.replace(/_/g, " ")})` : ""}`,
      detail: c.reason,
    }),
  );
  (plan.voiceovers ?? []).forEach((v, i) =>
    items.push({ id: `voiceovers.${i}`, group: "B-roll & AI clips", label: `AI voice-over at ${mmss(v.at)}: “${v.text}”`, detail: v.reason }),
  );
  return items;
}

/** The plan with only the accepted items; rejected ones go back to the preset value. */
export function acceptedPlan(plan: Plan, base: Plan, accepted: Set<string>): Plan {
  const keep = (id: string) => accepted.has(id);
  return {
    ...plan,
    style: keep("style") ? plan.style : base.style,
    grade: keep("grade") ? plan.grade : base.grade,
    pacing: {
      silence_threshold: keep("pacing.silence_threshold") ? plan.pacing.silence_threshold : base.pacing.silence_threshold,
      remove_fillers: keep("pacing.remove_fillers") ? plan.pacing.remove_fillers : base.pacing.remove_fillers,
    },
    zoom: keep("zoom") ? plan.zoom : base.zoom,
    captions: {
      enabled: keep("captions.enabled") ? plan.captions.enabled : base.captions.enabled,
      size_scale: keep("captions.size_scale") ? plan.captions.size_scale : base.captions.size_scale,
      position: keep("captions.position") ? plan.captions.position : base.captions.position,
      highlight_words: keep("captions.highlight_words") ? plan.captions.highlight_words : [],
    },
    cuts: plan.cuts.filter((_, i) => keep(`cuts.${i}`)),
    zooms: plan.zooms.filter((_, i) => keep(`zooms.${i}`)),
    grades: plan.grades.filter((_, i) => keep(`grades.${i}`)),
    photos: plan.photos.filter((_, i) => keep(`photos.${i}`)),
    ai_clips: (plan.ai_clips ?? []).filter((_, i) => keep(`ai_clips.${i}`)),
    voiceovers: (plan.voiceovers ?? []).filter((_, i) => keep(`voiceovers.${i}`)),
  };
}

export function formatCost(total: number | null | undefined): string {
  if (total === null || total === undefined) return "unknown";
  if (total === 0) return "$0";
  if (total < 0.01) return `$${total.toFixed(4)}`;
  return `$${total.toFixed(2)}`;
}

/** "B-roll" when it may come from your folder or stock first; "AI" when only AI makes it. */
function brollWhere(source: PlanAiClip["source"]): string {
  return source === "ai" ? "AI" : source === "library" ? "B-roll (your folder)" : source === "stock" ? "B-roll (free stock)" : "B-roll";
}
