"""ledger - how Anchor's code jobs are doing, by size and tier, and which chores still want a Foundry tool.

  python C:/dev/foundry-tools/ft.py ledger [--days 30] [--line] [--json]

John 2026-10-13: small jobs may run one model tier down at a lower effort; the steward tracks and calibrates that and
recommends new tools. Read-only and derived: the job list is Anchor's speed.jsonl (one row per finished attempt), each
job's own record (.ecgberht/code-jobs.json in its steward's folder), the Foundry tools' usage log and PROPOSALS.md. It
never writes anything. The numbers are prompts to look, not proof."""
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FT = HERE.parent
JOBS = Path(os.environ.get("ANCHOR_CODE_JOBS_DIR") or "C:/dev/Anchor-code-jobs")
USAGE = Path(os.environ.get("FOUNDRY_TOOLS_USAGE_DIR") or FT / ".usage")
PROPOSALS = FT / "PROPOSALS.md"
CAUSES = (("review", "the review"), ("check failed", "the check"), ("turn ended in an error", "the worker failed"),
          ("changed during the job", "outside writes"), ("outside the coder's own files", "outside writes"),
          ("tools did not write", "outside writes"), ("nothing", "nothing made"), ("stopped", "stopped"),
          ("usage limit", "usage limit"), ("missing or unsafe", "reading copy missing"))


