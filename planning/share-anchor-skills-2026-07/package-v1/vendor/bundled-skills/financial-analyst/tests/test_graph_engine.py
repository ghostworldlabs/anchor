import pytest
from decimal import Decimal
from graph_engine import Graph, InputNode, FormulaNode, Node

def test_wave2_done_when():
    """
    Given a graph with nodes A=10.00, B=5.00, and C=A+B,
    when the graph is evaluated,
    then Node C exactly equals 15.00.
    """
    g = Graph()
    a = g.add_node(InputNode("A", 10.00))
    b = g.add_node(InputNode("B", 5.00))
    c = g.add_node(FormulaNode("C", lambda x, y: x + y, depends_on=["A", "B"]))

    results = g.evaluate()
    assert results["C"] == Decimal("15.00")
    assert isinstance(results["C"], Decimal)
    assert g.evaluate_node("C") == Decimal("15.00")


def test_graph_free_evaluation():
    """
    Verifies that nodes linked directly as Node objects can be evaluated without a Graph context.
    """
    a = InputNode("A", "10.00")
    b = InputNode("B", "5.00")
    c = FormulaNode("C", lambda x, y: x + y, depends_on=[a, b])
    
    val_c = c.evaluate()
    assert val_c == Decimal("15.00")
    assert isinstance(val_c, Decimal)


def test_cache_invalidation():
    """
    Verifies that changing an InputNode's value invalidates the cache of downstream FormulaNodes.
    """
    g = Graph()
    a = g.add_node(InputNode("A", 10.00))
    b = g.add_node(InputNode("B", 5.00))
    c = g.add_node(FormulaNode("C", lambda x, y: x + y, depends_on=["A", "B"]))
    
    assert g.evaluate_node("C") == Decimal("15.00")
    
    # Update input A
    g.set_input("A", 20.00)
    assert g.evaluate_node("C") == Decimal("25.00")


def test_cycle_detection():
    """
    Verifies that cycle detection raises ValueError.
    """
    g = Graph()
    # A depends on B, B depends on A
    g.add_node(FormulaNode("A", lambda b: b, depends_on=["B"]))
    g.add_node(FormulaNode("B", lambda a: a, depends_on=["A"]))
    
    with pytest.raises(ValueError, match="Cycle detected"):
        g.evaluate()

    with pytest.raises(ValueError, match="Cycle detected"):
        g.topological_sort()


def test_topological_sort():
    """
    Verifies topological sorting of nodes.
    """
    g = Graph()
    g.add_node(InputNode("A", 1))
    g.add_node(FormulaNode("C", lambda a, b: a + b, depends_on=["A", "B"]))
    g.add_node(InputNode("B", 2))
    
    sort_order = g.topological_sort()
    # "A" and "B" must appear before "C"
    assert sort_order.index("A") < sort_order.index("C")
    assert sort_order.index("B") < sort_order.index("C")


def test_boolean_and_types():
    """
    Verifies booleans and non-decimal values are handled and not coerced to Decimals incorrectly.
    """
    g = Graph()
    g.add_node(InputNode("Condition", True))
    g.add_node(InputNode("Text", "hello"))
    
    results = g.evaluate()
    assert results["Condition"] is True
    assert results["Text"] == "hello"
