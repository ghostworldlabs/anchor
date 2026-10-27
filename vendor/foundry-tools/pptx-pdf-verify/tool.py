"""pptx-pdf-verify: Convert a PowerPoint (.pptx) deck to a same-stem .pdf and verify slide count, selectable text, and bounds.

  python C:/dev/foundry-tools/ft.py pptx-pdf-verify <deck.pptx> [--expect-slides N] [--no-convert] [--json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for c in SOFFICE_CANDIDATES:
        if Path(c).is_file():
            return c
    return None


def inspect_pptx(pptx_path: Path) -> dict:
    try:
        from pptx import Presentation
        prs = Presentation(str(pptx_path))
        w_in = round(prs.slide_width.inches, 2) if prs.slide_width else None
        h_in = round(prs.slide_height.inches, 2) if prs.slide_height else None
        slides = []
        overflow_shapes = []
        for idx, slide in enumerate(prs.slides, 1):
            texts = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                    texts.append(shape.text_frame.text.strip())
                try:
                    if prs.slide_width and prs.slide_height and shape.left is not None and shape.width is not None:
                        right_in = (shape.left + shape.width) / 914400.0
                        bottom_in = (shape.top + shape.height) / 914400.0
                        if right_in > w_in + 0.25 or bottom_in > h_in + 0.25:
                            overflow_shapes.append({"slide": idx, "name": shape.name, "right_in": round(right_in, 2), "bottom_in": round(bottom_in, 2)})
                except Exception:
                    pass
            slides.append({"slide": idx, "chars": sum(len(t) for t in texts), "title": (texts[0].splitlines()[0][:80] if texts else "")})
        return {"slide_count": len(slides), "width_in": w_in, "height_in": h_in, "slides": slides, "overflow_shapes": overflow_shapes}
    except Exception as exc:
        return {"slide_count": None, "error": str(exc), "slides": [], "overflow_shapes": []}


def convert_to_pdf(pptx_path: Path, pdf_path: Path) -> tuple[bool, str]:
    soffice = find_soffice()
    if not soffice:
        return False, "LibreOffice soffice.exe not found"
    with tempfile.TemporaryDirectory(prefix="ft-soffice-") as profile_dir:
        profile_uri = Path(profile_dir).as_uri()
        cmd = [
            soffice,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(pdf_path.parent),
            str(pptx_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not pdf_path.is_file():
            return False, (r.stderr or r.stdout or f"soffice exit {r.returncode}").strip()[:300]
    return True, "converted"


def inspect_pdf(pdf_path: Path) -> dict:
    if not pdf_path.is_file():
        return {"exists": False, "valid_pdf_header": False, "page_count": 0, "empty_text_pages": []}
    raw_head = pdf_path.read_bytes()[:8]
    valid_header = raw_head.startswith(b"%PDF-")
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        empty_pages = []
        total_chars = 0
        for idx in range(page_count):
            txt = doc[idx].get_text("text").strip()
            total_chars += len(txt)
            if not txt:
                empty_pages.append(idx + 1)
        doc.close()
        return {"exists": True, "valid_pdf_header": valid_header, "page_count": page_count, "total_chars": total_chars, "empty_text_pages": empty_pages}
    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        empty_pages = []
        total_chars = 0
        for idx, p in enumerate(reader.pages):
            txt = (p.extract_text() or "").strip()
            total_chars += len(txt)
            if not txt:
                empty_pages.append(idx + 1)
        return {"exists": True, "valid_pdf_header": valid_header, "page_count": page_count, "total_chars": total_chars, "empty_text_pages": empty_pages}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert .pptx to .pdf and verify slide/page parity, selectable text, and bounds.")
    ap.add_argument("pptx", help="Path to .pptx file")
    ap.add_argument("--pdf", help="Optional output .pdf path (defaults to same stem beside .pptx)")
    ap.add_argument("--expect-slides", type=int, default=0, help="Expected slide/page count")
    ap.add_argument("--no-convert", action="store_true", help="Verify existing .pptx and .pdf without running soffice")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    pptx_path = Path(args.pptx).resolve()
    if not pptx_path.is_file():
        print(f"pptx-pdf-verify: file not found: {pptx_path}", file=sys.stderr)
        return 2
    pdf_path = Path(args.pdf).resolve() if args.pdf else pptx_path.with_suffix(".pdf")

    conv_ok, conv_note = (True, "skipped (--no-convert)") if args.no_convert else convert_to_pdf(pptx_path, pdf_path)
    pptx_info = inspect_pptx(pptx_path)
    pdf_info = inspect_pdf(pdf_path)

    errors = []
    if not conv_ok and not pdf_info.get("exists"):
        errors.append(f"PDF conversion failed: {conv_note}")
    if not pdf_info.get("valid_pdf_header"):
        errors.append("PDF file is missing %PDF- header")
    if pptx_info.get("slide_count") and pdf_info.get("page_count") and pptx_info["slide_count"] != pdf_info["page_count"]:
        errors.append(f"Slide/page mismatch: PPTX has {pptx_info['slide_count']} slides, PDF has {pdf_info['page_count']} pages")
    if args.expect_slides and pptx_info.get("slide_count") != args.expect_slides:
        errors.append(f"Expected {args.expect_slides} slides, found {pptx_info.get('slide_count')}")
    if pdf_info.get("empty_text_pages"):
        errors.append(f"PDF pages with no selectable text: {pdf_info['empty_text_pages']}")
    if pptx_info.get("overflow_shapes"):
        errors.append(f"PPTX shapes overflowing slide bounds: {len(pptx_info['overflow_shapes'])}")

    report = {
        "ok": len(errors) == 0,
        "pptx": str(pptx_path),
        "pdf": str(pdf_path),
        "conversion": conv_note,
        "pptx_info": pptx_info,
        "pdf_info": pdf_info,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"[{status}] {pptx_path.name} -> {pdf_path.name} ({pptx_info.get('slide_count')} slides, {pdf_info.get('page_count')} PDF pages, {pdf_info.get('total_chars', 0)} selectable chars)")
        for err in errors:
            print(f"  - ERROR: {err}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
