"""The fence's PreToolUse guard (W1a, ChatGPT review round 1 of 2026-10-08): a Claude Code hook that runs BEFORE a tool,
so a refused call never happens.

  - A fenced steward's shell: the allow list admits only the two hand-off tools and read-only git, by prefix - and a
    prefix admits ``git diff --output=C:/dev/Anchor/static/page.js`` or a redirection. This guard admits the command
    only when it has no shell operator, no redirection, and no git option that writes a file or runs a program.
  - A code job's coder (ANCHOR_FENCE_ROOT set): its file tools write only inside its own worktree.

Protocol: the tool call arrives as JSON on stdin; exit 0 allows it, exit 2 refuses it with the reason on stderr (the
model reads it). Stdlib only. Never crashes open: any doubt refuses.
"""
import json
import os
import re
import sys

SHELL_TOOLS = {"Bash", "PowerShell"}
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
OPERATORS = re.compile(r"[<>|;&`\n\r]|\$\(|\$\{")
GIT_ARG = re.compile(r"^(?:--output(?:=.*)?|-o.*|--output-directory.*|--ext-diff|--textconv|--exec(?:=.*)?|"
                     r"--upload-pack.*|--receive-pack.*|-c|--config-env.*)$")
ALLOWED = (
    re.compile(r"^python(?:\.exe)?\s+C:/dev/Anchor/tools/steward_(?:code_job|skill)\.py(?:\s|$)", re.I),
    re.compile(r"^git\s+(?:status|log|diff|show)(?:\s|$)"),
)


def unquoted(cmd):
    """The command as the shell acts on it: single-quoted text is literal (dropped); in double quotes only command
    substitution stays live (kept as a marker); an unclosed quote is refused by the caller (returns None)."""
    out, i, n = [], 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "\\" and i + 1 < n:
            out.append("_"); i += 2; continue
        if c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                return None
            out.append("_"); i = j + 1; continue
        if c == '"':
            j, live = i + 1, False
            while j < n and cmd[j] != '"':
                if cmd[j] == "\\" and j + 1 < n:
                    j += 2; continue
                if cmd[j] == "`" or cmd.startswith("$(", j) or cmd.startswith("${", j):
                    live = True
                j += 1
            if j >= n:
                return None
            out.append("$(" if live else "_"); i = j + 1; continue
        out.append(c); i += 1
    return "".join(out)


def refuse(why):
    log = os.environ.get("ANCHOR_FENCE_LOG")
    if log:     # the proof's witness that the hook itself refused (not the model declining)
        try:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(why + "\n")
        except OSError:
            pass
    sys.stderr.write("REFUSED by the fence: %s\n" % why)
    sys.exit(2)


def inside(path, root):
    try:
        p = os.path.normcase(os.path.realpath(path))
        r = os.path.normcase(os.path.realpath(root))
        return p == r or p.startswith(r.rstrip("\\/") + os.sep)
    except Exception:
        return False


def main():
    try:
        call = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        refuse("the tool call could not be read")
    tool = str(call.get("tool_name") or "")
    inp = call.get("tool_input") or {}
    root = os.environ.get("ANCHOR_FENCE_ROOT", "")
    if tool in FILE_TOOLS and root:
        cwd = str(call.get("cwd") or os.getcwd())
        raw = str(inp.get("file_path") or inp.get("notebook_path") or "")
        path = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
        if not raw or not inside(path, root):
            refuse("a code job writes only inside its own worktree (%s); %s is outside" % (root, raw or "(no path)"))
        sys.exit(0)
    if tool in SHELL_TOOLS and os.environ.get("ANCHOR_FENCE_SHELL") == "1":
        cmd = str(inp.get("command") or "").strip()
        bare = unquoted(cmd)
        if bare is None:
            refuse("an unclosed quote")
        if OPERATORS.search(bare):
            refuse("no shell operators or redirection in a fenced shell - run one hand-off tool or one read-only git command")
        if not any(a.search(cmd) for a in ALLOWED):
            refuse("only the two hand-off tools and read-only git run here")
        if cmd.startswith("git"):
            try:
                import shlex
                args = shlex.split(cmd, posix=True)[2:]     # a quoted option is still an option
            except ValueError:
                refuse("the git command could not be read")
            if any(GIT_ARG.match(a) for a in args):
                refuse("that git option writes a file or runs a program")
    sys.exit(0)


if __name__ == "__main__":
    main()
