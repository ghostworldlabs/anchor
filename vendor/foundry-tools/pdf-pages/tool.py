"""pdf-pages: fast PDF page count, dimensions, text extraction, and page PNG rendering.

  python C:/dev/foundry-tools/ft.py pdf-pages <file.pdf> [--pages 1-5] [--info] [--render-dir <folder>]
"""
import argparse
import json
import sys
from pathlib import Path


def parse_pages(spec: str, total: int) -> list[int]:
    if not spec:
        return list(range(1, min(total, 5) + 1))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            for p in range(max(1, int(a)), min(total, int(b)) + 1):
                if p not in out:
                    out.append(p)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= total and p not in out:
                out.append(p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inspect PDF pages without writing custom helper scripts.")
    ap.add_argument("pdf", help="Path to PDF file")
    ap.add_argument("--pages", default="1-5", help="1-based page range, e.g. 1-5 or 1,3,7 (default: 1-5)")
    ap.add_argument("--info", action="store_true", help="Print page count and dimensions only")
    ap.add_argument("--render-dir", help="Optional directory to render selected pages as PNGs")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args(argv)

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"pdf-pages: file not found: {pdf_path}", file=sys.stderr)
        return 2

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        total = len(doc)
        selected = parse_pages(args.pages, total)
        pages_out = []
        render_dir = Path(args.render_dir) if args.render_dir else None
        if render_dir:
            render_dir.mkdir(parents=True, exist_ok=True)
        for pno in selected:
            page = doc[pno - 1]
            rect = page.rect
            text = "" if args.info else page.get_text("text").strip()
            png_path = None
            if render_dir:
                pix = page.get_pixmap(dpi=150)
                dest = render_dir / f"page-{pno:03d}.png"
                pix.save(str(dest))
                png_path = str(dest)
            pages_out.append({
                "page": pno,
                "width_pt": round(rect.width, 1),
                "height_pt": round(rect.height, 1),
                "chars": len(text),
                "png": png_path,
                "excerpt": text[:600],
            })
        doc.close()
    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        total = len(reader.pages)
        selected = parse_pages(args.pages, total)
        pages_out = []
        for pno in selected:
            page = reader.pages[pno - 1]
            box = page.mediabox
            text = "" if args.info else (page.extract_text() or "").strip()
            pages_out.append({
                "page": pno,
                "width_pt": round(float(box.width), 1),
                "height_pt": round(float(box.height), 1),
                "chars": len(text),
                "png": None,
                "excerpt": text[:600],
            })

    if args.json:
        print(json.dumps({"file": str(pdf_path), "total_pages": total, "pages": pages_out}, indent=2))
        return 0

    print(f"{pdf_path.name}: {total} page(s)")
    for row in pages_out:
        extra = f" -> {row['png']}" if row.get("png") else ""
        print(f"  [p.{row['page']}/{total}] {row['width_pt']}x{row['height_pt']} pt · {row['chars']} chars{extra}")
        if not args.info and row["excerpt"]:
            first_line = " ".join(row["excerpt"].splitlines()[:2])[:140]
            print(f"    {first_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
