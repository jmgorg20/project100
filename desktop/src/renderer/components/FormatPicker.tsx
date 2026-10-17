// The AI panel's video format menu (Reaction, Listicle, Clone yourself, ...) and the extra files
// the chosen format needs. The formats come from the engine (autoedit/formats/*.json via ui-data),
// so a new format shows up here without changing this file.
import data from "../../shared/engine-data.json";
import type { FormatInfo } from "../../shared/types";
import { api } from "../lib/api";

export const FORMATS = (data as unknown as { formats: FormatInfo[] }).formats;

export interface FormatChoice {
  /** "" = from your words (rules), "auto" = the AI picks, else a format id. */
  format: string;
  inputs: Record<string, string[]>;
  items: string;
  offset: number;
}

export const NO_FORMAT: FormatChoice = { format: "", inputs: {}, items: "", offset: 0 };

const base = (p: string) => p.split(/[\\/]/).pop() ?? p;
const LIST_FORMATS = ["listicle", "ranking"];
const OFFSET_ROLES = ["source", "screen", "second"];

/** The job request fields for a choice. */
export function formatRequest(choice: FormatChoice) {
  if (!choice.format) return {};
  const spec = FORMATS.find((f) => f.id === choice.format);
  const roles = new Set(spec?.inputs.map((i) => i.role) ?? []);
  const formatInputs = Object.fromEntries(
    Object.entries(choice.inputs).filter(([role, files]) => files.length && roles.has(role) && role !== "voiceover"),
  );
  const items = LIST_FORMATS.includes(choice.format) ? choice.items.split("\n").map((s) => s.trim()).filter(Boolean) : [];
  const offsetRole = spec?.inputs.find((i) => OFFSET_ROLES.includes(i.role))?.role;
  return {
    format: choice.format,
    ...(Object.keys(formatInputs).length ? { formatInputs } : {}),
    ...(items.length ? { items } : {}),
    ...(offsetRole && choice.offset ? { offsets: { [offsetRole]: choice.offset } } : {}),
  };
}

/** What still needs a file before the format can run (the main video comes from the list). */
export function missingRoles(choice: FormatChoice): string[] {
  const spec = FORMATS.find((f) => f.id === choice.format);
  if (!spec) return [];
  return spec.inputs.filter((i) => i.required && i.role !== "main" && !choice.inputs[i.role]?.length).map((i) => i.label);
}

export function FormatPicker({ value, onChange }: { value: FormatChoice; onChange: (v: FormatChoice) => void }) {
  const spec = FORMATS.find((f) => f.id === value.format);
  // Files only: text inputs (Listicle items) have their own box below.
  const roles = spec?.inputs.filter((i) => i.role !== "main" && !i.kinds.includes("text")) ?? [];
  const missing = missingRoles(value);
  const set = (patch: Partial<FormatChoice>) => onChange({ ...value, ...patch });
  const setFiles = (role: string, files: string[]) => set({ inputs: { ...value.inputs, [role]: files } });
  const hasOffset = roles.some((r) => OFFSET_ROLES.includes(r.role));

  return (
    <div className="stack" style={{ gap: 6 }} data-testid="format-picker">
      <label className="field small">
        Video format · Uri ng video
        <select aria-label="Video format" value={value.format} onChange={(e) => onChange({ ...NO_FORMAT, format: e.target.value })} data-testid="format-select">
          <option value="">From my words · Ayon sa sinabi ko</option>
          <option value="auto">Let the AI pick · AI ang pipili</option>
          {FORMATS.map((f) => (
            <option key={f.id} value={f.id}>{f.name}{f.tl !== f.name ? ` · ${f.tl}` : ""}</option>
          ))}
        </select>
      </label>
      {spec && <span className="muted small" data-testid="format-about">{spec.about} <em>{spec.about_tl}</em></span>}
      {roles.map((r) => {
        const files = value.inputs[r.role] ?? [];
        const many = Boolean(r.multiple);
        const full = many && r.max !== undefined && files.length >= r.max;
        return (
          <div className="stack" style={{ gap: 4 }} key={r.role} data-testid={`format-role-${r.role}`}>
            <div className="row">
              <span className="small" style={{ flex: 1 }}>
                {r.label} · <span className="muted">{r.tl}</span>{r.required ? "" : " (optional)"}
              </span>
              <button
                className="btn small"
                aria-label={`Choose: ${r.label}`}
                disabled={full}
                onClick={async () => {
                  const picked = await api.pickFormatFiles(r.kinds, many);
                  const merged = [...files, ...picked.filter((x) => !files.includes(x))];
                  if (picked.length) setFiles(r.role, many ? merged.slice(0, r.max ?? merged.length) : picked.slice(0, 1));
                }}
              >
                Choose…
              </button>
            </div>
            {files.length > 0 && (
              <div className="chips">
                {files.map((f) => (
                  <span className="chip" key={f} title={f}>
                    <span>{base(f)}</span>
                    <button onClick={() => setFiles(r.role, files.filter((x) => x !== f))} aria-label={`Remove ${base(f)}`}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {LIST_FORMATS.includes(value.format) && (
        <label className="field small">
          Items, one per line (optional: otherwise found in what you say) · Mga item, isa bawat linya
          <textarea aria-label="Items" rows={3} value={value.items} onChange={(e) => set({ items: e.target.value })} data-testid="format-items" />
        </label>
      )}
      {hasOffset && (
        <label className="field small">
          Second video starts later by (seconds) · Pagkaantala ng pangalawang video
          <input type="number" step={0.1} aria-label="Second video offset" value={value.offset} onChange={(e) => set({ offset: Number(e.target.value) || 0 })} />
        </label>
      )}
      {value.format === "clone" && (
        <span className="muted small">Keep the camera still for every take. Ikaw lang ang gumalaw; huwag galawin ang camera.</span>
      )}
      {missing.length > 0 && (
        <span className="small warn" data-testid="format-missing">Still needed · Kailangan pa: {missing.join(", ")}</span>
      )}
    </div>
  );
}
