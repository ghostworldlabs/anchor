"""Unit tests for the tidy-idy thin caller (no live job spawn)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import tidy_idy_runner as tidy


def test_resolve_entry_finds_worktree_or_env(tmp_path, monkeypatch):
    fake = tmp_path / "tidy-idy.mjs"
    fake.write_text("// entry\n", encoding="utf-8")
    monkeypatch.setenv(tidy.ENTRY_ENV, str(fake))
    assert tidy.resolve_entry() == fake.resolve()


def test_build_command_shape(tmp_path, monkeypatch):
    fake = tmp_path / "tidy-idy.mjs"
    fake.write_text("// entry\n", encoding="utf-8")
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv(tidy.ENTRY_ENV, str(fake))
    cmd = tidy.build_command(root, nonce_file=tmp_path / "nonce.json")
    assert cmd[0] == "node"
    assert cmd[1] == str(fake.resolve())
    assert cmd[2] == str(root.resolve())
    assert "--environment=anchor" in cmd
    assert "--json" in cmd
    assert any(a.startswith("--nonce-file=") for a in cmd)


def test_parse_panel_ready():
    log = (
        'noise\n'
        '{"event":"panel-ready","baseUrl":"http://127.0.0.1:9/","bootstrapFile":"C:/n.json"}\n'
        'more\n'
    )
    got = tidy.parse_panel_ready(log)
    assert got is not None
    assert got["event"] == "panel-ready"
    assert got["bootstrapFile"].endswith("n.json")


def test_read_bootstrap_file(tmp_path):
    p = tmp_path / "boot.json"
    p.write_text(json.dumps({"url": "http://127.0.0.1:9/?n=abc"}), encoding="utf-8")
    got = tidy.read_bootstrap_file(p)
    assert got["url"].startswith("http://127.0.0.1:9/")


def test_launch_refuses_missing_folder(tmp_path, monkeypatch):
    fake = tmp_path / "tidy-idy.mjs"
    fake.write_text("// entry\n", encoding="utf-8")
    monkeypatch.setenv(tidy.ENTRY_ENV, str(fake))
    out = tidy.launch_tidy_idy("proj", tmp_path / "nope")
    assert out["ok"] is False
    assert out["code"] == "no-folder"


def test_launch_refuses_missing_entry(tmp_path, monkeypatch):
    monkeypatch.delenv(tidy.ENTRY_ENV, raising=False)
    monkeypatch.setattr(tidy, "_DEFAULT_CANDIDATES", (tmp_path / "missing.mjs",))
    out = tidy.launch_tidy_idy("proj", tmp_path)
    assert out["ok"] is False
    assert out["code"] == "no-entry"


def test_route_table_registers_tidy_idy_run():
    import route_table
    keys = {(r.method, r.pattern) for r in route_table.ROUTES}
    assert ("POST", "/api/rnd/tidy_idy_run") in keys
