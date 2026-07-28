import os
import tempfile
import pytest
from decimal import Decimal

from agent_interface import create_agent, FinancialAnalystAgent

def test_agent_interface_vc_comp(tmp_path):
    """
    Given the evaluated VC Comp graph,
    when passed to the report generator/agent interface,
    then the output contains citations like [Node: PostMoneyValuation] or [Node: post_money_valuation].
    """
    agent = create_agent()
    
    # Load VC Comp template
    g = agent.load_template("vc_comp")
    
    # Assert initial values
    assert agent.get_value("pre_money_valuation") == Decimal("10000000.00")
    assert agent.get_value("investment_amount") == Decimal("5000000.00")
    assert agent.get_value("post_money_valuation") == Decimal("15000000.00")
    assert agent.get_value("investor_ownership") == Decimal("0.3333")

    # A2 regression (2026-07-11): the CamelCase alias family is GONE. A parallel
    # stateful alias diverged silently after set_input and compiled BOTH families
    # into one workbook (two contradictory cap tables). Alias lookups must fail
    # loudly, never return a stale shadow value.
    with pytest.raises(Exception):
        agent.get_value("PostMoneyValuation")
    with pytest.raises(Exception):
        agent.set_input("PreMoneyValuation", 1.0)

    # Update input pre-money valuation — ONE name, one truth.
    agent.set_input("pre_money_valuation", 20000000.00)

    assert agent.get_value("pre_money_valuation") == Decimal("20000000.00")
    assert agent.get_value("post_money_valuation") == Decimal("25000000.00")
    assert agent.get_value("investor_ownership") == Decimal("0.2000")
    
    # Generate Markdown Report
    report = agent.generate_report()
    assert "[Node: post_money_valuation]" in report or "[Node: PostMoneyValuation]" in report
    assert "[Node: pre_money_valuation]" in report or "[Node: PreMoneyValuation]" in report
    assert "[Node: investment_amount]" in report or "[Node: InvestmentAmount]" in report
    
    # Generate PDF Report
    pdf_path = tmp_path / "vc_report.pdf"
    agent.generate_pdf_report(str(pdf_path))
    assert os.path.exists(pdf_path)
    
    # Generate Prompt
    prompt = agent.generate_prompt()
    assert "SYSTEM INSTRUCTIONS" in prompt
    assert "25000000.00" in prompt
    
    # Compile Excel
    excel_path = tmp_path / "agent_vc.xlsx"
    cell_mapping = agent.compile_excel(str(excel_path))
    assert "post_money_valuation" in cell_mapping or "PostMoneyValuation" in cell_mapping
    assert os.path.exists(excel_path)
    
    # Compile Python
    py_path = tmp_path / "agent_vc.py"
    agent.compile_python(str(py_path))
    assert os.path.exists(py_path)


def test_agent_interface_waterfall(tmp_path):
    """
    Verify agent interface with the waterfall template.
    """
    agent = create_agent()
    
    # Load Waterfall template
    agent.load_template("re_waterfall")
    
    # Verify initial evaluations
    assert agent.get_value("lp_contribution") == Decimal("900000.00")
    assert agent.get_value("gp_contribution") == Decimal("100000.00")
    
    # Update initial equity
    agent.set_input("initial_equity", 2000000.00)
    assert agent.get_value("lp_contribution") == Decimal("1800000.00")
    assert agent.get_value("gp_contribution") == Decimal("200000.00")
    
    # Generate Report
    report = agent.generate_report()
    assert "[Node: initial_equity]" in report
    assert "[Node: lp_contribution]" in report
    
    # Generate PDF Report
    pdf_path = tmp_path / "waterfall_report.pdf"
    agent.generate_pdf_report(str(pdf_path))
    assert os.path.exists(pdf_path)
