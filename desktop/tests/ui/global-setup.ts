import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

// Fixtures are made by the real engine (needs Python + FFmpeg); reused if present.
export default function globalSetup() {
  const dir = path.join(__dirname, "fixtures");
  if (fs.existsSync(path.join(dir, "gen.status.json"))) return; // the last file written
  const python = process.platform === "win32" ? "python" : "python3";
  execFileSync(python, [path.join(__dirname, "make_fixtures.py")], { stdio: "inherit" });
}
