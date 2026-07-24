"""One-shot clean ship package builder (no personal runtime state)."""
from __future__ import annotations

import os
from pathlib import Path
import shutil

import distro
import share_governance as gov
import vendor_skills as vs

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "package-v1" / "clean-ship"

# Author machine layout for packaging only (never baked into shipped files).
os.environ.setdefault("ANCHOR_TRIO_DIR", r"C:\dev\trio")
os.environ.setdefault("ANCHOR_FOUNDRY_DIR", r"C:\dev\Skill Foundry")
# Gandalf lives under Foundry on this host (not a separate git root).
os.environ.setdefault("ANCHOR_GANDALF_DIR", r"C:\dev\Skill Foundry")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    b = OUT / "B-anchor-plus-skills"
    a = OUT / "A-skills-only"
    b.mkdir(parents=True)
    a.mkdir(parents=True)

    selected = distro.select_shippable()
    deny = (
        "tests/",
        ".anchor/",
        "planning/",
        "worktrees/",
        "general/",
        "bundle_staging/",
        "swarm/",
        "logs/",
    )
    staged: list[str] = []
    for rel in selected:
        r = rel.replace("\\", "/")
        if any(r.startswith(d) for d in deny):
            continue
        if "test_" in Path(r).name:
            continue
        staged.append(rel)

    for p in list(ROOT.glob("share_*.py")) + list(ROOT.glob("share_*.json")):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel not in staged:
            staged.append(rel)
    for base in ("share_governance_pack", "share_schemas"):
        d = ROOT / base
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(ROOT)).replace("\\", "/")
                if rel not in staged:
                    staged.append(rel)
    for name in (
        "onboard.py",
        "onboard.cmd",
        "onboard.ps1",
        "onboard_cli.py",
        "launch_anchor_dashboard.py",
        "USER-ONBOARD.md",
        "vendor_skills.py",
        "distro.py",
        "paths.py",
        "pillar_flags.py",
        "dist_manifest.txt",
        "gandalf.py",
        "anchor.py",
        "anchor_gui.py",
    ):
        if (ROOT / name).is_file() and name not in staged:
            staged.append(name)

    n = 0
    for rel in staged:
        src = ROOT / rel
        if not src.is_file():
            continue
        dst = b / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    print("product", n)

    # vendor_all writes under dest/vendor/bundled-skills
    # Override gandalf subdir: on this host it lives at skills/gandalf in Foundry.
    sources = []
    for name, env_var, subdir in vs.SKILL_SOURCES:
        if name == "gandalf":
            sources.append((name, "ANCHOR_FOUNDRY_DIR", "skills/gandalf"))
        else:
            sources.append((name, env_var, subdir))
    report = vs.vendor_all(b, sources=sources)
    # Scrub host paths in product surface too (not only git-archived skills).
    for p in b.rglob("*"):
        if p.is_file():
            try:
                vs._scrub_file(p)
            except Exception:
                pass
    print(
        "vendored",
        [x.get("name") if isinstance(x, dict) else x for x in report.get("vendored", [])],
    )
    print(
        "skipped",
        [
            (x.get("name"), x.get("reason"))
            for x in report.get("skipped", [])
            if isinstance(x, dict)
        ],
    )
    vendor_dest = b / "vendor" / "bundled-skills"
    print(
        "skills",
        sorted(
            p.name
            for p in vendor_dest.iterdir()
            if p.is_dir() or p.name == "SOURCES.md"
        ),
    )

    files = [
        (str(p.relative_to(b)).replace("\\", "/"), p)
        for p in b.rglob("*")
        if p.is_file()
    ]
    hits = distro.scan_paths(files)
    real = []
    for h in hits or []:
        s = str(h).lower()
        if "high-entropy" in s:
            continue
        # Planted detector fixtures / env-placeholder token patterns (not author data)
        if "c:\\users\\john\\secret" in s or "c:\\\\users\\\\john\\\\secret" in s:
            continue
        if "__anchor_t" in s:
            continue
        if "body.confirmtoken" in s or "confirm_token" in s:
            continue
        if "secret-blocked" in s:
            continue
        if "process.env" in s:
            continue
        if "token=" in s and "encodeuricomponent" in s:
            continue
        real.append(h)
    print("raw", len(hits or []), "real_concern", len(real))
    for h in real[:40]:
        print(" ", h)

    skills_src = vendor_dest
    shutil.copytree(skills_src, a / "skills")
    gp = a / "governance"
    gp.mkdir()
    for k, v in gov.build_pack_files().items():
        (gp / k).write_text(v, encoding="utf-8")
    shutil.copy2(ROOT / "share_sources_pin.json", a / "share_sources_pin.json")
    shutil.copy2(ROOT / "share_freeze_manifest.json", a / "share_freeze_manifest.json")
    (a / "README.md").write_text(
        "# Skills package v1.0\n\n"
        "Local edits stay local. Install skills + governance pack.\n",
        encoding="utf-8",
    )
    print(
        "A",
        sum(1 for _ in a.rglob("*") if _.is_file()),
        "B",
        sum(1 for _ in b.rglob("*") if _.is_file()),
    )


if __name__ == "__main__":
    main()
