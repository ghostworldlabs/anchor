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


def test_route_table_registers_tidy_idy_run_and_status():
    import route_table
    keys = {(r.method, r.pattern) for r in route_table.ROUTES}
    assert ("POST", "/api/rnd/tidy_idy_run") in keys
    assert ("GET", "/api/rnd/tidy_idy_status") in keys


def test_migrated_handlers_include_tidy_idy_status():
    import anchor_gui
    assert "handle_tidy_idy_run" in anchor_gui._MIGRATED_HANDLERS
    assert "handle_tidy_idy_status" in anchor_gui._MIGRATED_HANDLERS


def test_status_for_folder_reads_status_json(tmp_path):
    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({
            "phase": "analyzing",
            "message": "Analyzing…",
            "statusUrl": "http://127.0.0.1:9/",
            "projectName": "demo",
        }),
        encoding="utf-8",
    )
    out = tidy.status_for_folder(tmp_path)
    assert out["ok"] is True
    assert out["phase"] == "analyzing"
    assert out["statusUrl"] == "http://127.0.0.1:9/"
    assert "Analyzing" in out["message"]


def test_launch_short_circuits_live_status(tmp_path, monkeypatch):
    """Second click: live status.json short-circuits without job_runner."""
    report = tmp_path / ".tidy-idy"
    report.mkdir()
    (report / "status.json").write_text(
        json.dumps({
            "phase": "scanning",
            "message": "Scanning…",
            "statusUrl": "http://127.0.0.1:60890/",
            "openUrl": "http://127.0.0.1:60890/?n=abc",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(tidy, "resolve_entry", lambda: tmp_path / "never.mjs")

    def _boom(*_a, **_k):
        raise AssertionError("job_runner must not be called when a run is live")

    monkeypatch.setattr(tidy.job_runner, "launch_guarded", _boom)
    out = tidy.launch_tidy_idy("proj", tmp_path)
    assert out["ok"] is True
    assert out["already_running"] is True
    assert out["status_url"] == "http://127.0.0.1:60890/"
