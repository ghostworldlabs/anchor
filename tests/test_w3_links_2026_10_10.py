"""W3 of the night of 2026-10-10: links in a steward's reply open the right thing, or say exactly why not.
Acceptance: the registered PDF opens from the dialogue (and the card), not the HTML beside it. Each failure word is
earned: "not found" only for a confirmed missing file; "changed since it was registered" for other bytes; "unavailable
now" for anything outside, private or unknown. External links are exempt; an absolute Anchor URL opens relatively."""
import hashlib
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import link_check  # noqa: E402

PID = "p0001"


def _effort(tmp_path, monkeypatch):
    proj = tmp_path / "Proj"
    eff = proj / "Effort"
    (eff / "out").mkdir(parents=True)
    (eff / "ECGBERHT.md").write_text("# x\n", encoding="utf-8")
    (eff / "out" / "report.pdf").write_bytes(b"%PDF-1.4 report")
    (eff / "out" / "report.html").write_text("<p>report</p>", encoding="utf-8")
    (eff / "notes.md").write_text("# notes\n", encoding="utf-8")
    (eff / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n"
        "| Report (PDF) | `out/report.pdf` | 2026-10-10 | 1 |\n"
        "| Report (HTML) | `out/report.html` | 2026-10-10 | 1 |\n", encoding="utf-8")
    monkeypatch.setattr(link_check, "_project_folder", lambda pid: str(proj) if pid == PID else None)
    import deliverables_register as dr
    monkeypatch.setattr(dr, "project_and_rel", lambda cdir: (PID, "Effort"))
    return proj, eff


def _file_url(rel, **extra):
    q = "pid=%s&dir=Effort&path=%s" % (PID, quote(rel, safe=""))
    for k, v in extra.items():
        q += "&%s=%s" % (k, v)
    return "/api/steward/deliverable-file?" + q


def test_the_registered_pdf_wins_over_the_html_beside_it(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = "Read [the report](%s) when you can." % _file_url("out/report.html")
    out, report = link_check.check_reply(text, str(eff))
    assert "report.pdf" in out and "report.html" not in out
    assert report and report[0]["verdict"] == "the registered PDF"
    assert "now opens the registered copy" in link_check.report_line(report)


def test_an_absolute_anchor_url_opens_relatively_and_external_links_are_exempt(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = ("[notes](http://localhost:8777/artifact/%s/Effort/notes.md) and [paper](https://arxiv.org/abs/1234.5678) "
            "and https://example.com/x" % PID)
    out, report = link_check.check_reply(text, str(eff))
    assert "](/artifact/%s/Effort/notes.md)" % PID in out
    assert "https://arxiv.org/abs/1234.5678" in out and "https://example.com/x" in out
    assert report == []


def test_a_missing_file_is_not_found_and_an_outside_one_is_unavailable(tmp_path, monkeypatch):
    proj, eff = _effort(tmp_path, monkeypatch)
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    text = "[gone](/artifact/%s?path=Effort/gone.md) and [escape](/artifact/%s?path=../secret.txt)" % (PID, PID)
    out, report = link_check.check_reply(text, str(eff))
    verdicts = {r["label"]: r["verdict"] for r in report}
    assert verdicts == {"gone": "not found", "escape": "unavailable now"}
    assert out == text, "an uncorrectable link is left as written - never swapped for a guess"
    line = link_check.report_line(report)
    assert "`gone`: not found" in line and "`escape`: unavailable now" in line


def test_other_bytes_than_registered_say_changed_and_an_unknown_project_is_unavailable(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    stale = hashlib.sha256(b"older bytes").hexdigest()
    text = "[old notes](%s) [lost](/artifact/nope?path=a.md)" % _file_url("notes.md", hash=stale)
    _out, report = link_check.check_reply(text, str(eff))
    verdicts = {r["label"]: r["verdict"] for r in report}
    assert verdicts["old notes"] == "changed since it was registered"
    assert verdicts["lost"] == "unavailable now"


def test_a_broken_link_to_a_registered_product_is_corrected_to_its_registered_copy(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    text = "[the pdf](/artifact/%s?path=out/report.pdf)" % PID   # wrong: the project root, not the effort
    out, report = link_check.check_reply(text, str(eff))
    assert report and report[0]["verdict"] == "not found" and report[0]["fixed_to"]
    assert "deliverable-file" in out and "report.pdf" in out
    assert "(the link was not found)" in link_check.report_line(report)


def test_a_reply_without_links_is_untouched_and_a_failure_inside_never_raises(tmp_path, monkeypatch):
    _proj, eff = _effort(tmp_path, monkeypatch)
    assert link_check.check_reply("plain words only", str(eff)) == ("plain words only", [])
    monkeypatch.setattr(link_check, "_check_reply", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert link_check.check_reply("[x](/artifact/p?path=a)", str(eff)) == ("[x](/artifact/p?path=a)", [])


def test_the_engine_checks_links_before_recording_and_the_page_swaps_the_text():
    eng = (ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    i_check, i_record = eng.index("link_check.check_reply(txt, self.dir)"), eng.index('"steward", txt, turn_id=completed_turn_id')
    assert i_check < i_record
    assert '"t": "reply_links"' in eng and "_publish_link_report(completed_turn_id, link_report)" in eng
    js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert 'ev.t === "reply_links"' in js


def test_the_card_reads_a_product_through_the_register(tmp_path, monkeypatch):
    proj, eff = _effort(tmp_path, monkeypatch)
    from steward_cockpit import high_seat_card as card
    monkeypatch.setattr(card, "_effort_dir_of", lambda pid, rel: (str(eff), {"out/report.pdf", "out/report.html"}))
    html = card._item_link({"what": "Report", "path": "out/report.pdf"}, PID, "Effort")
    assert "deliverable-file" in html and "report.pdf" in html
    missing = card._item_link({"what": "Gone", "path": "out/gone.pdf"}, PID, "Effort")
    assert "<a " not in missing, "a missing file gets no link"
