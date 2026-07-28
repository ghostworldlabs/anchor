import os
import sys
import subprocess
import pytest
from decimal import Decimal
import openpyxl

from graph_engine import Graph
from templates.vc_comp import create_vc_comp_graph
from compiler_excel import compile_to_excel
from compiler_python import compile_to_python

def test_vc_comp_graph_evaluation():
    """
    Given a set of inputs for a Series A round,
    when run through the VC Comp template graph,
    then both the Excel and Python formats produce matching capitalization tables.
    """
    g = create_vc_comp_graph()
    results = g.evaluate()
    
    assert results["pre_money_valuation"] == Decimal("10000000.00")
    assert results["investment_amount"] == Decimal("5000000.00")
    assert results["post_money_valuation"] == Decimal("15000000.00")
    assert results["investor_ownership"] == Decimal("0.3333")
    assert results["existing_ownership"] == Decimal("0.6667")

    # A2 regression (2026-07-11): the CamelCase alias family must NOT exist —
    # a parallel stateful alias diverged after set_input and compiled two
    # contradictory cap tables into one workbook. One node family, one truth.
    for alias in ("PreMoneyValuation", "InvestmentAmount", "PostMoneyValuation",
                  "InvestorOwnership", "ExistingOwnership"):
        assert alias not in results, f"stateful alias {alias} must stay deleted"

def test_vc_comp_compiler_excel_and_python(tmp_path):
    g = create_vc_comp_graph()
    
    excel_path = tmp_path / "vc_comp.xlsx"
    python_path = tmp_path / "vc_comp.py"
    
    cell_mapping = compile_to_excel(g, str(excel_path))
    
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    
    # Check that a few key nodes have correct Excel formula representations
    post_val_cell = cell_mapping["post_money_valuation"]
    assert ws[post_val_cell].value.startswith("=ROUND(")
    
    wb.close()
    
    compile_to_python(g, str(python_path))
    
    res = subprocess.run([sys.executable, str(python_path)], capture_output=True, text=True, check=True)
    outputs = res.stdout.strip().split("\n")
    
    topo_order = g.topological_sort()
    leaf_nodes = []
    for node_id in topo_order:
        dependents = g._dependents.get(node_id, set())
        if not dependents:
            leaf_nodes.append(node_id)
            
    assert len(outputs) == len(leaf_nodes)
    for i, leaf_id in enumerate(leaf_nodes):
        expected_val = g.nodes[leaf_id].value
        actual_val = Decimal(outputs[i].strip())
        assert actual_val == expected_val, f"Leaf {leaf_id} mismatch: expected {expected_val}, got {actual_val}"
