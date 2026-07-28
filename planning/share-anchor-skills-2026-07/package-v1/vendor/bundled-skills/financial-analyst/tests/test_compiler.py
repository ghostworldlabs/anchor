import os
import sys
import subprocess
import pytest
from decimal import Decimal
import openpyxl

from graph_engine import Graph, InputNode, FormulaNode
from compiler_excel import compile_to_excel
from compiler_python import compile_to_python, compile_to_python_source

def test_wave3_compiler_done_when(tmp_path):
    """
    Given the simple A+B=C DAG,
    when compiled to Excel and standalone Python,
    then the generated Python script outputs 15.00,
    and the Excel file computes 15.00 in cell C1 using =A1+B1.
    """
    # 1. Construct the simple A+B=C DAG
    g = Graph()
    g.add_node(InputNode("A", 10.00))
    g.add_node(InputNode("B", 5.00))
    g.add_node(FormulaNode("C", lambda x, y: x + y, depends_on=["A", "B"], formula_str="A + B"))

    # Paths for compilation output
    excel_path = tmp_path / "compiled_graph.xlsx"
    python_path = tmp_path / "compiled_graph.py"

    # 2. Compile to Excel (using cell mapping A->A1, B->B1, C->C1)
    cell_mapping = {"A": "A1", "B": "B1", "C": "C1"}
    final_mapping = compile_to_excel(g, str(excel_path), cell_mapping=cell_mapping)

    assert final_mapping["A"] == "A1"
    assert final_mapping["B"] == "B1"
    assert final_mapping["C"] == "C1"

    # Verify compiled Excel file structure and values
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    assert ws["A1"].value == 10.0
    assert ws["B1"].value == 5.0
    assert ws["C1"].value == "=A1 + B1"
    wb.close()

    # 3. Compile to Standalone Python
    compile_to_python(g, str(python_path))

    # Verify generated Python code contains Decimal imports and correct formula
    with open(python_path, "r") as f:
        py_content = f.read()

    assert "from decimal import Decimal" in py_content
    assert "A = Decimal('10.0')" in py_content or "A = Decimal('10.00')" in py_content or "A = Decimal('10')" in py_content
    assert "B = Decimal('5.0')" in py_content or "B = Decimal('5.00')" in py_content or "B = Decimal('5')" in py_content
    assert "C = A + B" in py_content
    assert "print(C)" in py_content

    # Execute standalone Python script and assert stdout is 15.00
    res = subprocess.run([sys.executable, str(python_path)], capture_output=True, text=True, check=True)
    assert res.stdout.strip() in ("15.0", "15.00")


def test_compiler_custom_mapping(tmp_path):
    """
    Given a DAG with custom cell mapping coordinates,
    when compiled to Excel,
    then the Excel formulas reference the mapped cells correctly.
    """
    g = Graph()
    g.add_node(InputNode("A", 10.00))
    g.add_node(InputNode("B", 5.00))
    g.add_node(FormulaNode("C", lambda x, y: x + y, depends_on=["A", "B"], formula_str="A + B"))

    excel_path = tmp_path / "custom_mapped.xlsx"
    cell_mapping = {"A": "B2", "B": "C3", "C": "D4"}
    compile_to_excel(g, str(excel_path), cell_mapping=cell_mapping)

    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    assert ws["B2"].value == 10.0
    assert ws["C3"].value == 5.0
    assert ws["D4"].value == "=B2 + C3"
    wb.close()


def test_compiler_excel_string_literals(tmp_path):
    """
    Verifies that string literals in formula strings are not replaced by cell mapping.
    """
    g = Graph()
    g.add_node(InputNode("A", 10.00))
    g.add_node(FormulaNode("C", lambda x: "YES" if x > 5 else "NO", depends_on=["A"], formula_str='IF(A > 5, "YES", "NO")'))

    excel_path = tmp_path / "string_literal.xlsx"
    cell_mapping = {"A": "A1", "C": "B1"}
    compile_to_excel(g, str(excel_path), cell_mapping=cell_mapping)

    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    assert ws["B1"].value == '=IF(A1 > 5, "YES", "NO")'
    wb.close()
