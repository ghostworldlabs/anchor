"""Steward persona selection (2026-07-29) — pure unit tests.

One steward engine, selectable livery: ecgberht / aladdin / jarvis. Covers the
settings-store field (default, roundtrip, invalid rejection, corrupt fallback),
the persona catalog's icon files existing in vendor/brand (they ship with the
bundle), and the home-header selector rendering all three options with the
active one selected. No network, no live CLI, no model call.
"""
import importlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    import paths
    importlib.reload(paths)
    import anchor_settings
    importlib.reload(anchor_settings)
    return anchor_settings


def test_steward_default_is_ecgberht(settings_env):
    s = settings_env
    out = s.load_settings()
    assert out["steward_type"] == "ecgberht"
    prof = s.steward_profile(out)
    assert prof["key"] == "ecgberht"
    assert prof["seal"] == "ecgberht-project-seal.jpg"


def test_steward_roundtrip_and_profile(settings_env):
    s = settings_env
    for key in ("aladdin", "jarvis", "ecgberht"):
        s.save_settings(steward_type=key)
        out = s.load_settings()
        assert out["steward_type"] == key
        prof = s.steward_profile()
        assert prof["key"] == key
        assert prof["label"] == s.STEWARDS[key]["label"]
        assert prof["high_seat"] == s.STEWARDS[key]["high_seat"]
        assert prof["seal"] == s.STEWARDS[key]["seal"]


def test_steward_invalid_rejected(settings_env):
    s = settings_env
    with pytest.raises(ValueError):
        s.save_settings(steward_type="expert")  # the spelling-law classic
    with pytest.raises(ValueError):
        s.save_settings(steward_type="")
    # Store untouched by the failed writes.
    assert s.load_settings()["steward_type"] == "ecgberht"


def test_steward_corrupt_value_falls_back(settings_env):
    s = settings_env
    p = s.settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"steward_type": "not-a-steward"}', encoding="utf-8")
    assert s.load_settings()["steward_type"] == "ecgberht"
    assert s.steward_profile({"steward_type": "bogus"})["key"] == "ecgberht"


def test_steward_icon_files_ship():
    """Every catalog icon exists in vendor/brand (they ride the bundle)."""
    import anchor_settings as s
    for key, meta in s.STEWARDS.items():
        for kind in ("high_seat", "seal"):
            f = REPO_ROOT / "vendor" / "brand" / meta[kind]
            assert f.is_file(), "%s %s icon missing: %s" % (key, kind, f)


def test_steward_control_renders_all_options(settings_env, monkeypatch):
    """The home-header selector lists all three personas, active selected."""
    s = settings_env
    s.save_settings(steward_type="jarvis")
    import anchor_gui
    # anchor_gui holds its own reference to the module; point it at the
    # reloaded, tmp-isolated instance for this render.
    monkeypatch.setattr(anchor_gui, "_aset", s)
    html = anchor_gui.render_steward_control()
    for key in ("ecgberht", "aladdin", "jarvis"):
        assert "value='%s'" % key in html
    assert "value='jarvis'" in html and "selected>Jarvis" in html.replace(
        "' selected", "' selected")
    # active option is marked selected
    assert "'jarvis' " in html or "value='jarvis' " in html
    jarvis_opt = html.split("value='jarvis'", 1)[1].split(">", 1)[0]
    assert "selected" in jarvis_opt
    # the seal thumbnail of the active persona rides along
    assert s.STEWARDS["jarvis"]["seal"] in html


def test_steward_catalog_naming_complete():
    """Persona-consistent naming (2026-07-30): every persona names BOTH
    surfaces itself — portfolio (high_seat_name) + project mark (seal_name)
    + the Projects-tile hint. No mixed livery, no missing field."""
    import anchor_settings as s
    for key, meta in s.STEWARDS.items():
        for field in ("label", "desc", "high_seat", "seal",
                      "high_seat_name", "seal_name", "projects_hint"):
            assert meta.get(field), "%s missing %s" % (key, field)
    # The names John locked: the persona speaks its own tongue.
    assert s.STEWARDS["aladdin"]["high_seat_name"] == "Cave of Wonders"
    assert s.STEWARDS["jarvis"]["high_seat_name"] == "Tip of the Hat"
    assert s.STEWARDS["ecgberht"]["high_seat_name"] == "High Seat"


def test_steward_ui_total_and_row_icon_follows_persona(settings_env,
                                                       monkeypatch):
    """_steward_ui is TOTAL (every field, any persona) and the project-row
    seal icon src follows the active persona."""
    s = settings_env
    import anchor_gui
    monkeypatch.setattr(anchor_gui, "_aset", s)
    for key in ("ecgberht", "aladdin", "jarvis"):
        s.save_settings(steward_type=key)
        ui = anchor_gui._steward_ui()
        for field in ("label", "high_seat", "seal", "high_seat_name",
                      "seal_name", "projects_hint"):
            assert ui.get(field), "%s missing in ui for %s" % (field, key)
        assert ui["key"] == key
        src = anchor_gui._steward_seal_icon_src()
        assert s.STEWARDS[key]["seal"] in src
        assert src.startswith("/vendor/brand/")


def test_steward_ui_falls_back_complete(monkeypatch):
    """A settings-layer explosion still yields a COMPLETE Ecgberht profile."""
    import anchor_gui

    class _Boom:
        def steward_profile(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(anchor_gui, "_aset", _Boom())
    ui = anchor_gui._steward_ui()
    assert ui["key"] == "ecgberht"
    for field in ("high_seat", "seal", "high_seat_name", "seal_name",
                  "projects_hint"):
        assert ui.get(field)


def test_project_window_livery_slots_and_boot():
    """Project-level dashboards follow the persona (2026-07-30): the window
    shell's seal button + boot global are SLOTTED (no hardcoded Ecgberht
    seal), and both static JS assets resolve display livery through
    window.ANCHOR_STEWARD with an Ecgberht fallback."""
    shell = (REPO_ROOT / "static" / "project-window.html").read_text(
        encoding="utf-8")
    for slot in ("@@steward_label@@", "@@steward_seal_src@@",
                 "@@steward_seal_name@@", "@@steward_boot@@"):
        assert slot in shell, slot
    assert "src='/vendor/brand/ecgberht-project-seal.jpg'" not in shell

    for asset in ("project-window.js", "high-seat.js"):
        js = (REPO_ROOT / "static" / asset).read_text(encoding="utf-8")
        assert "window.ANCHOR_STEWARD" in js, asset
        # the fallback literal survives ONLY inside the helper functions
        assert "ico.src = '/vendor/brand/ecgberht-project-seal.jpg';" not in js, asset
