import os
import sys
import subprocess
import pytest
from decimal import Decimal
import openpyxl

from graph_engine import Graph
from templates.re_waterfall import create_waterfall_graph
from compiler_excel import compile_to_excel
from compiler_python import compile_to_python

def test_waterfall_graph_evaluation():
    """
    Given a 5-year waterfall with preferred return hurdles,
    when run through the Graph engine,
    then LP/GP distributions and ending balances evaluate correctly.
    """
    g = create_waterfall_graph()
    results = g.evaluate()
    
    # Assert initial contribution calculations
    assert results["lp_contribution"] == Decimal("900000.00")
    assert results["gp_contribution"] == Decimal("100000.00")
    
    # Assert Year 1 values
    assert results["lp_beg_bal_8_1"] == Decimal("900000.00")
    assert results["lp_pref_8_1"] == Decimal("72000.00")
    assert results["lp_target_8_1"] == Decimal("972000.00")
    assert results["total_dist_1_1"] == Decimal("120000.00")
    assert results["lp_dist_1_1"] == Decimal("108000.00")
    assert results["gp_dist_1_1"] == Decimal("120000.00") - Decimal("108000.00")
    assert results["lp_end_bal_8_1"] == Decimal("864000.00")
    assert results["lp_end_bal_12_1"] == Decimal("900000.00")
    
    # Assert Year 5 (liquidation / final hurdle cleared)
    assert results["lp_end_bal_8_5"] == Decimal("0.00")
    assert results["lp_end_bal_12_5"] == Decimal("0.00")
    
    # Assert Year 5 distributions
    assert results["lp_total_dist_5"] == Decimal("911391.33")
    assert results["gp_total_dist_5"] == Decimal("288608.67")
    assert results["total_dist_5"] == Decimal("1200000.00")

def test_waterfall_compiler_excel_and_python(tmp_path):
    """
    Given the waterfall graph,
    when compiled to Excel and Standalone Python,
    then the Excel cell formulas are written correctly,
    and the compiled Python script executes and outputs matching values.
    """
    g = create_waterfall_graph()
    
    # Compile targets
    excel_path = tmp_path / "waterfall.xlsx"
    python_path = tmp_path / "waterfall.py"
    
    # Compile to Excel (using auto-assigned cells or default)
    cell_mapping = compile_to_excel(g, str(excel_path))
    
    # Verify Excel file exists and contains formulas
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    
    # Check that a few key nodes have correct Excel formula representations
    lp_contrib_cell = cell_mapping["lp_contribution"]
    assert ws[lp_contrib_cell].value.startswith("=ROUND(")
    
    lp_target_8_1_cell = cell_mapping["lp_target_8_1"]
    assert ws[lp_target_8_1_cell].value.startswith("=ROUND(")
    
    total_dist_1_1_cell = cell_mapping["total_dist_1_1"]
    assert ws[total_dist_1_1_cell].value.startswith("=MIN(")
    
    wb.close()
    
    # Compile to Standalone Python
    compile_to_python(g, str(python_path))
    
    # Execute the standalone Python script and capture printed leaf node values
    res = subprocess.run([sys.executable, str(python_path)], capture_output=True, text=True, check=True)
    outputs = res.stdout.strip().split("\n")
    
    # Obtain the evaluated leaf node values from Python
    # Since compile_to_python prints leaf nodes, we verify they match the graph's evaluate results.
    # We sort leaf nodes the same way they were written by compile_to_python.
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
