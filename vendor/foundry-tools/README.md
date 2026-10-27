# Foundry tools

Small, fast, standard commands for chores agents keep doing by hand - seconds, not minutes. One per chore. Every
agent (steward, coder, skill) uses the tool instead of writing its own helper.

- `python C:/dev/foundry-tools/ft.py list` - the tools (from `INDEX.json`)
- `python C:/dev/foundry-tools/ft.py <tool> ...` - run one; every run is timed and logged to `.usage/` (not in git)
- `python C:/dev/foundry-tools/ft.py usage` - runs, failures and time per tool
- `python C:/dev/foundry-tools/ft.py propose <name> --why "..."` - suggest a new one (`PROPOSALS.md`)

`C:/dev/foundry-tools` is a junction to this folder (a path without a space). Anchor reads `INDEX.json` to list the
tools in every steward's and job's instructions, so a tool added here reaches them with no Anchor change.

Add a tool: a folder `<name>/` with `tool.py` (exit 0 on success, plain one-line results) and `TOOL.md` (when, the
command, typical time, what it needs), plus its row in `INDEX.json`. `tests/test_foundry_tools.py` checks they agree.
