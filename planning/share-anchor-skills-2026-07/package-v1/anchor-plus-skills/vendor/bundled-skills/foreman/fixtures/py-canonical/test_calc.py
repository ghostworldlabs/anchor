# test_calc.py — the Python canonical fixture's pytest suite (the ground-truth
# gate). Run with: python -m pytest -v  (declared in the plan).
#
# It imports `calc` (an absolute project import) so the vacuous-GREEN coverage
# proxy can prove `calc.py` is reachable from an executed test.
from calc import add, subtract, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(4, 5) == 20


# This is the test the planted bug breaks. It is RED in the shipped fixture and
# turns GREEN once `subtract` is fixed to `a - b`.
def test_subtract():
    assert subtract(7, 3) == 4