def rows(days, name="speed.jsonl"):
    """Rows of one of Anchor's job logs from the last ``days``: speed.jsonl (timing, one row per finished attempt) or
    jobs-index.jsonl (one pointer per started job - so a job that failed before its timing line is still counted)."""
    since = time.time() - days * 86400
    out = []
    try:
        text = (JOBS / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("job") and (r.get("at") or 0) >= since:
            out.append(r)
    return out


def records(steward_dirs):
    """{job id: record} from each steward folder's own code-jobs.json (read once per folder)."""
    found = {}
    for d in steward_dirs:
        try:
            data = json.loads((Path(d) / ".ecgberht" / "code-jobs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        jobs = data.get("jobs", data) if isinstance(data, dict) else {}
        for jid, rec in (jobs.items() if isinstance(jobs, dict) else []):
            if isinstance(rec, dict):
                found[jid] = rec
    return found


def _timed(rec, jrows):
    """Every attempt of the job left its timing row (a stopped attempt leaves none)."""
    return not rec or len({r.get("attempt") or 1 for r in jrows}) >= int(rec.get("attempt") or 1)


def _ended_at(rec):
    try:
        return time.mktime(time.strptime(str((rec or {}).get("finished") or ""), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return 0


def cause(note):
    n = (note or "").lower()
    for key, label in CAUSES:
        if key in n:
            return label
    return "other"


def kind(rec):
    tier = str((rec or {}).get("tier") or "")
    if tier.startswith("small"):
        want = (tier.split()[1:2] or [""])[0].lower()       # "small: sonnet high" -> sonnet
        served = str(rec.get("model_served") or "").lower()
        if not served:                                       # five r2 #3: unknown is not a confirmed small job
            return "small, served model unreported"
        if want and want not in served:                      # five r1 #3: judged on the model that actually ran
            return "small, other model served"
        return "small"
    if "small unavailable" in tier:
        return "small fell back"
    return "standard" if rec else "no record"


def tool_runs(days):
    since, out = time.time() - days * 86400, {}
    for f in sorted(USAGE.glob("*.jsonl")) if USAGE.is_dir() else []:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if (e.get("at_epoch") or 0) < since or e.get("tool") in (None, "propose"):
                continue
            r = out.setdefault(e["tool"], [0, 0])
            r[0] += 1
            r[1] += e.get("exit") not in (0, None)
    return out


def proposals():
    try:
        text = PROPOSALS.read_text(encoding="utf-8")
    except OSError:
        return []
    return [m.group(1) for m in re.finditer(r"^## (\S+) - proposed[^\n]*\n(?:(?!^## ).*\n)*?- Status: waiting", text, re.M)]


def build(days):
    rs, started = rows(days), rows(days, "jobs-index.jsonl")
    every = rows(36500)                                   # five r3 #7 / r5 #3: history outside the window still counts
    recs = records({r.get("steward_dir") for r in rs + started + rows(36500, "jobs-index.jsonl") if r.get("steward_dir")})
    since = time.time() - days * 86400
    chosen = {r["job"] for r in started} | {r["job"] for r in rs}
    for r in rows(36500, "jobs-index.jsonl"):             # five r9: a job that ended in the window, however early it began
        if _ended_at(recs.get(r["job"])) >= since:
            chosen.add(r["job"])
    by_job = {j: [] for j in chosen}
    for r in every:                                       # five r5 #3: a chosen job's whole attempt history
        if r.get("job") in by_job:
            by_job[r["job"]].append(r)
    escalated = {rec.get("escalates"): jid for jid, rec in recs.items() if rec.get("escalates")}
    groups, misses, chores, helpers = {}, {}, {}, {}
    unconfirmed = []
    for jid, jrows in by_job.items():
        rec = recs.get(jid)
        if rec and rec.get("status") in ("running", "finishing"):
            continue                                      # still at work: counted when it ends
        k = kind(rec)
        g = groups.setdefault(k, {"jobs": 0, "first": 0, "landed": 0, "worker": [], "delivery": [], "escalated": 0})
        g["jobs"] += 1
        first = min(jrows, key=lambda r: r.get("attempt") or 1) if jrows else {}
        if rec and rec.get("landed") and (rec.get("attempt") or 1) == 1:
            g["first"] += 1
        if rec and rec.get("landed"):
            g["landed"] += 1
        elif rec and rec.get("status") not in ("running", "finishing"):
            c = cause(rec.get("land_note") or rec.get("error"))
            misses[c] = misses.get(c, 0) + 1
        if first.get("worker_minutes") is not None:
            g["worker"].append(first["worker_minutes"])
        total = sum((r.get("minutes") or 0) for r in jrows)     # a re-filing's row holds only its own minutes
        incomplete = not _timed(rec, jrows)
        if jid in escalated:                              # five r13: a redo pair is whole only if both are
            redo = escalated[jid]
            incomplete = incomplete or not _timed(recs.get(redo), [r for r in every if r.get("job") == redo])
        if incomplete:
            g["timing_incomplete"] = g.get("timing_incomplete", 0) + 1     # five r12: an attempt left no timing
            total = 0                                                       # (a stop): never a short total
        if jid in escalated:
            g["escalated"] += 1
            total += sum((r.get("minutes") or 0) for r in every if r.get("job") == escalated[jid])
        parent = (rec or {}).get("escalates")
        if parent and parent not in by_job and not incomplete                 and _timed(recs.get(parent), [r for r in every if r.get("job") == parent]):   # five r4 #2 / r13: whole pairs only
            pk = kind(recs.get(parent))                   # so the pair is counted here, once, under the small job's size
            pg = groups.setdefault(pk, {"jobs": 0, "first": 0, "landed": 0, "worker": [], "delivery": [], "escalated": 0})
            pg["delivery"].append(total + sum((r.get("minutes") or 0) for r in every if r.get("job") == parent))
        elif total and not parent and not incomplete:     # five r14: an incomplete pair is never a sample
            g["delivery"].append(total)
        if k.startswith("small,"):
            unconfirmed.append(jid)
        for cat, v in (first.get("by_category") or {}).items():
            if cat == "other commands" or not isinstance(v, dict):
                continue
            c = chores.setdefault(cat, [0.0, set()])
            c[0] += (v.get("run_min") or 0) + (v.get("think_min") or 0)
            c[1].add(jid)
        for h in first.get("helpers_written") or []:
            helpers.setdefault(Path(str(h)).name, set()).add(jid)
    med = lambda xs: round(statistics.median(xs), 1) if xs else None
    return {
        "days": days,
        "groups": {k: {"jobs": g["jobs"], "landed_first_time": g["first"], "landed": g["landed"],
                       "median_worker_min": med(g["worker"]), "median_delivery_min": med(g["delivery"]),
                       "escalated": g["escalated"], "timing_incomplete": g.get("timing_incomplete", 0)}
                   for k, g in groups.items()},
        "top_misses": sorted(misses.items(), key=lambda x: -x[1])[:3],
        "small_tier_unconfirmed": unconfirmed,
        "chores_by_hand": sorted(((c, round(m, 1), len(j)) for c, (m, j) in chores.items()), key=lambda x: -x[1])[:5],
        "helpers_repeated": sorted((h, len(j)) for h, j in helpers.items() if len(j) >= 2),
        "tools": tool_runs(days),
        "proposals_waiting": proposals(),
    }


def line(d):
    gs = d["groups"]
    n = sum(g["jobs"] for g in gs.values())
    first = sum(g["landed_first_time"] for g in gs.values())
    asked = [g for k, g in gs.items() if k.startswith("small") and k != "small fell back"]
    small = {"jobs": sum(g["jobs"] for g in asked), "escalated": sum(g["escalated"] for g in asked),
             "confirmed": gs.get("small", {}).get("jobs", 0)}
    miss = d["top_misses"][0][0] if d["top_misses"] else "none"
    runs = sum(r[0] for r in d["tools"].values())
    return ("ledger %dd: %d jobs, %d landed first time; small tier asked %d (%d confirmed, %d escalated); top miss: %s; Foundry tool runs %d; "
            "proposals waiting %d" % (d["days"], n, first, small.get("jobs", 0), small.get("confirmed", 0), small.get("escalated", 0), miss, runs,
                                      len(d["proposals_waiting"])))


def show(d):
    print("THE JOB LEDGER - last %d days (prompts to look, not proof)" % d["days"])
    if not d["groups"]:
        print("no finished jobs recorded")
    for k, g in sorted(d["groups"].items()):
        print("  %-16s %3d jobs  %3d landed first time  %3d landed  median worker %s min  median delivery %s min  "
              "%d escalated" % (k, g["jobs"], g["landed_first_time"], g["landed"], g["median_worker_min"],
                                g["median_delivery_min"], g["escalated"]))
    if d["small_tier_unconfirmed"]:
        print("  small jobs whose served model was not the tier asked for (or unreported): %s"
              % ", ".join(d["small_tier_unconfirmed"][:6]))
    print("not landed, top causes: %s" % (", ".join("%s %d" % m for m in d["top_misses"]) or "none"))
    print("chores still done by hand (minutes, jobs): %s"
          % (", ".join("%s %.1f min in %d" % c for c in d["chores_by_hand"]) or "none seen"))
    if d["helpers_repeated"]:
        print("helper scripts written by hand in more than one job: %s"
              % ", ".join("%s (%d)" % h for h in d["helpers_repeated"]))
    print("Foundry tool runs: %s" % (", ".join("%s %d (%d failed)" % (t, r[0], r[1])
                                                for t, r in sorted(d["tools"].items())) or "none"))
    print("tool proposals waiting for John: %s" % (", ".join(d["proposals_waiting"]) or "none"))
    print("calibration prompts: with 20+ small jobs, escalations at or under 15% suggest widening small; over 25%, "
          "or any small job John rejected, suggest narrowing it. Tiers change only by John's word.")


def main(argv):
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 30
    d = build(days)
    if "--json" in argv:
        print(json.dumps(d, default=list))
    elif "--line" in argv:
        print(line(d))
    else:
        show(d)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
