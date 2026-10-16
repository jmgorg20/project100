// API keys, encrypted with Electron safeStorage (Windows: DPAPI) and stored in the app's
// data folder. Keys are only ever handed to the engine process as environment variables;
// they are never logged, and the window only learns whether a key is set.
import * as fs from "node:fs";
import * as path from "node:path";
import type { KeyName, KeysStatus } from "../shared/types";

export interface Encryptor {
  isEncryptionAvailable(): boolean;
  encryptString(plain: string): Buffer;
  decryptString(encrypted: Buffer): string;
}

const ENV_NAMES: Record<KeyName, string> = {
  groq: "GROQ_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  pexels: "PEXELS_API_KEY",
  pixabay: "PIXABAY_API_KEY",
};
const PROVIDERS = Object.keys(ENV_NAMES) as KeyName[];

export class KeyStore {
  constructor(private file: string, private crypto: Encryptor) {}

  private read(): Partial<Record<KeyName, string>> {
    try {
      return JSON.parse(fs.readFileSync(this.file, "utf-8"));
    } catch {
      return {};
    }
  }

  private write(data: Partial<Record<KeyName, string>>): void {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = `${this.file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(data), { encoding: "utf-8", mode: 0o600 });
    fs.renameSync(tmp, this.file);
  }

  private decrypt(provider: KeyName): string | null {
    const stored = this.read()[provider];
    if (!stored || !this.crypto.isEncryptionAvailable()) return null;
    try {
      return this.crypto.decryptString(Buffer.from(stored, "base64"));
    } catch {
      return null; // made on another PC or by another user: treat as not set
    }
  }

  set(provider: KeyName, key: string): void {
    const clean = key.trim();
    if (!PROVIDERS.includes(provider)) throw new Error(`Unknown provider ${provider}`);
    if (!clean) throw new Error("The key is empty.");
    if (/\s/.test(clean)) throw new Error("The key has spaces in it. Copy it again.");
    if (!this.crypto.isEncryptionAvailable()) {
      throw new Error("This computer cannot encrypt the key, so it was not saved. Use the .env file instead (see README).");
    }
    const data = this.read();
    data[provider] = this.crypto.encryptString(clean).toString("base64");
    this.write(data);
  }

  clear(provider: KeyName): void {
    const data = this.read();
    delete data[provider];
    this.write(data);
  }

  status(): KeysStatus {
    const one = (provider: KeyName) => {
      const key = this.decrypt(provider);
      return { set: Boolean(key), hint: key ? `••••${key.slice(-4)}` : "" };
    };
    return {
      encryptionAvailable: this.crypto.isEncryptionAvailable(),
      groq: one("groq"),
      anthropic: one("anthropic"),
      pexels: one("pexels"),
      pixabay: one("pixabay"),
    };
  }

  /** Environment variables for the engine process. */
  env(): Record<string, string> {
    const env: Record<string, string> = {};
    for (const provider of PROVIDERS) {
      const key = this.decrypt(provider);
      if (key) env[ENV_NAMES[provider]] = key;
    }
    return env;
  }
}
