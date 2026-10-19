"""The audit is one file per milestone plus a printed index, so milestone PRs never edit the same lines."""
import subprocess
import sys

from autoedit import PROJECT_DIR

SCRIPT = PROJECT_DIR / "scripts" / "audit_index.py"


def test_every_milestone_file_covers_the_30_techniques():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_the_index_has_a_column_per_milestone():
    out = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=True).stdout
    lines = out.splitlines()
    assert "After M2" in lines[0] and "After M3" in lines[0]
    assert len([ln for ln in lines if ln.startswith("| ") and ln[2].isdigit()]) == 30
