# ledger

**When:** the Campaign steward is handed the ledger (Anchor does this after every 10 finished jobs, or 7 days), or
anyone asks how the code jobs are doing, whether the small tier is working, or which chores still want a tool.

**Command:** `python C:/dev/foundry-tools/ft.py ledger [--days 30] [--line] [--json]`

**Time:** well under a second. It reads only: Anchor's `speed.jsonl`, each job's own record, the Foundry usage
log and PROPOSALS.md. It writes nothing.

Prints, by job size (standard, small, small fell back): jobs, landed the first time, landed, median worker minutes,
median delivery minutes (a small job redone at standard counts as one delivery with both times) and escalations;
small jobs whose served model was not the tier asked for; the top reasons jobs did not land; chores still done by
hand; helper scripts written by hand in more than one job; Foundry tool runs; and tool proposals waiting for John.

The numbers are prompts to look, not proof. Tiers live in `tiers.json` and change only by John's word.
