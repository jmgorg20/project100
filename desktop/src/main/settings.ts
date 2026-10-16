// App settings (JSON in the app's data folder), with safe defaults.
import * as fs from "node:fs";
import * as path from "node:path";
import type { Settings } from "../shared/types";

export function defaultSettings(platform: string, engineDir: string): Settings {
  return {
    pythonPath: platform === "win32" ? "python" : "python3",
    engineDir,
    outputDir: path.join(engineDir, "output"),
    provider: "groq",
    groqModel: "openai/gpt-oss-120b",
    anthropicModel: "claude-opus-5-5",
    transcribeWith: "groq",
    autoMode: true,
    consentAccepted: false,
  };
}

/** Keep only known keys with the right types; anything else falls back to the default. */
export function cleanSettings(value: unknown, defaults: Settings): Settings {
  const input = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  const out: Settings = { ...defaults };
  for (const key of Object.keys(defaults) as (keyof Settings)[]) {
    const v = input[key];
    if (typeof v === typeof defaults[key] && v !== "") (out as unknown as Record<string, unknown>)[key] = v;
  }
  if (out.provider !== "groq" && out.provider !== "anthropic") out.provider = defaults.provider;
  if (out.transcribeWith !== "groq" && out.transcribeWith !== "local") out.transcribeWith = defaults.transcribeWith;
  return out;
}

export function loadSettings(file: string, defaults: Settings): Settings {
  try {
    return cleanSettings(JSON.parse(fs.readFileSync(file, "utf-8")), defaults);
  } catch {
    return { ...defaults };
  }
}

export function saveSettings(file: string, settings: Settings): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(settings, null, 1), "utf-8");
  fs.renameSync(tmp, file);
}
