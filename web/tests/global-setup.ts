import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

// Test media made with FFmpeg: a short talking-style video (about 3 MB: several upload pieces) and a photo.
export default function globalSetup() {
  const dir = path.join(HERE, ".media");
  fs.mkdirSync(dir, { recursive: true });
  const video = path.join(dir, "talk.mp4");
  if (!fs.existsSync(video)) {
    execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=3", "-f", "lavfi",
      "-i", "sine=f=330:r=48000:d=3", "-vf", "noise=alls=60:allf=t", "-c:v", "libx264", "-preset", "ultrafast",
      "-b:v", "8M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video]);
  }
  const photo = path.join(dir, "photo.png");
  if (!fs.existsSync(photo)) {
    execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x3366cc:s=640x640", "-frames:v", "1", photo]);
  }
}
