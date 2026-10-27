# time-profile

**When:** a job or a session took longer than it should, or a steward wants to know whether a chore deserves a
Foundry tool. Never hand-analyse transcripts.

**Command:** `python C:/dev/foundry-tools/ft.py time-profile --worktree <folder the worker ran in> [--since ISO] [--line|--json]`
or `--session <transcript.jsonl>`.

**Time:** under a second for a Claude worker; a few seconds when it searches the ChatGPT (Codex) logs.

Prints: total minutes and steps, commands vs the model thinking, minutes by kind of work, the slowest steps, and the
helper scripts the worker wrote by hand (each one a Foundry tool candidate). `--line` prints only the one-line summary
Anchor puts on every finished job.
