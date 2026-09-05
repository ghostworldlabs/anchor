"""ChatGPT as a first-class Terminal engine (John, 2026-09-05) — the gate file for the build.

Wave 1 of planning/chatgpt-terminal-2026-09-05 extends this file with the real proofs
(stub-PTY start_session on backend chatgpt, the seed written once, the argv, the engine
switch, the capability matrix). This seed test is true today and stays true: the backend
name exists in the registry.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import session_registry as _reg  # noqa: E402


def test_chatgpt_backend_is_a_registry_backend():
    assert _reg.BACKEND_CHATGPT == "chatgpt"
    assert _reg.BACKEND_CHATGPT in _reg.VALID_BACKENDS
