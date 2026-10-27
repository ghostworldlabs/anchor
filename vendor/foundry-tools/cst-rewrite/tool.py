"""cst-rewrite: Lossless Concrete Syntax Tree (LibCST/parso) codemod, Parable of the Oranges decomposition, and differential equivalence verifier.

  python C:/dev/foundry-tools/ft.py cst-rewrite --orange-split <repo>
  python C:/dev/foundry-tools/ft.py cst-rewrite --source <file.py> [--rename old:new]... [--drop fn_name]... [--output <dest.py>]
  python C:/dev/foundry-tools/ft.py cst-rewrite --verify-equivalence <old_repo> <new_repo> [--rtol 1e-7]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ANVIL_ENGINE = Path(__file__).resolve().parents[2] / "skills" / "anvil" / "scripts" / "anvil_engine.py"


def _load_anvil():
    import importlib.util
    spec = importlib.util.spec_from_file_location("anvil_engine", str(ANVIL_ENGINE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lossless CST code rewriting, Orange-Split decomposition, and differential equivalence checking.")
    ap.add_argument("--orange-split", metavar="REPO", help="Run Parable of the Oranges decomposition (Juice vs. Peel vs. Pith/Seeds)")
    ap.add_argument("--source", metavar="FILE", help="Source Python file for lossless LibCST/parso rewrite")
    ap.add_argument("--rename", action="append", default=[], help="Symbol rename old:new")
    ap.add_argument("--drop", action="append", default=[], help="Function name in Pith/Seeds (Null Space) to excise")
    ap.add_argument("--output", default="", help="Optional output file path")
    ap.add_argument("--verify-equivalence", nargs=2, metavar=("OLD_REPO", "NEW_REPO"), help="Verify differential behavioral equivalence")
    ap.add_argument("--rtol", type=float, default=1e-7, help="Relative tolerance for numeric equivalence")
    args = ap.parse_args(argv)

    anvil = _load_anvil()
    if args.orange_split:
        res = anvil.extract_orange_split(args.orange_split)
        print(json.dumps(res, indent=2))
        return 0
    if args.verify_equivalence:
        old_r, new_r = args.verify_equivalence
        res = anvil.verify_behavioral_equivalence(old_r, new_r, rtol=args.rtol)
        print(json.dumps(res, indent=2))
        return 0 if res.get("equivalent") else 1
    if args.source:
        rmap = dict(item.split(":", 1) for item in args.rename if ":" in item)
        res = anvil.cst_rewrite_module(args.source, rmap, args.drop, args.output or None)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ruff_syntax_and_undefined_gate_ok") else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
