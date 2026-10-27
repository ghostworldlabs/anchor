"""scout: proactive workflow bottleneck & tool-acquisition detector for Steward and Skill Foundry.

  python C:/dev/foundry-tools/ft.py scout [--days 14] [--json]

Scans Anchor's code-job speed log (`speed.jsonl`), Foundry tool usage logs (`.usage/*.jsonl`), and `PROPOSALS.md`
to surface:
1. Slow steps / jobs where `other_s` or `check_s` exceeded 60s.
2. Jobs that wrote ad-hoc one-off helpers by hand (`adhoc_helpers`).
3. Pending tool proposals in `PROPOSALS.md` vs. already-installed tools in `INDEX.json`.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FT = HERE.parent
JOBS = Path(os.environ.get("ANCHOR_CODE_JOBS_DIR") or "C:/dev/Anchor-code-jobs")
PROPOSALS = FT / "PROPOSALS.md"
INDEX = FT / "INDEX.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Proactively detect workflow slowdowns and tool gaps.")
    ap.add_argument("--days", type=int, default=14, help="Lookback window in days (default: 14)")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args(argv)

    since = time.time() - args.days * 86400
    installed = set()
    try:
        for t in json.loads(INDEX.read_text(encoding="utf-8")).get("tools") or []:
            installed.add(t.get("name"))
    except Exception:
        pass

    slow_jobs = []
    adhoc_counts = {}
    speed_file = JOBS / "speed.jsonl"
    if speed_file.is_file():
        for line in speed_file.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict) or (r.get("at") or 0) < since:
                continue
            other_s = float(r.get("other_s") or 0)
            check_s = float(r.get("check_s") or 0)
            if other_s >= 60 or check_s >= 60:
                slow_jobs.append({
                    "job": r.get("job"),
                    "other_s": round(other_s, 1),
                    "check_s": round(check_s, 1),
                    "slowest": r.get("slowest_cmd") or "",
                })
            for h in r.get("adhoc_helpers") or []:
                adhoc_counts[h] = adhoc_counts.get(h, 0) + 1

    proposals = []
    if PROPOSALS.is_file():
        for m in re.finditer(r"^##\s+([\w-]+)\s+-\s+proposed\s+([^\n]+)\n((?:- [^\n]+\n?)+)",
                             PROPOSALS.read_text(encoding="utf-8", errors="replace"), re.M):
            name, when, body = m.group(1), m.group(2).strip(), m.group(3)
            status = "shipped" if name in installed else "pending"
            why_m = re.search(r"^- Why:\s*(.+)$", body, re.M)
            proposals.append({
                "name": name,
                "proposed_at": when,
                "status": status,
                "why": (why_m.group(1).strip()[:180] if why_m else ""),
            })

    report = {
        "days": args.days,
        "installed_tools": sorted(installed),
        "slow_jobs_count": len(slow_jobs),
        "slow_jobs_top": sorted(slow_jobs, key=lambda x: -(x["other_s"] + x["check_s"]))[:5],
        "adhoc_helpers": adhoc_counts,
        "proposals": proposals,
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Foundry Proactive Scout (last {args.days} days) — {len(installed)} tools installed")
    pending = [p for p in proposals if p["status"] == "pending"]
    shipped = [p for p in proposals if p["status"] == "shipped"]
    print(f"  Proposals: {len(pending)} pending, {len(shipped)} shipped ({', '.join(p['name'] for p in shipped) or 'none'})")
    for p in pending:
        print(f"    - [PENDING] {p['name']} ({p['proposed_at']}): {p['why']}")
    if report["slow_jobs_top"]:
        print(f"  Slow job intervals (>=60s non-model time): {len(slow_jobs)} total")
        for s in report["slow_jobs_top"]:
            print(f"    - job {s['job']}: other={s['other_s']}s, check={s['check_s']}s")
    if adhoc_counts:
        print("  Ad-hoc helpers written by hand: " + ", ".join(f"{k} ({v}x)" for k, v in adhoc_counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
