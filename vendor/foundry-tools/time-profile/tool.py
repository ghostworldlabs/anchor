"""time-profile: where a worker's time went - commands running vs model and other time (the gaps between steps:
mostly the model, but not provably), the slowest steps, and the helper scripts it wrote by hand (Foundry tool
candidates). Overlapping commands are counted once.

  ft.py time-profile --worktree <folder the worker ran in>     finds its Claude and ChatGPT (Codex) session logs
  ft.py time-profile --session <transcript.jsonl>               one log
  [--since ISO] [--json] [--top N]

Reads ~/.claude/projects/<folder slug>/*.jsonl and ~/.codex/sessions/**/rollout-*.jsonl (matched by working folder)."""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_EXT = (".py", ".mjs", ".js", ".ps1", ".sh", ".cjs", ".ts")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def category(name, text):
    s = text.lower()
    if name in ("Read", "Grep", "Glob", "read_file", "list_dir", "grep_files"):
        return "reading"
    if name in ("Edit", "Write", "MultiEdit", "apply_patch", "NotebookEdit"):
        return "editing"
    if "foundry-tools/ft.py" in s or "foundry-tools\\ft.py" in s:
        return "foundry tool"
    if "playwright" in s or "screenshot" in s or "chromium" in s or "headless" in s:
        return "screenshots"
    if ".pdf" in s or "reportlab" in s or "weasyprint" in s or "print-to-pdf" in s or "pandoc" in s:
        return "pdf making"
    if "sha256" in s or "hashlib" in s or "receipt" in s or "manifest" in s or "provenance" in s:
        return "receipts/hashes"
    if re.search(r"\bsleep\b|time\.sleep|start-sleep|wait-poll|until .*; do", s):
        return "waiting"
    if "pytest" in s or "node --test" in s or "npm test" in s:
        return "tests"
    if re.search(r"\bgit\b", s):
        return "git"
    if name in ("WebSearch", "WebFetch", "web_search"):
        return "web"
    return "other commands"


def helper_written(name, text):
    """A script file the worker created by hand (Write of a script, a here-doc into one, an apply_patch Add File)."""
    out = []
    if name == "Write":
        try:
            p = json.loads(text).get("file_path", "")
        except ValueError:
            p = ""
        if p.lower().endswith(SCRIPT_EXT):
            out.append(p)
    for m in re.finditer(r"\*\*\* Add File: ([^\n\\]+)", text):
        if m.group(1).strip().lower().endswith(SCRIPT_EXT):
            out.append(m.group(1).strip())
    for m in re.finditer(r"cat\s*>\s*[\"']?([^\s\"'<>]+)[\"']?\s*<<", text):
        if m.group(1).lower().endswith(SCRIPT_EXT):
            out.append(m.group(1))
    return out


def claude_steps(path):
    ev = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if "timestamp" in e:
            ev.append(e)
    ev.sort(key=lambda e: e["timestamp"])
    uses, steps = {}, []
    for i, e in enumerate(ev):
        msg = e.get("message") or {}
        cont = msg.get("content") if isinstance(msg.get("content"), list) else []
        if e.get("type") == "assistant":
            for c in cont:
                if c.get("type") == "tool_use":
                    uses[c["id"]] = (ts(e["timestamp"]), c["name"], json.dumps(c.get("input", {}), ensure_ascii=False))
        elif e.get("type") == "user":
            for c in cont:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in uses:
                    t0, name, text = uses.pop(c["tool_use_id"])
                    t1 = ts(e["timestamp"])
                    nxt = next((ts(x["timestamp"]) for x in ev[i + 1:] if x.get("type") == "assistant"), t1)
                    steps.append({"at": t0, "name": name, "text": text, "run": t1 - t0, "think": max(0.0, nxt - t1)})
    span = (ts(ev[0]["timestamp"]), ts(ev[-1]["timestamp"])) if ev else (0, 0)
    return steps, span


def codex_steps(path):
    ev = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("timestamp"):
            ev.append(e)
    calls, steps = {}, []
    for i, e in enumerate(ev):
        p = e.get("payload") or {}
        kind = p.get("type")
        if kind in ("function_call", "custom_tool_call", "local_shell_call"):
            args = p.get("arguments") or p.get("input") or json.dumps(p.get("action") or {})
            calls[p.get("call_id")] = (ts(e["timestamp"]), p.get("name") or kind, str(args))
        elif kind in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            c = calls.pop(p.get("call_id"), None)
            if c:
                t1 = ts(e["timestamp"])
                nxt = next((ts(x["timestamp"]) for x in ev[i + 1:]
                            if (x.get("payload") or {}).get("type") in ("function_call", "custom_tool_call",
                                                                         "local_shell_call", "message")), t1)
                steps.append({"at": c[0], "name": c[1], "text": c[2], "run": t1 - c[0], "think": max(0.0, nxt - t1)})
    span = (ts(ev[0]["timestamp"]), ts(ev[-1]["timestamp"])) if ev else (0, 0)
    return steps, span


def claude_logs(folder):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(folder).resolve()))
    home = Path.home() / ".claude" / "projects"
    return sorted(glob.glob(str(home / slug / "*.jsonl")), key=os.path.getmtime)


