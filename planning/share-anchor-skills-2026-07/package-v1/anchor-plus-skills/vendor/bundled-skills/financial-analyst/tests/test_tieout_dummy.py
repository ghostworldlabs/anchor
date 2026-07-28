import os
import tempfile
import openpyxl
from decimal import Decimal

def evaluate_simple_formula(formula, sheet):
    """
    A dummy Excel formula evaluator that handles simple cell references and addition.
    E.g., '=A1+B1' -> Decimal(A1) + Decimal(B1)
    """
    if not formula.startswith('='):
        raise ValueError(f"Not a formula: {formula}")
    
    expr = formula[1:].strip()
    if '+' in expr:
        left, right = expr.split('+')
        left_val = Decimal(str(sheet[left.strip()].value))
        right_val = Decimal(str(sheet[right.strip()].value))
        return left_val + right_val
    else:
        raise NotImplementedError(f"Dummy evaluator only supports '+' operator, got: {expr}")

def test_tieout_dummy():
    temp_filename = None
    # 1. Compute in Python using exact decimal math
    a_py = Decimal('10.00')
    b_py = Decimal('5.00')
    c_py = a_py + b_py
    
    # 2. Stand up a dummy Excel sheet and write values + formula
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tieout"
    
    ws['A1'] = a_py
    ws['B1'] = b_py
    ws['C1'] = "=A1+B1"
    
    # Save the workbook to a temporary file in a safe system temp location to avoid workspace pollution
    fd, temp_filename = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(temp_filename)
    
    try:
        # 3. Read it back
        wb_read = openpyxl.load_workbook(temp_filename)
        ws_read = wb_read["Tieout"]
        
        formula_c1 = ws_read['C1'].value
        
        # 4. Evaluate the Excel formula using our dummy evaluator
        c_excel = evaluate_simple_formula(formula_c1, ws_read)
        
        # 5. Assert they match exactly to the cent
        assert c_py == Decimal('15.00')
        assert c_excel == Decimal('15.00')
        assert c_py == c_excel
        
    finally:
        if temp_filename and os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except OSError:
                pass

def test_dependencies_exist():
    # 2026-07 cleanup: this skill is PYTHON-ONLY. The old assertion required a
    # package.json — the vestigial 26MB TypeScript toolchain installed to satisfy
    # a build gate and never used. The gate now encodes the opposite invariant:
    # requirements.txt is the dependency manifest, and the dead Node scaffolding
    # must NOT come back.
    base_dir = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(base_dir, 'requirements.txt'), 'r', encoding='utf-8') as f:
        assert len(f.read().strip()) > 0
    for dead in ('package.json', 'package-lock.json', 'tsconfig.json', 'node_modules'):
        assert not os.path.exists(os.path.join(base_dir, dead)), (
            f"{dead} is dead Node scaffolding — this skill is Python-only")


# --- W3 (2026-07-11): the tie-out is machine-checked; the Excel layout is labeled ---

def test_tie_out_is_machine_checked():
    """agent.tie_out() compiles the standalone Python, runs it, compares EVERY leaf,
    and emits the SKILL.md-mandated line — the signature guarantee has tooling now."""
    from agent_interface import create_agent
    from decimal import Decimal
    agent = create_agent()
    agent.load_template("vc_comp")
    r = agent.tie_out()
    assert r["ok"] is True
    assert r["nodes_compared"] >= 2
    assert r["max_delta"] == Decimal(0)
    assert r["mismatches"] == []
    assert r["line"].startswith("tie-out: ")
    assert "max delta 0" in r["line"]
    # and it re-verifies after an input change (the divergence class A2 removed)
    agent.set_input("investment_amount", 7500000.00)
    r2 = agent.tie_out()
    assert r2["ok"] is True


def test_excel_auto_layout_is_labeled():
    """Default compile: header + label column + one node per row — a handable sheet,
    not the old ~N unlabeled cells in row 1."""
    import os, tempfile
    import openpyxl
    from agent_interface import create_agent
    agent = create_agent()
    agent.load_template("vc_comp")
    with tempfile.TemporaryDirectory() as td:
        xlsx = os.path.join(td, "vc.xlsx")
        mapping = agent.compile_excel(xlsx)
        wb = openpyxl.load_workbook(xlsx)
        ws = wb.active
        assert ws["A1"].value == "Node"
        assert ws["B1"].value == "Value / Formula"
        # every node sits in column B with its id labeling it in column A
        for node_id, cell in mapping.items():
            assert cell.startswith("B"), f"{node_id} auto-assigned to {cell}, expected column B"
            row = cell[1:]
            assert ws[f"A{row}"].value == node_id, f"label missing for {node_id}"
        wb.close()
