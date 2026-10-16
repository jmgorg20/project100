"""What this PC has: GPU name and VRAM, system RAM, free disk space.

Every probe is optional: anything that cannot be detected is reported as unknown with a
note, and nothing here ever stops the editor. The profile is saved, so a change of
hardware (new GPU, more RAM) is noticed and old benchmark results are not reused for it.
"""

import ctypes
import hashlib
import json
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

PROBE_TIMEOUT = 10


def _run(cmd, timeout=PROBE_TIMEOUT):
    """Output of a command, or None if it is missing, fails or hangs."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def nvidia_smi():
    return shutil.which("nvidia-smi")


def detect_gpus(notes):
    """[{name, vram_mb, driver, source}] for each GPU found."""
    smi = nvidia_smi()
    if smi:
        out = _run([smi, "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader,nounits"])
        if out is not None:
            gpus = []
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and parts[0]:
                    try:
                        vram = int(float(parts[1]))
                    except ValueError:
                        vram = None
                    gpus.append({"name": parts[0], "vram_mb": vram,
                                 "driver": parts[2] if len(parts) > 2 else None,
                                 "source": "nvidia-smi"})
            if gpus:
                return gpus
        notes.append("nvidia-smi is installed but did not answer; GPU details may be missing.")
    if platform.system() == "Windows":
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | "
                    "ConvertTo-Json -Compress"])
        if out:
            try:
                data = json.loads(out)
            except ValueError:
                data = []
            gpus = []
            for item in data if isinstance(data, list) else [data]:
                ram = item.get("AdapterRAM")
                # Windows reports at most 4 GB here (a 32-bit field), so only trust smaller values.
                vram = int(ram) // (1024 * 1024) if isinstance(ram, int) and 0 < ram < 4 * 1024 ** 3 else None
                gpus.append({"name": item.get("Name") or "Unknown GPU", "vram_mb": vram,
                             "driver": None, "source": "Windows"})
            if gpus:
                notes.append("VRAM could not be read reliably without nvidia-smi (NVIDIA driver).")
                return gpus
    notes.append("No GPU details found (nvidia-smi not available). AI generation needs an "
                 "NVIDIA GPU for WanGP; other features work without one.")
    return []


def detect_ram_mb(notes):
    system = platform.system()
    try:
        if system == "Windows":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys // (1024 * 1024)
        elif system == "Linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
        elif system == "Darwin":
            out = _run(["sysctl", "-n", "hw.memsize"])
            if out:
                return int(out.strip()) // (1024 * 1024)
    except (OSError, ValueError, AttributeError):
        pass
    notes.append("System RAM could not be detected.")
    return None


def disk_free_mb(paths):
    result = {}
    for path in paths:
        if not path:
            continue
        p = Path(path)
        while not p.exists() and p.parent != p:
            p = p.parent
        try:
            result[str(path)] = shutil.disk_usage(p).free // (1024 * 1024)
        except OSError:
            result[str(path)] = None
    return result


def hardware_key(gpus, ram_mb):
    """Changes when the GPU(s) or the amount of RAM change (rounded to whole GB)."""
    text = json.dumps({"gpus": [(g["name"], g["vram_mb"]) for g in gpus],
                       "ram_gb": round(ram_mb / 1024) if ram_mb else None}, sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def detect(paths=()):
    notes = []
    gpus = detect_gpus(notes)
    ram = detect_ram_mb(notes)
    return {
        "gpus": gpus,
        "ram_mb": ram,
        "disk_free_mb": disk_free_mb(paths),
        "os": f"{platform.system()} {platform.release()}".strip(),
        "detected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "key": hardware_key(gpus, ram),
        "notes": notes,
    }


def describe(profile):
    """One plain line, e.g. 'NVIDIA GeForce RTX 3060 (12 GB VRAM), 32 GB RAM'."""
    parts = []
    for gpu in profile["gpus"]:
        vram = f"{gpu['vram_mb'] / 1024:.0f} GB VRAM" if gpu.get("vram_mb") else "VRAM unknown"
        parts.append(f"{gpu['name']} ({vram})")
    if not profile["gpus"]:
        parts.append("no GPU detected")
    parts.append(f"{profile['ram_mb'] / 1024:.0f} GB RAM" if profile.get("ram_mb")
                 else "RAM unknown")
    return ", ".join(parts)


def load_profile(store, paths=()):
    """Detect the hardware now and save it. Returns (profile, changed, previous).

    `changed` is True when the hardware differs from the last saved profile.
    """
    store = Path(store)
    try:
        previous = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    current = detect(paths)
    changed = bool(previous) and previous.get("key") != current["key"]
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(current, indent=1), encoding="utf-8")
    except OSError:
        current["notes"].append(f"Could not save the hardware profile to {store}.")
    return current, changed, previous


class VramSampler:
    """Peak GPU memory in use while a job runs, sampled with nvidia-smi (if available).

    Measures the whole GPU (other programs included), so `peak_mb - baseline_mb` is an
    approximation of what the job needed; a short spike between two readings is missed.
    """

    def __init__(self, gpu_index=0, interval=0.5):
        self.smi = nvidia_smi()
        self.gpu_index, self.interval = gpu_index, interval
        self.baseline_mb = self.peak_mb = None
        self._stop = threading.Event()
        self._thread = None

    def _used(self):
        out = _run([self.smi, f"--id={self.gpu_index}", "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits"], timeout=5)
        try:
            return int(float(out.strip().splitlines()[0])) if out else None
        except (ValueError, IndexError):
            return None

    def __enter__(self):
        if self.smi:
            self.baseline_mb = self._used()
            self.peak_mb = self.baseline_mb

            def loop():
                while not self._stop.wait(self.interval):
                    used = self._used()
                    if used is not None:
                        self.peak_mb = max(self.peak_mb or 0, used)
            self._thread = threading.Thread(target=loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
            used = self._used()               # one last reading: very short jobs still count
            if used is not None:
                self.peak_mb = max(self.peak_mb or 0, used)

    @property
    def job_peak_mb(self):
        if self.peak_mb is None or self.baseline_mb is None:
            return None
        return max(0, self.peak_mb - self.baseline_mb)
