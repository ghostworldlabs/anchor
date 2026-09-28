"""R11 of the High Seat (John, 2026-09-28): a new project without the old dashboard — say it to the steward and
confirm the card here, or ONE button that opens the old dashboard's folder-creation dialog alone in a small window;
either way the project is placed in a dashboard folder of his choosing, not only in Ungrouped."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anchor_gui  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import rnd_registry  # noqa: E402


class _Handler:
    def __init__(self):
        self.sent = []

    def _send_json(self, payload, code=200):
        self.sent.append((payload, code))


def test_the_dialogs_folder_choices_are_the_dashboards_folders_then_ungrouped_then_new(monkeypatch):
    monkeypatch.setattr(rnd_registry, "group_by_group", lambda **k: {"Teaching": [1], "Writing <b>": [2], "Ungrouped": [3]})
    html = anchor_gui._np_group_options()
    assert html.index('<option value="Teaching">Teaching</option>') < html.index('<option value="Writing &lt;b&gt;">Writing &lt;b&gt;</option>') < html.index('<option value="">Ungrouped</option>') < html.index('value="__new__"')
    monkeypatch.setattr(rnd_registry, "group_by_group", lambda **k: (_ for _ in ()).throw(OSError("registry")))
    assert anchor_gui._np_group_options().startswith('<option value="">Ungrouped</option>'), "a registry that cannot be read still offers Ungrouped and a new folder"


def test_a_new_project_is_placed_in_the_folder_he_chose(monkeypatch):
    placed = []
    monkeypatch.setattr(anchor_gui, "create_new_folder_project", lambda name, parent, priority=2, git_init=False: {"entry": {"id": "p1", "name": name, "group": ""}, "folder_created": True})
    monkeypatch.setattr(anchor_gui, "select_existing_project", lambda name, folder, priority=2: {"entry": {"id": "p2", "name": name, "group": ""}, "folder_created": False})
    monkeypatch.setattr(rnd_registry, "set_group", lambda pid, group: placed.append((pid, group)) or {"id": pid, "group": group, "name": "x"})
    h = _Handler()
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "new_folder", "name": "Bread 2", "parent_path": "C:/dev", "group": "Nutrition"})
    payload, code = h.sent[-1]
    assert code == 200 and payload["ok"] and payload["entry"]["group"] == "Nutrition" and payload["group"] == "Nutrition"
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "existing", "name": "Old", "folder_path": "C:/dev/old", "group": "Teaching"})
    assert h.sent[-1][0]["entry"]["group"] == "Teaching"
    # the composer's confirm card: mode auto, an existing folder
    monkeypatch.setattr(anchor_gui.Path, "exists", lambda self: True)
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "auto", "name": "Spoken", "folder_path": "C:/dev/spoken", "group": "Writing"})
    assert h.sent[-1][0]["entry"]["group"] == "Writing" and h.sent[-1][0]["path_existed"] is True
    assert placed == [("p1", "Nutrition"), ("p2", "Teaching"), ("p2", "Writing")]
    # no folder chosen: nothing placed, Ungrouped as before
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "existing", "name": "Plain", "folder_path": "C:/dev/plain"})
    assert "group" not in h.sent[-1][0] and len(placed) == 3
    # a placement that fails never loses the creation
    monkeypatch.setattr(rnd_registry, "set_group", lambda pid, group: (_ for _ in ()).throw(OSError("locked")))
    anchor_gui.handle_new_project(h, "/api/rnd/new_project", {"mode": "existing", "name": "Late", "folder_path": "C:/dev/late", "group": "Teaching"})
    payload, code = h.sent[-1]
    assert code == 200 and payload["ok"] and "could not be placed" in payload["group_error"]


def test_the_old_dashboards_dialog_carries_the_folder_and_can_stand_alone_in_a_small_window():
    src = inspect.getsource(anchor_gui.generate_html)
    assert '<select id="npGroup" onchange="npGroupChanged()">{np_group_options}</select>' in src
    assert "group: npGroupValue()" in src and "_npCreateInPopup(body)" in src
    assert "body.only-new-project > *:not(#newProjectModal)" in src
    assert "q.get('only') === '1' || !!window.opener" in src and "postMessage({{ anchor: 'project-created'" in src
    assert "window.close()" in src


def test_the_projects_tile_offers_one_control_and_no_trip_to_the_old_dashboard():
    ctx = {"groups": {"Teaching": [1, 2], "Writing": [3], "Ungrouped": [4]}, "quiet_n": 0, "projects_html": "<ul></ul>"}
    html = hsp._projects_tile(ctx)
    assert 'id="apNew" role="button"' in html and "New project" in html
    assert 'id="apCreate"' not in html and 'href="/dashboard"' not in html
    assert '<select id="apGroups" hidden><option value="Teaching">Teaching</option><option value="Writing">Writing</option><option value="">Ungrouped</option></select>' in html
    assert "start a new project called" in html


def test_lint_the_page_opens_the_dialog_alone_and_confirms_a_spoken_project_here():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(root, "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "window.open('/dashboard?new=1&only=1', 'anchor-new-project'" in js
    assert "ev.data.anchor !== 'project-created'" in js and "location.reload()" in js
    assert "function projectCard(pc, sayText)" in js and "mode: 'auto', name: name, folder_path: folder, group: sel.value || ''" in js
    assert "confirm it on the old dashboard" not in js
    css = open(os.path.join(root, "static", "high-seat-page.css"), encoding="utf-8").read()
    assert ".pc-card{" in css and ".ptile-h .tog.np{" in css
