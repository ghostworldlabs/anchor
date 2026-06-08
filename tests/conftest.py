"""pytest configuration for the Anchor test suite.

Ensures the repository root is importable so tests can `import anchor`
(the stdlib-only CLI engine) regardless of the working directory pytest
is invoked from.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
