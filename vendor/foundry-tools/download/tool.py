"""download: package or copy an artifact/HTML program with a human filename and verify byte integrity.

  python C:/dev/foundry-tools/ft.py download <src> --as "<Human Name.ext>" [--out-dir <folder>]
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copy and verify a deliverable under a clean human filename.")
    ap.add_argument("src", help="Source file path")
    ap.add_argument("--as", dest="human_name", required=True, help="Human-friendly filename (e.g. 'Supplement 1 - Demand Simulator.html')")
    ap.add_argument("--out-dir", help="Destination directory (defaults to source file's directory)")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args(argv)

    src = Path(args.src).resolve()
    if not src.is_file():
        print(f"download: source file does not exist: {src}", file=sys.stderr)
        return 2

    clean_name = Path(args.human_name).name.strip()
    if not clean_name or clean_name in (".", ".."):
        print("download: invalid --as filename", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir).resolve() if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / clean_name
    if src != dst:
        shutil.copy2(src, dst)

    src_hash = sha256_of(src)
    dst_hash = sha256_of(dst)
    ok = src_hash == dst_hash and dst.stat().st_size == src.stat().st_size
    result = {
        "ok": ok,
        "src": str(src),
        "dst": str(dst),
        "filename": clean_name,
        "bytes": dst.stat().st_size,
        "sha256": dst_hash,
    }
    if args.json:
        print(json.dumps(result))
    else:
        print(f"{'OK' if ok else 'MISMATCH'}: {clean_name} ({result['bytes']:,} bytes, sha256={dst_hash[:12]}…) -> {dst}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
