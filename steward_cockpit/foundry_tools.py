"""Foundry tools in every steward's and coder's standing rules (John 2026-10-12: "Why do we use commands that take
minutes, when there are options that take just seconds?").

The tools live in Skill Foundry (`foundry-tools/`, single source, like the skills); their INDEX.json is read each
time an engine's rules are built, so a tool added there reaches every steward and job with no Anchor change. A
missing or unreadable index falls back to the one tool Anchor itself carries (the reading copy)."""
import json
import os
from pathlib import Path

DEFAULT_INDEX = Path("C:/dev/Skill Foundry/foundry-tools/INDEX.json")
MAX_TOOLS = 8
_cache = {"key": None, "rows": None}

FALLBACK = (
    "A PDF or HTML reading copy is ONE command that takes seconds - `python C:/dev/Anchor/tools/reading_copy.py "
    "<document.md> [--html]` - never write or commission a renderer. "
)


def index_path():
    return Path(os.environ.get("ANCHOR_FOUNDRY_TOOLS_INDEX") or DEFAULT_INDEX)


def _clean(value, limit):
    text = " ".join(str(value or "").split())
    return text[:limit]


def tools():
    """The indexed tools as (name, purpose, command) rows; [] when the index cannot be read."""
    p = index_path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if _cache["key"] == key:
            return _cache["rows"]
        raw = json.loads(p.read_text(encoding="utf-8"))
        rows = []
        for t in raw.get("tools") or []:
            if not isinstance(t, dict):
                continue
            name, purpose, command = (_clean(t.get("name"), 40), _clean(t.get("purpose"), 160),
                                      _clean(t.get("command"), 220))
            if name and purpose and command:
                rows.append((name, purpose, command))
        rows = rows[:MAX_TOOLS]
        _cache.update(key=key, rows=rows)
        return rows
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def block(steward=True):
    """The FOUNDRY TOOLS paragraph for an engine's standing rules."""
    rows = tools()
    if not rows:
        return FALLBACK
    lines = "".join("\n  - %s: %s - `%s`" % r for r in rows)
    tail = ("When you or a job keep doing a chore by hand that no tool covers, or a job's speed line says it wrote "
            "helpers by hand, propose a tool: `python C:/dev/foundry-tools/ft.py propose <name> --why \"<what was done "
            "by hand, how long, where>\"` and tell John in one line. " if steward else
            "If a chore you needed has no tool, say so in one line of your final summary instead of building a "
            "general-purpose helper. ")
    return ("FOUNDRY TOOLS - one fast standard command per chore (seconds, not minutes). Use them; never write your "
            "own renderer, screenshot script, wait loop or time analysis:" + lines + "\n" + tail)
