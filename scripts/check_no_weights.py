"""Fail if AI model weights would ship with AutoEdit: the repository, the service's requirements and
the container images must never include model files or fetch them. (The desktop app downloads the
optional tracking / local-transcription models only when the person asks for it; the cloud service
uses hosted AI and needs none.)

    python scripts/check_no_weights.py          # exit 0 = clean; otherwise lists each problem
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEIGHT_EXTENSIONS = {".safetensors", ".gguf", ".ggml", ".ckpt", ".pt", ".pth", ".onnx", ".tflite", ".task", ".h5",
                     ".pb", ".bin", ".npz", ".mlmodel", ".pkl", ".joblib", ".msgpack", ".engine", ".plan"}
MAX_TRACKED_BYTES = 15 * 1024 * 1024
# packages that bundle or fetch model weights; none belongs in the cloud images
WEIGHT_PACKAGES = ("faster-whisper", "openai-whisper", "torch", "tensorflow", "transformers", "diffusers",
                   "mediapipe", "onnxruntime", "ctranslate2", "huggingface-hub", "sentence-transformers")
IMAGE_FILES = ("requirements-service.txt", "requirements-worker.txt", "deploy/Dockerfile.api",
               "deploy/Dockerfile.worker", "deploy/docker-compose.yml")
FETCH_MARKERS = ("huggingface.co", "hf_hub_download", "from_pretrained", "storage.googleapis.com/mediapipe-models",
                 "civitai.com", ".safetensors", ".gguf")


def tracked_files(root):
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
        return [root / p for p in out.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts]


def requirement_names(text):
    names = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            name = line.split(";")[0]
            for sep in ("[", "=", ">", "<", "~", "!", " "):
                name = name.split(sep)[0]
            names.append(name.strip().lower().replace("_", "-"))
    return names


def check(root=ROOT):
    problems = []
    for path in tracked_files(root):
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() in WEIGHT_EXTENSIONS and "fixtures" not in path.parts:
            problems.append(f"{rel}: looks like model weights ({path.suffix})")
        elif path.stat().st_size > MAX_TRACKED_BYTES:
            problems.append(f"{rel}: {path.stat().st_size // (1024 * 1024)} MB is too big for the repository")
    for name in IMAGE_FILES:
        path = root / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if name.endswith(".txt"):
            for pkg in requirement_names(text):
                if pkg in WEIGHT_PACKAGES:
                    problems.append(f"{name}: {pkg} brings or downloads model weights")
        for marker in FETCH_MARKERS:
            if marker in text:
                problems.append(f"{name}: fetches model files ({marker})")
        if name.startswith("deploy/Dockerfile") and ("COPY models" in text or "COPY . " in text):
            problems.append(f"{name}: copies the models folder (or everything) into the image")
    return problems


def main():
    problems = check()
    for p in problems:
        print("✗", p)
    if not problems:
        print("✓ no model weights in the repository, the requirements or the images")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
