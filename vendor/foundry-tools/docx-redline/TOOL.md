# `docx-redline` — Word (`.docx`) Inspector, Clause Diff & OpenXML Track Changes Generator

Eliminates ad-hoc Python scripts for inspecting `.docx` styles/tabs/paragraphs, comparing two versions of a legal or business agreement, or generating native Microsoft Word Track Changes (`<w:ins>` / `<w:del>`) while preserving 100% of original `<w:pPr>` and `<w:rPr>` formatting.

## Usage
```powershell
python C:/dev/foundry-tools/ft.py docx-redline --inspect <file.docx>
python C:/dev/foundry-tools/ft.py docx-redline --diff <baseline.docx> <revised.docx>
python C:/dev/foundry-tools/ft.py docx-redline --redline <baseline.docx> <revised.docx> --out <tracked.docx> [--author "John Calder Liechty"]
```
