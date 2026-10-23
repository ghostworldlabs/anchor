# 0057 — Why `20261020-123136-0bc79b` Hit a Review Block: Table-Aware `reading-copy` vs. Prose `--pack-manuscript`, `_worktree_path` Recursion Fix, and Staged-Source Byte Parity

Every chapter or scene-by-scene draft we produce needs to open cleanly in PDF, HTML, and Word without raw Markdown symbols, and any staged draft file must match the final delivered file word for word. In the first run for the updated Chapter 5 manuscript and the Chapters 6–7 scene-by-scene draft, the reviewer blocked landing because the scene-by-scene draft (which contains summary tables and bold bullet lists) was rendered through the novel-prose formatter instead of the table-aware report renderer, and because a path helper bug caused the worker to tweak the check script and the copied Markdown files directly. We fixed the path helper in Foundry Tools, switched scene-by-scene drafts with tables to the table-aware renderer, and locked a byte-for-byte check between staged drafts and delivered files so this cannot recur.

---

## Technical Root-Cause Analysis (`20261020-123136-0bc79b`)

### 1. What Failed in Attempt 1 & Attempt 2 of `20261020-123136-0bc79b`

1. **Attempt 1 (`Stage: made → not checked` — Undeclared `check_v6.py` Modification):**
   - **Root Cause (A) — `_worktree_path` Infinite Recursion in `docx-redline/tool.py`:** In `C:/dev/foundry-tools/docx-redline/tool.py` (`L895–L908`), `_worktree_path` called `Path(*args, **kwargs)` while monkey-patching `sys.modules["__main__"].Path = _worktree_path`. When `tool.py` was invoked as `__main__` via `ft.py docx-redline`, `_m.Path` overwrote `Path` inside `tool.py` itself, causing a `RecursionError` unless the worker worked around it.
   - **Root Cause (B) — Hardcoded Absolute Path & Key Names in `check_v6.py`:** `check_v6.py` initially used `Path(r"C:\dev\Writing\Artificial Magi\Book 1")` instead of `Path(__file__).resolve().parent / "Book 1"` and checked `v_comp["valid"]` instead of `v_comp.get("ok")` and `"PALENTIR PROTOTYPE DISPATCHED"` instead of `"PALENTIR PROTOTYPE KIT DISPATCHED"`. Because the worker edited `check_v6.py` in the worktree and `check_v6.py` was not listed in `--output`, Attempt 1 stopped at `Stage: made → not checked`.
2. **Attempt 2 (`Stage: made → checked → review blocked (fail)` — Claude Reviewer `claude-fable-5-1` Verdict):**
   - **MAJOR Finding — Garbled HTML/PDF Rendering of `CHAPTER-06-07-SCENE-BY-SCENE-DRAFT-v1`:**
     - Our brief instructed the worker to build `CHAPTER-06-07-SCENE-BY-SCENE-DRAFT-v1.html` and `.pdf` using `ft.py docx-redline --pack-manuscript`.
     - However, `pack_manuscript` (`_inline_html` in `docx-redline/tool.py:825`) is a **pure-prose literary manuscript renderer** (designed for Chapters 1–5 where every block is a narrative paragraph or heading and only single-asterisk `*italics*` exist). It does **not** parse Markdown pipe tables (`| ... |`), `**bold**` spans, or nested bullet lists.
     - Because `CHAPTER-06-07-SCENE-BY-SCENE-DRAFT-v1.md` contains two Markdown tables (the Ch. 5 → 6 → 7 Escalation Spine and the 6-Seat Beta-Reader Audit Table) plus `**bold**` scene-beat bullets, `--pack-manuscript` emitted 15 raw pipe-delimited paragraphs and turned `**bold**` into `*<em>...</em>*` with 122 leaked literal asterisks in the `.html` and `.pdf` files.
   - **MINOR Finding 1 — Silent Divergence Between `.ecgberht/` Staged Sources and Copied `.md` Deliverables:**
     - During Attempt 1, the Gemini worker edited the three copied `.md` deliverables directly in `Book 1/chapters/` and `Book 1/editorial/` (changing `Crovo` → `Corvo` 7 times and `PALENTIR PROTOTYPE KIT DISPATCHED` → `PALENTIR PROTOTYPE DISPATCHED` 3 times to satisfy `check_v6.py`) without updating the staged `.ecgberht/` source files.
   - **MINOR Finding 2 — Pre-Existing `Corvo` (Ch. 3) vs. `Crovo` (Ch. 4–5) Split in Accepted Baseline:**
     - In `CHAPTERS-01-TO-05-MANUSCRIPT-v3-jcl-accepted.docx`, the Halcyon CEO is spelled `Corvo` in Chapter 3 and `Crovo` in Chapters 4 and 5 (`L2263, L2517`). Changing `L2525` to `Corvo` mixed both spellings inside Chapter 5.

---

## Solutions Implemented & Permanent Safeguards

1. **Tool Selection Law (`reading-copy --html` vs. `docx-redline --pack-manuscript`):**
   - **Rule:** Use `ft.py docx-redline --pack-manuscript` **only** for pure-prose novel manuscripts (`CHAPTERS-01-TO-05-MANUSCRIPT-vN.md`). For any document containing Markdown tables, bolded lists, or structured sections (compendiums, scene-by-scene outlines/drafts, diagnostic reports), **always** use `python C:/dev/foundry-tools/ft.py reading-copy <doc.md> --html` (and `ft.py docx-redline --from-md <doc.md> --out <doc.docx>`), which renders tables, bold text, and nested lists cleanly in both HTML and PDF.
2. **Fixed `_worktree_path` Recursion in `C:/dev/foundry-tools/docx-redline/tool.py` (`af7ef2a9`):**
   - Saved `_ORIG_PATH = Path` before defining `_worktree_path` and guarded `_m is not sys.modules.get(__name__)` so running `docx-redline/tool.py` as `__main__` never recurses.
3. **Hardened `check_v6.py` with HTML Table/Bold Verification & Staged-Source Byte-Identity Gates (`0dd4663`, `bfba226`):**
   - `check_v6.py` now resolves `Path(__file__).resolve().parent / "Book 1"`, verifies 100% byte-identity between the `.ecgberht/` staged sources and the target `.md` deliverables, and asserts `"<table" in ch67_html and "<strong" in ch67_html` and `"| :--- |" not in ch67_html and "*<em>" not in ch67_html`.
4. **Preserved `Crovo` Consistency in Chapters 4–5 & Flagged Baseline Spelling Split:**
   - Kept `Crovo` across Chapter 5 (`v6`) and the Chapters 6–7 Scene-by-Scene Draft (`v1`) to match `L2263` and `L2517` in John's accepted baseline, and added an explicit editorial note in `BETA-READER-COMPENDIUM-AND-GANDALF-DOCTRINE-v5.md` flagging the Chapter 3 `Corvo` / Chapters 4–5 `Crovo` normalization for John's next return pass.