def codex_logs(folder, since=None):
    want = os.path.normcase(str(Path(folder).resolve()))
    root = Path.home() / ".codex" / "sessions"
    found = []
    for f in glob.glob(str(root / "**" / "rollout-*.jsonl"), recursive=True):
        if since and os.path.getmtime(f) < since:
            continue
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for _ in range(5):
                    line = fh.readline()
                    if not line:
                        break
                    e = json.loads(line)
                    if e.get("type") == "session_meta":
                        cwd = (e.get("payload") or {}).get("cwd") or ""
                        if os.path.normcase(cwd) == want:
                            found.append(f)
                        break
        except (OSError, ValueError):
            continue
    return sorted(found, key=os.path.getmtime)


def profile(paths):
    steps, t0, t1 = [], None, None
    for p in paths:
        s, span = (codex_steps if "rollout-" in Path(p).name else claude_steps)(p)
        steps += s
        if span[0]:
            t0 = span[0] if t0 is None else min(t0, span[0])
            t1 = span[1] if t1 is None else max(t1, span[1])
    by = {}
    helpers = []
    for s in steps:
        cat = category(s["name"], s["text"])
        r = by.setdefault(cat, {"runs": [], "thinks": [], "steps": 0})
        r["runs"].append((s["at"], s["at"] + s["run"]))            # parallel steps share time: union, never a sum
        r["thinks"].append((s["at"] + s["run"], s["at"] + s["run"] + s["think"]))
        r["steps"] += 1
        s["category"] = cat
        helpers += helper_written(s["name"], s["text"])
    all_runs = _merge([(s["at"], s["at"] + s["run"]) for s in steps])
    for r in by.values():                              # "after it" never includes time a command was running
        r["run"] = _union(r.pop("runs"))
        r["think"] = sum(b - a for a, b in _minus(_merge(r.pop("thinks")), all_runs))
    slow = sorted(steps, key=lambda s: -(s["run"] + s["think"]))
    run_total = _union([(s["at"], s["at"] + s["run"]) for s in steps])
    span = (t1 or 0) - (t0 or 0)
    return {"logs": paths, "minutes": round(span / 60, 1), "steps": len(steps),
            "command_minutes": round(run_total / 60, 1),
            "other_minutes": round(max(0.0, span - run_total) / 60, 1),
            "by_category": {k: {"run_min": round(v["run"] / 60, 1), "think_min": round(v["think"] / 60, 1),
                                "steps": v["steps"]} for k, v in sorted(by.items(), key=lambda x: -(x[1]["run"] + x[1]["think"]))},
            "slowest": [{"minutes": round((s["run"] + s["think"]) / 60, 1), "category": s["category"],
                         "what": (s["name"] + ": " + s["text"])[:160]} for s in slow[:8]],
            "helpers_written": sorted(set(helpers))}


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        elif b > a:
            out.append([a, b])
    return out


def _minus(spans, cut):
    """Merged intervals ``spans`` with the merged intervals ``cut`` removed."""
    out = []
    for a, b in spans:
        pieces = [(a, b)]
        for c, d in cut:
            nxt = []
            for x, y in pieces:
                if d <= x or c >= y:
                    nxt.append((x, y))
                    continue
                if c > x:
                    nxt.append((x, c))
                if d < y:
                    nxt.append((d, y))
            pieces = nxt
        out += pieces
    return out


def _union(spans):
    """Seconds covered by the intervals, overlaps counted once (parallel or background commands)."""
    total, end = 0.0, None
    for a, b in sorted(spans):
        if end is None or a > end:
            total += b - a
            end = b
        elif b > end:
            total += b - end
            end = b
    return total


def speed_line(r):
    """One plain line for a job record."""
    if not r["steps"]:
        return "no worker log found"
    top = next(iter(r["by_category"].items()), None)
    worst = ("; slowest: %s %.1f min" % (top[0], top[1]["run_min"] + top[1]["think_min"])) if top else ""
    h = len(r["helpers_written"])
    return "%.0f min, %d steps (commands %.0f min, model and other %.0f min)%s%s" % (
        r["minutes"], r["steps"], r["command_minutes"], r["other_minutes"], worst,
        ("; wrote %d helper script%s by hand - Foundry tool candidate" % (h, "" if h == 1 else "s")) if h else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--worktree")
    g.add_argument("--session")
    ap.add_argument("--since", help="ISO time: ignore Codex logs older than this")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--line", action="store_true", help="print only the one-line summary")
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args(argv)
    if a.session:
        paths = [a.session]
    else:
        since = ts(a.since) if a.since else None
        paths = claude_logs(a.worktree) + codex_logs(a.worktree, since)
    r = profile(paths)
    r["line"] = speed_line(r)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    if a.line:
        print(r["line"])
        return 0
    if not paths:
        print("no session log found for that folder")
        return 1
    print(r["line"])
    print("%-18s %9s %9s %6s" % ("", "commands", "after it", "steps"))
    for k, v in r["by_category"].items():
        print("%-18s %8.1fm %8.1fm %6d" % (k, v["run_min"], v["think_min"], v["steps"]))
    print("slowest steps (command + thinking after it):")
    for s in r["slowest"][:a.top]:
        print("  %5.1f min  %-15s %s" % (s["minutes"], s["category"], s["what"]))
    for h in r["helpers_written"]:
        print("  helper written by hand: %s" % h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
