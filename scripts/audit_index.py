"""Print the Premium Editorial audit as one table: the M2 column of docs/premium-editorial-audit.md,
then one column per milestone file docs/audit/m<N>.md (read in milestone order). Each milestone PR
adds its own file, so no two PRs edit the same lines.

    python scripts/audit_index.py            # Markdown table to stdout
    python scripts/audit_index.py --check    # exit 1 if a milestone file misses one of the 30 rows
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "docs" / "premium-editorial-audit.md"
FOLDER = ROOT / "docs" / "audit"
ROW = re.compile(r"^\| (\d+) \| ([^|]+?) \|(.*)\|$")


def rows_of(text, status_col, seen_col=None):
    """{technique number: (name, seen at, status)} from the rows of a Markdown table."""
    out = {}
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(3).split("|")]
        if len(cells) <= status_col:
            continue
        out[int(m.group(1))] = (m.group(2).strip(), cells[seen_col] if seen_col is not None else "",
                                cells[status_col])
    return out


def milestones():
    """[(label, {n: (name, seen, status)})]: M2 from the main audit, then every docs/audit/m<N>.md."""
    main = MAIN.read_text(encoding="utf-8")
    table = main[main.index("After M2"):] if "After M2" in main else main
    cols = [("M2", rows_of(table, 1, 0))]
    files = sorted(FOLDER.glob("m*.md"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    for f in files:
        cols.append((f.stem.upper(), rows_of(f.read_text(encoding="utf-8"), 1, 0)))
    return cols


def main(argv):
    cols = milestones()
    missing = [(label, n) for label, rows in cols for n in range(1, 31) if n not in rows]
    if "--check" in argv:
        for label, n in missing:
            print(f"{label}: technique {n} is missing")
        return 1 if missing else 0
    first = cols[0][1]
    print("| # | Technique | Seen at | " + " | ".join(f"After {label}" for label, _ in cols) + " |")
    print("|---|---|---|" + "---|" * len(cols))
    for n in range(1, 31):
        name, seen, _ = first.get(n, ("?", "", ""))
        seen = next((r[n][1] for _l, r in cols if n in r and r[n][1]), seen)
        print(f"| {n} | {name} | {seen} | " + " | ".join(r.get(n, ("", "", "—"))[2] for _l, r in cols) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
