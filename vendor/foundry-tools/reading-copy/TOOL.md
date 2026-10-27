# reading-copy

**When:** a Markdown deliverable needs its PDF (or HTML) reading copy. Never write your own renderer.

**Command:** `python C:/dev/foundry-tools/ft.py reading-copy <doc.md> [--html [PATH]] [--out PDF] [--no-pdf]`

**Time:** about 1-2 seconds. **Needs:** Anchor installed (its page renderer) and Microsoft Edge (already on PUTER).

Prints the written path(s); exit 1 with the reason when it could not. Figures (`![alt](file.png)`) and math are kept.
A code job also makes a missing declared `.pdf`/`.html` from the same-named `.md` by itself.
