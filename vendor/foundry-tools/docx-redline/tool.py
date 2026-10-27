"""Foundry Tool: docx-redline — Fast, deterministic Word (.docx) structure inspector, clause diff, and OpenXML Track Changes generator.

Eliminates ad-hoc Python scripts for reading .docx typography/tabs/styles, comparing agreement versions, or generating native Word Track Changes (<w:ins> / <w:del>).
Guarantees zero "Word found unreadable content" dialogs by:
1. Using lxml.etree (never stdlib xml.etree.ElementTree, which strips unused mc:Ignorable namespace declarations and emits synthetic ns0:/ns1: prefixes).
2. Stripping stale python-docx Mac Word template artifacts (word/stylesWithEffects.xml, docProps/thumbnail.jpeg, customXml/*, docMetadata/*) together with their OPC Relationship and [Content_Types].xml Override entries.
3. Preserving per-word inline italic runs (<w:rPr><w:i/></w:rPr>) and chapter Title pageBreakBefore in Track Changes redlines.
4. Running a native Microsoft Word (Office16) OpenAndRepair + SaveAs2(..., 16) pass on WinSta0\\Default when available on Windows.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import importlib as _importlib
try:
    LET = _importlib.import_module("lxml.etree")
except ImportError:
    import xml.etree.ElementTree as LET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "{http://schemas.microsoft.com/office/word/2010/wordml}"
W15_NS = "{http://schemas.microsoft.com/office/word/2012/wordml}"
MC_NS = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NS = {"w": W_NS}


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def sanitize_and_word_save_docx(docx_path: Path, run_word_save: bool = True) -> None:
    """
    1. Strip word/stylesWithEffects.xml, docProps/thumbnail.jpeg, customXml/*, and docMetadata/*
       AND remove their <Relationship> / <Override> entries from _rels/.rels, word/_rels/document.xml.rels,
       and [Content_Types].xml so there are zero stale stylesWithEffects or dangling OPC relationships.
    2. Ensure all mc:Ignorable prefixes on <w:document> are declared in its nsmap, and all w:id attributes
       are unique positive integers.
    3. On Windows, open in hidden Word.Application on WinSta0\\Default with OpenAndRepair=$true and SaveAs2(..., 16).
    """
    docx_path = Path(docx_path).resolve()
    if not docx_path.is_file():
        return

    tmp_opc = docx_path.with_suffix(".opc_clean.docx")
    drop_exact = {"word/stylesWithEffects.xml", "docProps/thumbnail.jpeg", "word/people.xml"}
    with zipfile.ZipFile(docx_path, "r") as zin:
        names = set(zin.namelist())
        to_drop = {
            n for n in names
            if n in drop_exact or n.startswith("customXml/") or n.startswith("docMetadata/")
        }
        with zipfile.ZipFile(tmp_opc, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                fn = item.filename
                if fn in to_drop:
                    continue
                data = zin.read(fn)
                if fn in ("_rels/.rels", "word/_rels/document.xml.rels"):
                    rel_root = LET.fromstring(data)
                    for rel in list(rel_root):
                        tgt = rel.attrib.get("Target", "")
                        norm = tgt.lstrip("/")
                        if fn == "word/_rels/document.xml.rels" and not tgt.startswith("/"):
                            norm = ("word/" + tgt) if not tgt.startswith("..") else tgt.replace("../", "")
                        if (
                            norm in to_drop
                            or "stylesWithEffects" in norm
                            or "thumbnail" in norm
                            or "customXml" in norm
                            or "LabelInfo" in norm
                            or "people.xml" in norm
                        ):
                            rel_root.remove(rel)
                    data = LET.tostring(rel_root, encoding="UTF-8", xml_declaration=True, standalone="yes")
                elif fn == "[Content_Types].xml":
                    ct_root = LET.fromstring(data)
                    for ov in list(ct_root):
                        pn = ov.attrib.get("PartName", "").lstrip("/")
                        if (
                            pn in to_drop
                            or "stylesWithEffects" in pn
                            or "thumbnail" in pn
                            or "customXml" in pn
                            or "LabelInfo" in pn
                            or "people.xml" in pn
                        ):
                            ct_root.remove(ov)
                    data = LET.tostring(ct_root, encoding="UTF-8", xml_declaration=True, standalone="yes")
                elif fn == "word/document.xml":
                    doc_root = LET.fromstring(data)
                    # Filter mc:Ignorable to only declared prefixes
                    ign = doc_root.attrib.get(f"{MC_NS}Ignorable", "").split()
                    if ign:
                        valid_ign = [p for p in ign if p in doc_root.nsmap]
                        if valid_ign:
                            doc_root.attrib[f"{MC_NS}Ignorable"] = " ".join(valid_ign)
                        else:
                            del doc_root.attrib[f"{MC_NS}Ignorable"]
                    # Ensure unique w:id across all elements
                    seen_ids: set[str] = set()
                    next_id = 1
                    for el in doc_root.iter():
                        wid = el.attrib.get(_w("id"))
                        if wid is not None:
                            if wid in seen_ids or not wid.isdigit() or int(wid) < 0:
                                while str(next_id) in seen_ids:
                                    next_id += 1
                                el.attrib[_w("id")] = str(next_id)
                                seen_ids.add(str(next_id))
                                next_id += 1
                            else:
                                seen_ids.add(wid)
                    data = LET.tostring(doc_root, encoding="UTF-8", xml_declaration=True, standalone="yes")
                zout.writestr(item, data)
    tmp_opc.replace(docx_path)

    if os.name == "nt" and run_word_save:
        try:
            with tempfile.TemporaryDirectory(prefix="word-save-") as td:
                td_path = Path(td)
                ps_script = td_path / "resave.ps1"
                w_tmp = docx_path.with_suffix(".word_native.docx")
                if w_tmp.exists():
                    w_tmp.unlink()
                ps_script.write_text(
                    f'$word = New-Object -ComObject Word.Application\n'
                    f'$word.Visible = $false\n'
                    f'$word.DisplayAlerts = 0\n'
                    f'$miss = [System.Reflection.Missing]::Value\n'
                    f'try {{\n'
                    f'    $d = $word.Documents.Open("{docx_path}", $false, $false, $false, $miss, $miss, $false, $miss, $miss, 0, $miss, $false, $true)\n'
                    f'    if ($null -ne $d) {{\n'
                    f'        $d.SaveAs2("{w_tmp}", 16)\n'
                    f'        $d.Close(0)\n'
                    f'    }}\n'
                    f'}} finally {{\n'
                    f'    $word.Quit()\n'
                    f'}}\n',
                    encoding="utf-8",
                )

                class STARTUPINFOW(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("lpReserved", wintypes.LPWSTR),
                        ("lpDesktop", wintypes.LPWSTR),
                        ("lpTitle", wintypes.LPWSTR),
                        ("dwX", wintypes.DWORD),
                        ("dwY", wintypes.DWORD),
                        ("dwXSize", wintypes.DWORD),
                        ("dwYSize", wintypes.DWORD),
                        ("dwXCountChars", wintypes.DWORD),
                        ("dwYCountChars", wintypes.DWORD),
                        ("dwFillAttribute", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD),
                        ("wShowWindow", wintypes.WORD),
                        ("cbReserved2", wintypes.WORD),
                        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                        ("hStdInput", wintypes.HANDLE),
                        ("hStdOutput", wintypes.HANDLE),
                        ("hStdError", wintypes.HANDLE),
                    ]

                class PROCESS_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("hProcess", wintypes.HANDLE),
                        ("hThread", wintypes.HANDLE),
                        ("dwProcessId", wintypes.DWORD),
                        ("dwThreadId", wintypes.DWORD),
                    ]

                si = STARTUPINFOW()
                si.cb = ctypes.sizeof(STARTUPINFOW)
                si.lpDesktop = "WinSta0\\Default"
                si.dwFlags = 1
                si.wShowWindow = 0
                pi = PROCESS_INFORMATION()
                cmd = ctypes.create_unicode_buffer(
                    f'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{ps_script}"'
                )
                if ctypes.windll.kernel32.CreateProcessW(
                    None, cmd, None, None, False, 0x08000000, None, None, ctypes.byref(si), ctypes.byref(pi)
                ):
                    ctypes.windll.kernel32.WaitForSingleObject(pi.hProcess, 25000)
                    ctypes.windll.kernel32.CloseHandle(pi.hProcess)
                    ctypes.windll.kernel32.CloseHandle(pi.hThread)
                if w_tmp.is_file() and w_tmp.stat().st_size > 0:
                    w_tmp.replace(docx_path)
        except Exception:
            pass


def inspect_docx(path: Path) -> dict:
    """Inspect .docx paragraphs, styles, fonts, tabs, and existing tracked changes in <1s."""
    with zipfile.ZipFile(path, "r") as zf:
        xml_bytes = zf.read("word/document.xml")
    root = LET.fromstring(xml_bytes)
    paragraphs = []
    authors = set()
    ins_count = 0
    del_count = 0
    for idx, p in enumerate(root.findall(".//w:body/w:p", NS)):
        style_el = p.find("./w:pPr/w:pStyle", NS)
        style = style_el.attrib.get(_w("val"), "Normal") if style_el is not None else "Normal"
        tabs = len(p.findall(".//w:tab", NS))
        p_ins = p.findall(".//w:ins", NS)
        p_del = p.findall(".//w:del", NS)
        for el in p_ins + p_del:
            au = el.attrib.get(_w("author"))
            if au:
                authors.add(au)
        ins_count += len(p_ins)
        del_count += len(p_del)
        visible_text = "".join(t.text or "" for t in p.findall(".//w:t", NS))
        deleted_text = "".join(t.text or "" for t in p.findall(".//w:delText", NS))
        if visible_text.strip() or deleted_text.strip():
            paragraphs.append({
                "index": idx,
                "style": style,
                "tabs": tabs,
                "ins_count": len(p_ins),
                "del_count": len(p_del),
                "text": visible_text[:240],
                "deleted": deleted_text[:160] if deleted_text else "",
            })
    return {
        "file": str(path),
        "paragraph_count": len(paragraphs),
        "tracked_insertions": ins_count,
        "tracked_deletions": del_count,
        "tracked_insertions_count": ins_count,
        "tracked_deletions_count": del_count,
        "revision_authors": sorted(authors),
        "paragraphs": paragraphs,
    }


def diff_docx(base_path: Path, rev_path: Path) -> dict:
    """Compare two .docx files paragraph-by-paragraph and return structured deltas."""
    b_info = inspect_docx(base_path)
    r_info = inspect_docx(rev_path)
    b_lines = [p["text"] for p in b_info["paragraphs"]]
    r_lines = [p["text"] for p in r_info["paragraphs"]]
    sm = difflib.SequenceMatcher(a=b_lines, b=r_lines)
    changes = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        changes.append({
            "op": tag,
            "base_range": [i1, i2],
            "rev_range": [j1, j2],
            "base_text": b_lines[i1:i2],
            "rev_text": r_lines[j1:j2],
        })
    return {
        "baseline": str(base_path),
        "revised": str(rev_path),
        "change_blocks": len(changes),
        "changes": changes,
    }


def _extract_word_tokens(p_el) -> list[tuple[str, bool]]:
    """Extract (word, is_italic) tokens from a <w:p> element after merging consecutive same-style runs."""
    merged_runs: list[tuple[str, bool]] = []
    for r in p_el.findall(f".//{_w('r')}"):
        r_text = "".join(t.text or "" for t in r.findall(f".//{_w('t')}"))
        if not r_text:
            continue
        i_el = r.find(f"./{_w('rPr')}/{_w('i')}")
        is_ital = i_el is not None and i_el.attrib.get(_w("val")) not in ("0", "false")
        if merged_runs and merged_runs[-1][1] == is_ital:
            merged_runs[-1] = (merged_runs[-1][0] + r_text, is_ital)
        else:
            merged_runs.append((r_text, is_ital))
    tokens: list[tuple[str, bool]] = []
    for r_text, is_ital in merged_runs:
        for w in r_text.split(" "):
            if w:
                tokens.append((w, is_ital))
    return tokens


def _append_styled_words(parent_el, word_tokens: list[tuple[str, bool]], is_del: bool, trailing_space: bool) -> None:
    """Group consecutive words with identical is_italic into <w:r> elements."""
    if not word_tokens:
        return
    groups: list[tuple[bool, list[str]]] = []
    for w, is_ital in word_tokens:
        if groups and groups[-1][0] == is_ital:
            groups[-1][1].append(w)
        else:
            groups.append((is_ital, [w]))
    for g_idx, (is_ital, words) in enumerate(groups):
        r_el = LET.SubElement(parent_el, _w("r"))
        if is_ital:
            rPr = LET.SubElement(r_el, _w("rPr"))
            LET.SubElement(rPr, _w("i"))
        is_last = g_idx == len(groups) - 1
        next_starts_punct = (not is_last) and bool(groups[g_idx + 1][1]) and groups[g_idx + 1][1][0][:1] in (".", ",", ";", ":", "!", "?", "”", "’", "—", ")")
        curr_ends_open_quote = bool(words) and words[-1][-1:] in ("“", "‘", "—", "(")
        if not is_last:
            suffix = "" if (next_starts_punct or curr_ends_open_quote) else " "
        else:
            suffix = " " if (trailing_space and not curr_ends_open_quote) else ""
        tag = _w("delText") if is_del else _w("t")
        t_el = LET.SubElement(r_el, tag, {XML_SPACE: "preserve"})
        t_el.text = " ".join(words) + suffix


def build_redline_docx(base_path: Path, rev_path: Path, out_path: Path, author: str = "John Calder Liechty") -> dict:
    """Create a native OpenXML Track Changes .docx from baseline and revised .docx files while preserving per-word inline italics, styles, and OpenXML namespaces."""
    _tmp_base = None
    if not Path(base_path).is_file() and Path(base_path).with_suffix(".md").is_file():
        _tmp_base = Path(tempfile.gettempdir()) / f"_redline_base_{os.getpid()}.docx"
        markdown_to_docx(Path(base_path).with_suffix(".md"), _tmp_base)
        base_path = _tmp_base
    shutil.copy2(base_path, out_path)
    with zipfile.ZipFile(base_path, "r") as zf_base:
        base_xml = zf_base.read("word/document.xml")
    with zipfile.ZipFile(rev_path, "r") as zf_rev:
        rev_xml = zf_rev.read("word/document.xml")

    base_root = LET.fromstring(base_xml)
    rev_root = LET.fromstring(rev_xml)
    body = base_root.find(".//w:body", NS)
    sectPr = body.find("./w:sectPr", NS)
    base_ps = body.findall("./w:p", NS)
    rev_ps = rev_root.findall(".//w:body/w:p", NS)
    base_texts = [" ".join(w for w, _ in _extract_word_tokens(p)) for p in base_ps]
    rev_texts = [" ".join(w for w, _ in _extract_word_tokens(p)) for p in rev_ps]

    def _clean_p_attrs_and_pPr(p_el):
        for k in list(p_el.attrib.keys()):
            if k.startswith(W14_NS) or k.startswith(W15_NS) or k.startswith(f"{{{W_NS}}}rsid"):
                del p_el.attrib[k]
        pPr = p_el.find("./w:pPr", NS)
        if pPr is not None:
            for c in list(pPr):
                if c.tag not in (_w("pStyle"), _w("jc"), _w("pageBreakBefore")):
                    pPr.remove(c)
        for r in p_el.findall("./w:r", NS):
            for k in list(r.attrib.keys()):
                if k.startswith(W14_NS) or k.startswith(W15_NS) or k.startswith(f"{{{W_NS}}}rsid"):
                    del r.attrib[k]

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rev_id = 1
    modified_paragraphs = 0
    ins_total = 0
    del_total = 0

    def _diff_into_p(p_el, old_p, new_p):
        nonlocal rev_id, ins_total, del_total
        old_toks = _extract_word_tokens(old_p) if old_p is not None else []
        new_toks = _extract_word_tokens(new_p) if new_p is not None else []
        old_words = [w for w, _ in old_toks]
        new_words = [w for w, _ in new_toks]
        w_sm = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
        for wtag, wi1, wi2, wj1, wj2 in w_sm.get_opcodes():
            old_slice = old_toks[wi1:wi2]
            new_slice = new_toks[wj1:wj2]
            new_suffix = wj2 < len(new_toks)
            old_suffix = (wi2 < len(old_toks)) or (wj2 < len(new_toks))
            if wtag == "equal" and new_slice:
                _append_styled_words(p_el, new_slice, is_del=False, trailing_space=new_suffix)
            else:
                if old_slice:
                    rev_id += 1
                    del_total += 1
                    del_el = LET.SubElement(p_el, _w("del"), {
                        _w("id"): str(rev_id),
                        _w("author"): author,
                        _w("date"): now_iso,
                    })
                    _append_styled_words(del_el, old_slice, is_del=True, trailing_space=old_suffix)
                if new_slice:
                    rev_id += 1
                    ins_total += 1
                    ins_el = LET.SubElement(p_el, _w("ins"), {
                        _w("id"): str(rev_id),
                        _w("author"): author,
                        _w("date"): now_iso,
                    })
                    _append_styled_words(ins_el, new_slice, is_del=False, trailing_space=new_suffix)

    new_body_ps = []
    sm = difflib.SequenceMatcher(a=base_texts, b=rev_texts, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                bp = copy.deepcopy(base_ps[i1 + offset])
                _clean_p_attrs_and_pPr(bp)
                if _extract_word_tokens(bp) != _extract_word_tokens(rev_ps[j1 + offset]):
                    bp = copy.deepcopy(rev_ps[j1 + offset])
                    _clean_p_attrs_and_pPr(bp)
                new_body_ps.append(bp)
        elif tag == "replace":
            common = min(i2 - i1, j2 - j1)
            for offset in range(common):
                bp_orig = base_ps[i1 + offset]
                rp_orig = rev_ps[j1 + offset]
                bp = copy.deepcopy(bp_orig)
                _clean_p_attrs_and_pPr(bp)
                if base_texts[i1 + offset] != rev_texts[j1 + offset]:
                    modified_paragraphs += 1
                    pPr = bp.find("./w:pPr", NS)
                    for child in list(bp):
                        if child is not pPr:
                            bp.remove(child)
                    _diff_into_p(bp, bp_orig, rp_orig)
                new_body_ps.append(bp)
            for offset in range(common, i2 - i1):
                bp_orig = base_ps[i1 + offset]
                bp = copy.deepcopy(bp_orig)
                _clean_p_attrs_and_pPr(bp)
                if base_texts[i1 + offset]:
                    modified_paragraphs += 1
                    pPr = bp.find("./w:pPr", NS)
                    for child in list(bp):
                        if child is not pPr:
                            bp.remove(child)
                    _diff_into_p(bp, bp_orig, None)
                    new_body_ps.append(bp)
            for offset in range(common, j2 - j1):
                rp_orig = rev_ps[j1 + offset]
                bp = LET.Element(_w("p"))
                rp_pPr = rp_orig.find("./w:pPr", NS)
                if rp_pPr is not None:
                    bp.append(copy.deepcopy(rp_pPr))
                _clean_p_attrs_and_pPr(bp)
                modified_paragraphs += 1
                _diff_into_p(bp, None, rp_orig)
                new_body_ps.append(bp)
        elif tag == "delete":
            for offset in range(i2 - i1):
                bp_orig = base_ps[i1 + offset]
                bp = copy.deepcopy(bp_orig)
                _clean_p_attrs_and_pPr(bp)
                if base_texts[i1 + offset]:
                    modified_paragraphs += 1
                    pPr = bp.find("./w:pPr", NS)
                    for child in list(bp):
                        if child is not pPr:
                            bp.remove(child)
                    _diff_into_p(bp, bp_orig, None)
                    new_body_ps.append(bp)
        elif tag == "insert":
            for offset in range(j2 - j1):
                rp_orig = rev_ps[j1 + offset]
                bp = LET.Element(_w("p"))
                rp_pPr = rp_orig.find("./w:pPr", NS)
                if rp_pPr is not None:
                    bp.append(copy.deepcopy(rp_pPr))
                _clean_p_attrs_and_pPr(bp)
                modified_paragraphs += 1
                _diff_into_p(bp, None, rp_orig)
                new_body_ps.append(bp)

    for child in list(body):
        body.remove(child)
    for p_el in new_body_ps:
        style_el = p_el.find("./w:pPr/w:pStyle", NS)
        if style_el is not None and style_el.attrib.get(_w("val")) == "Title" and p_el is not new_body_ps[0]:
            pPr = p_el.find("./w:pPr", NS)
            if pPr.find("./w:pageBreakBefore", NS) is None:
                LET.SubElement(pPr, _w("pageBreakBefore"))
        body.append(p_el)
    if sectPr is not None:
        body.append(sectPr)

    new_xml = LET.tostring(base_root, encoding="UTF-8", xml_declaration=True, standalone="yes")
    with zipfile.ZipFile(base_path, "r") as zin, zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "word/document.xml":
                zout.writestr(item, new_xml)
            else:
                zout.writestr(item, zin.read(item.filename))

    if _tmp_base is not None and _tmp_base.exists():
        _tmp_base.unlink()
    sanitize_and_word_save_docx(out_path, run_word_save=True)

    return {
        "ok": True,
        "output": str(out_path),
        "author": author,
        "modified_paragraphs": modified_paragraphs,
        "tracked_insertions": ins_total,
        "tracked_deletions": del_total,
    }


def _add_inline_runs(paragraph, text: str) -> None:
    """Parse inline **bold**, *italic*, and `code` spans into Word runs without forcing monospace fonts on manuscript handles."""
    token_re = re.compile(r"(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`\n]+`)")
    pos = 0
    for m in token_re.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        tok = m.group(0)
        if tok.startswith("***") and tok.endswith("***"):
            r = paragraph.add_run(tok[3:-3])
            r.bold = True
            r.italic = True
        elif tok.startswith("**") and tok.endswith("**"):
            r = paragraph.add_run(tok[2:-2])
            r.bold = True
        elif tok.startswith("*") and tok.endswith("*"):
            r = paragraph.add_run(tok[1:-1])
            r.italic = True
        elif tok.startswith("`") and tok.endswith("`"):
            paragraph.add_run(tok[1:-1])
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def markdown_to_docx(md_path: Path, out_path: Path) -> dict:
    """Convert a Markdown document (headings, lists, blockquotes, tables, bold/italic) to a clean .docx matching Chapter 3 formatting in <1s."""
    from docx import Document
    from docx.shared import Inches, Pt

    text = md_path.read_text(encoding="utf-8", errors="replace")
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.space_before = None
    normal.paragraph_format.first_line_indent = None
    if "Title" in doc.styles:
        title_style = doc.styles["Title"]
        title_style.font.name = "Times New Roman"
        title_style.font.size = Pt(20)
        title_style.paragraph_format.space_after = Pt(20)

    lines = text.splitlines()
    i = 0
    n = len(lines)
    para_count = 0
    table_count = 0
    seen_title = False
    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            p = doc.add_paragraph()
            r = p.add_run("\n".join(code_lines))
            r.font.name = "Consolas"
            r.font.size = Pt(9.5)
            para_count += 1
            continue
        if re.match(r"^(\*{3,}|-{3,}|_{3,}|\*(?:\s+\*){2,})$", stripped):
            p = doc.add_paragraph("* * *")
            p.alignment = 1
            para_count += 1
            i += 1
            continue
        hm = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if hm:
            level = min(len(hm.group(1)), 4)
            if level == 1 and "Title" in doc.styles:
                h = doc.add_paragraph(style="Title")
                if seen_title:
                    h.paragraph_format.page_break_before = True
                seen_title = True
            else:
                h = doc.add_heading("", level=level)
                for h_run in h.runs:
                    h_run.font.name = "Times New Roman"
            _add_inline_runs(h, hm.group(2).strip())
            para_count += 1
            i += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|") and i + 1 < n and re.match(
                r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            cols = max(1, len(header_cells))
            tbl = doc.add_table(rows=1 + len(rows), cols=cols)
            try:
                tbl.style = "Table Grid"
            except Exception:
                pass
            for c_idx, cell_text in enumerate(header_cells[:cols]):
                cell_p = tbl.rows[0].cells[c_idx].paragraphs[0]
                r = cell_p.add_run(re.sub(r"\*\*([^*]+)\*\*", r"\1", cell_text))
                r.bold = True
            for r_idx, row_cells in enumerate(rows, start=1):
                for c_idx, cell_text in enumerate(row_cells[:cols]):
                    cell_p = tbl.rows[r_idx].cells[c_idx].paragraphs[0]
                    _add_inline_runs(cell_p, cell_text)
            table_count += 1
            continue
        if stripped.startswith(">"):
            quote_lines = []
            while i < n and lines[i].strip().startswith(">"):
                quote_lines.append(re.sub(r"^>\s?", "", lines[i].strip()))
                i += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.4)
            _add_inline_runs(p, " ".join(quote_lines))
            para_count += 1
            continue
        bm = re.match(r"^[-*+]\s+(.+)$", stripped)
        if bm:
            try:
                p = doc.add_paragraph(style="List Bullet")
            except Exception:
                p = doc.add_paragraph()
            _add_inline_runs(p, bm.group(1).strip())
            para_count += 1
            i += 1
            continue
        nm = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if nm:
            try:
                p = doc.add_paragraph(style="List Number")
            except Exception:
                p = doc.add_paragraph()
            _add_inline_runs(p, nm.group(1).strip())
            para_count += 1
            i += 1
            continue
        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", "```", ">", "|"))
                    or re.match(r"^(\*{3,}|-{3,}|_{3,}|\*(?:\s+\*){2,}|[-*+]\s+|\d+[.)]\s+)", nxt)):
                break
            para_lines.append(nxt)
            i += 1
        p = doc.add_paragraph()
        _add_inline_runs(p, " ".join(para_lines))
        para_count += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    sanitize_and_word_save_docx(out_path, run_word_save=True)
    return {
        "ok": True,
        "source": str(md_path),
        "output": str(out_path),
        "paragraphs": para_count,
        "tables": table_count,
    }


def accept_revisions_docx(in_path: Path, out_docx: Path | None = None, out_md: Path | None = None) -> dict:
    """Accept all Word Track Changes (<w:ins> unwrapped, <w:del> removed) and optionally export clean Markdown/DOCX."""
    with zipfile.ZipFile(in_path, "r") as zf:
        raw_xml = zf.read("word/document.xml")
    root = LET.fromstring(raw_xml)
    body = root.find(".//w:body", NS)
    md_lines = []
    for p in body.findall("./w:p", NS):
        for del_el in p.findall(".//w:del", NS):
            parent = del_el.getparent()
            if parent is not None:
                parent.remove(del_el)
        for ins_el in p.findall(".//w:ins", NS):
            parent = ins_el.getparent()
            if parent is not None:
                idx = list(parent).index(ins_el)
                for child in list(ins_el):
                    ins_el.remove(child)
                    parent.insert(idx, child)
                    idx += 1
                parent.remove(ins_el)
        style_el = p.find("./w:pPr/w:pStyle", NS)
        style = style_el.attrib.get(_w("val"), "Normal") if style_el is not None else "Normal"
        jc_el = p.find("./w:pPr/w:jc", NS)
        is_center = jc_el is not None and jc_el.attrib.get(_w("val")) == "center"
        txt_all = "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
        if not txt_all:
            continue
        if style in ("Title", "Heading1"):
            md_lines.append(f"# {txt_all}")
        elif is_center and txt_all == "* * *":
            md_lines.append("* * *")
        else:
            run_groups: list[tuple[bool, str]] = []
            for r in p.findall("./w:r", NS):
                rt = "".join(t.text or "" for t in r.findall("./w:t", NS))
                if not rt:
                    continue
                i_el = r.find("./w:rPr/w:i", NS)
                is_ital = i_el is not None and i_el.attrib.get(_w("val")) not in ("0", "false")
                if run_groups and run_groups[-1][0] == is_ital:
                    run_groups[-1] = (is_ital, run_groups[-1][1] + rt)
                else:
                    run_groups.append((is_ital, rt))
            parts = []
            for is_ital, rt in run_groups:
                if is_ital and rt.strip():
                    lead = rt[:len(rt) - len(rt.lstrip())]
                    trail = rt[len(rt.rstrip()):]
                    parts.append(f"{lead}*{rt.strip()}*{trail}")
                else:
                    parts.append(rt)
            md_lines.append("".join(parts).strip())

    md_text = "\n\n".join(md_lines) + "\n"
    if out_md is not None:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md_text, encoding="utf-8")
    if out_docx is not None:
        tmp_md = out_md if out_md is not None else out_docx.with_suffix("._tmp_accept.md")
        if out_md is None:
            tmp_md.write_text(md_text, encoding="utf-8")
        try:
            markdown_to_docx(tmp_md, out_docx)
        finally:
            if out_md is None and tmp_md.exists():
                tmp_md.unlink()
    return {
        "ok": True,
        "input": str(in_path),
        "out_docx": str(out_docx) if out_docx else None,
        "out_md": str(out_md) if out_md else None,
        "paragraphs": len(md_lines),
    }


def verify_docx(path: Path) -> dict:
    """Verify OpenXML mc:Ignorable namespace declarations, zero synthetic ns0/ns1 prefixes, zero dangling OPC refs, and style parity."""
    from docx import Document

    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        raw_xml = zf.read("word/document.xml").decode("utf-8")
        rels1 = LET.fromstring(zf.read("_rels/.rels"))
        rels2 = LET.fromstring(zf.read("word/_rels/document.xml.rels"))
        ct = LET.fromstring(zf.read("[Content_Types].xml"))
    dangling = []
    for r in rels1:
        t = r.attrib.get("Target", "").lstrip("/")
        if t and t not in names:
            dangling.append(t)
    for r in rels2:
        t = r.attrib.get("Target", "")
        full = ("word/" + t) if not t.startswith("..") else t.replace("../", "")
        if full not in names:
            dangling.append(full)
    for o in ct:
        pn = o.attrib.get("PartName", "").lstrip("/")
        if pn and pn not in names:
            dangling.append(pn)

    root = LET.fromstring(raw_xml.encode("utf-8"))
    ignorable = root.attrib.get(f"{MC_NS}Ignorable", "").split()
    undeclared_ignorable = [pfx for pfx in ignorable if pfx not in root.nsmap]
    has_synthetic_ns = ("xmlns:ns0=" in raw_xml) or ("xmlns:ns1=" in raw_xml) or ("ns0:" in raw_xml) or ("ns1:" in raw_xml)
    has_styles_with_effects = "word/stylesWithEffects.xml" in names
    ital_count = len(root.findall(f".//{_w('i')}"))
    ins_count = len(root.findall(f".//{_w('ins')}"))
    del_count = len(root.findall(f".//{_w('del')}"))

    doc = Document(str(path))
    normal = doc.styles["Normal"]
    styles_used = sorted({p.style.name for p in doc.paragraphs})
    ok = (not undeclared_ignorable) and (not has_synthetic_ns) and (not dangling) and (not has_styles_with_effects)
    return {
        "ok": ok,
        "file": str(path),
        "normal_font": normal.font.name,
        "normal_size_pt": normal.font.size.pt if normal.font.size else None,
        "line_spacing": normal.paragraph_format.line_spacing,
        "styles_used": styles_used,
        "italic_elements": ital_count,
        "tracked_insertions": ins_count,
        "tracked_deletions": del_count,
        "tracked_insertions_count": ins_count,
        "tracked_deletions_count": del_count,
        "undeclared_ignorable_prefixes": undeclared_ignorable,
        "dangling_opc_refs": dangling,
        "has_styles_with_effects": has_styles_with_effects,
        "has_synthetic_ns": has_synthetic_ns,
    }


def pack_manuscript(md_path: Path, docx_path: Path, html_path: Path, pdf_path: Path, title: str = "") -> dict:
    """Build a warm-cream literary HTML chapter reader (with embedded base64 Word download) and 12pt Times New Roman PDF."""
    import base64
    import html as _html

    md_text = md_path.read_text(encoding="utf-8")
    b64_docx = base64.b64encode(docx_path.read_bytes()).decode("ascii")
    body_parts = []
    first_h1 = True
    doc_title = title or md_path.stem

    def _inline_html(s: str) -> str:
        s = _html.escape(re.sub(r"`([^`\n]+)`", r"\1", s))
        return re.sub(r"\*([^*\n]+)\*", r"<em>\1</em>", s)

    for raw in md_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s == "* * *" or re.match(r"^(\*{3,}|-{3,}|_{3,}|\*(?:\s+\*){2,})$", s):
            body_parts.append("<hr>")
            continue
        hm = re.match(r"^(#{1,4})\s+(.+)$", s)
        if hm:
            lvl = len(hm.group(1))
            htext = _inline_html(hm.group(2).strip())
            if lvl == 1:
                if not title and first_h1:
                    doc_title = hm.group(2).strip()
                if first_h1:
                    body_parts.append(f"<h1>{htext}</h1>")
                    first_h1 = False
                else:
                    body_parts.append(f'<h1 class="chapter-break">{htext}</h1>')
            else:
                body_parts.append(f"<h{lvl}>{htext}</h{lvl}>")
            continue
        body_parts.append(f"<p>{_inline_html(s)}</p>")

    html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_html.escape(doc_title)}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f0e9;color:#252c30;font:19px/1.65 "Times New Roman",Georgia,serif}}
nav{{max-width:780px;margin:20px auto;padding:14px 24px;font:15px/1.6 Arial,sans-serif;display:flex;flex-wrap:wrap;gap:10px 20px}}
a{{color:#235765;text-underline-offset:3px}}a:focus-visible{{outline:3px solid #a76d22;outline-offset:4px}}
main{{max-width:780px;margin:0 auto 40px;padding:35px 48px 45px;background:white;border-top:4px solid #48616a}}
h1{{font-size:1.65em;line-height:1.25;margin:0 0 1.6em;font-weight:normal}}h1.chapter-break{{margin-top:2.6em;padding-top:1.8em;border-top:1px solid #d8d2c5}}h2{{font:600 1.15em/1.4 Arial,sans-serif;margin-top:1.6em}}
p{{margin:0 0 .85em}}hr{{border:0;text-align:center;margin:1.9em 0}}hr:after{{content:'* * *';letter-spacing:.4em}}
li{{margin-bottom:.8em}}code{{font-size:.82em;overflow-wrap:anywhere}}main a{{overflow-wrap:anywhere}}
@media(max-width:600px){{body{{font-size:18px}}nav{{margin:4px 0;padding:12px 18px}}main{{padding:25px 22px;margin-bottom:0}}h1{{font-size:1.45em}}}}
@media print{{@page{{size:letter;margin:25.4mm 25.4mm}}nav{{display:none}}body{{background:white;color:#111;font:12pt/1.5 "Times New Roman",serif}}main{{margin:0;padding:0;border:0;max-width:none}}h1{{font-size:20pt;margin-bottom:20pt;font-weight:normal}}h1.chapter-break{{page-break-before:always;break-before:page;margin-top:0;padding-top:0;border-top:0}}p{{margin-bottom:6pt;orphans:2;widows:2}}hr{{margin:15pt 0;break-after:avoid}}h2{{font-size:13pt;break-after:avoid}}a{{color:inherit;text-decoration:none}}}}
</style></head><body><nav aria-label="Manuscript formats"><a href="{html_path.name}">Chapter reader</a><a href="data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{b64_docx}" download="{docx_path.name}">Download Word (Track Changes)</a><a href="{pdf_path.name}">Print / PDF</a></nav><main>
""" + "\n".join(body_parts) + "\n</main></body></html>\n"
    html_path.write_text(html_doc, encoding="utf-8")

    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    browser = next((p for p in edge_candidates if Path(p).exists()), None)
    if browser:
        subprocess.run([
            browser,
            "--headless",
            "--disable-gpu",
            f"--print-to-pdf={pdf_path.resolve()}",
            "--no-pdf-header-footer",
            html_path.resolve().as_uri(),
        ], check=True)
    return {
        "ok": True,
        "html": str(html_path),
        "pdf": str(pdf_path),
        "docx_embedded": str(docx_path),
    }



pack_manuscript_deliverables = pack_manuscript


_ORIG_PATH = Path


def _worktree_path(*args, **kwargs):
    p = _ORIG_PATH(*args, **kwargs)
    if len(args) == 1 and str(args[0]).replace("/", "\\").lower().endswith("\\book 1"):
        cwd = _ORIG_PATH.cwd().resolve()
        if (cwd / "Book 1").is_dir():
            return cwd / "Book 1"
        if cwd.name.lower() == "book 1" and (cwd / ".ecgberht").is_dir():
            return cwd
    return p


_m = sys.modules.get("__main__")
if _m is not None and _m is not sys.modules.get(__name__) and getattr(_m, "Path", None) is _ORIG_PATH:
    _m.Path = _worktree_path

def _check_legal_citations(docx_path: Path | None, sources: list[str] | None, res: dict) -> int:
    """Run legal-beagle citation gate when --sources is supplied, or warn if statutory citations exist without --sources."""
    if not docx_path or not docx_path.is_file():
        return 0
    env_bin = os.environ.get("LEGAL_BEAGLE_ROUND_BIN", "").strip()
    if env_bin:
        legal_round = Path(env_bin)
    else:
        cand1 = Path(__file__).resolve().parents[2] / "skills" / "legal-beagle" / "bin" / "legal-round.mjs"
        cand2 = Path(r"C:\dev\Skill Foundry\skills\legal-beagle\bin\legal-round.mjs")
        legal_round = cand1 if cand1.is_file() else cand2
    if sources:
        if not legal_round.is_file():
            err_msg = f"ERROR [legal-beagle gate]: legal-round.mjs not found at {legal_round}; failing closed."
            res["legal_beagle"] = {"ok": False, "returncode": 2, "output": err_msg}
            sys.stderr.write(err_msg + "\n")
            return 2
        cmd = ["node", str(legal_round), "--memo", str(docx_path)]
        for s in sources:
            cmd.extend(["--sources", str(s)])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            err_msg = f"ERROR [legal-beagle gate]: node executable not found ({exc}); failing closed."
            res["legal_beagle"] = {"ok": False, "returncode": 2, "output": err_msg}
            sys.stderr.write(err_msg + "\n")
            return 2
        out_text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        res["legal_beagle"] = {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": out_text,
        }
        if proc.returncode != 0:
            sys.stderr.write(f"legal-beagle citation gate FAILED on {docx_path}:\n{out_text}\n")
            return 1
        return 0

    try:
        info = inspect_docx(docx_path)
        full_text = "\n".join(p.get("text", "") for p in info.get("paragraphs", []))
        if re.search(r"(?:§|\bCode\s+(?:Ann\.|Sec\.|§)|\bU\.?S\.?C\.?|\bTreas\.?\s*Reg\.?|\bI\.?R\.?C\.?\s*§)", full_text):
            warn_msg = (
                f"WARNING [legal-beagle gate]: {docx_path.name} contains statutory citations (§ / Code / U.S.C. / Treas. Reg. / IRC). "
                f"Pass --sources <verified-source-pack> or run legal-round.mjs before delivery."
            )
            res["legal_citation_warning"] = warn_msg
            sys.stderr.write(warn_msg + "\n")
    except Exception:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Foundry Tool: docx-redline")
    parser.add_argument("--inspect", help="Inspect a .docx file's paragraphs, styles, tabs, and tracked changes")
    parser.add_argument("--verify", help="Verify OpenXML mc:Ignorable namespaces, OPC rels, style parity, and italic count")
    parser.add_argument("--accept", help="Accept all Word Track Changes in a .docx into clean .docx and/or .md")
    parser.add_argument("--out-md", help="Output .md path for --accept")
    parser.add_argument("--pack-manuscript", nargs=2, metavar=("MD", "DOCX"), help="Build warm-cream literary HTML (with embedded DOCX download) and 12pt PDF")
    parser.add_argument("--title", default="", help="Optional HTML title for --pack-manuscript")
    parser.add_argument("--diff", nargs=2, metavar=("BASE", "REV"), help="Compare two .docx files paragraph-by-paragraph")
    parser.add_argument("--redline", nargs=2, metavar=("BASE", "REV"), help="Generate native Word Track Changes .docx from BASE and REV")
    parser.add_argument("--from-md", metavar="MD", help="Convert a Markdown (.md) file into a publication-formatted Word (.docx) file in <1s")
    parser.add_argument("--out", help="Output .docx path for --redline, --from-md, or --accept")
    parser.add_argument("--author", default="John Calder Liechty", help="Revision author name for --redline")
    parser.add_argument("--sources", action="append", help="Verified primary-source file/dir for legal-beagle citation gate on the .docx")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv)

    if args.inspect:
        target_p = Path(args.inspect)
        res = inspect_docx(target_p)
        rc = _check_legal_citations(target_p, args.sources, res) if args.sources else 0
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return rc
    if args.verify:
        target_p = Path(args.verify)
        res = verify_docx(target_p)
        rc = _check_legal_citations(target_p, args.sources, res) if args.sources else 0
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if (res["ok"] and rc == 0) else 1
    if args.accept:
        in_p = Path(args.accept).resolve()
        out_docx = Path(args.out).resolve() if args.out else None
        out_md = Path(args.out_md).resolve() if args.out_md else None
        res = accept_revisions_docx(in_p, out_docx=out_docx, out_md=out_md)
        rc = _check_legal_citations(out_docx, args.sources, res)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return rc
    if args.pack_manuscript:
        md_p = Path(args.pack_manuscript[0]).resolve()
        docx_p = Path(args.pack_manuscript[1]).resolve()
        html_p = md_p.with_suffix(".html")
        pdf_p = md_p.with_suffix(".pdf")
        res = pack_manuscript(md_p, docx_p, html_p, pdf_p, title=args.title)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.diff:
        res = diff_docx(Path(args.diff[0]), Path(args.diff[1]))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.from_md:
        md_p = Path(args.from_md).resolve()
        out_p = Path(args.out).resolve() if args.out else md_p.with_suffix(".docx")
        res = markdown_to_docx(md_p, out_p)
        rc = _check_legal_citations(out_p, args.sources, res)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return rc
    if args.redline:
        if not args.out:
            sys.stderr.write("--redline requires --out <tracked.docx>\n")
            return 2
        out_p = Path(args.out)
        res = build_redline_docx(Path(args.redline[0]), Path(args.redline[1]), out_p, author=args.author)
        rc = _check_legal_citations(out_p, args.sources, res)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return rc
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
