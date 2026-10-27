# pptx-pdf-verify

Convert a PowerPoint (`.pptx`) deck to a same-stem `.pdf` reading copy via LibreOffice `soffice.exe` (with an isolated temporary profile so concurrent conversions never collide) and verify:
1. Valid `%PDF-` header bytes.
2. Exact slide-count to PDF page-count parity (plus optional `--expect-slides N`).
3. Selectable text on every PDF page via PyMuPDF (`fitz`).
4. Zero shape bounding-box overflow beyond the slide dimensions (`python-pptx`).

## Usage

```bash
python C:/dev/foundry-tools/ft.py pptx-pdf-verify "BA 815/Fall 2026/AI Supplement 4 - Tuscan Recipe Draft 4.pptx" --expect-slides 18
python C:/dev/foundry-tools/ft.py pptx-pdf-verify "deck.pptx" --no-convert --json
```
