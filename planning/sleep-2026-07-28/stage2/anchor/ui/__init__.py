"""UI primitives for the v1.2 honesty surface (NamedState render path)."""
from __future__ import annotations

from anchor.ui.named_state import (
    BINDING_EMPTY,
    BINDING_PENDING,
    BINDING_UNKNOWN,
    BINDING_ZERO_MEASURED,
    FAILURE_STATE_TABLE,
    NAMED_STATE_COUNT,
    NamedState,
    generate_html,
    render_state,
    validate_failure_state_table,
)

__all__ = [
    "BINDING_EMPTY",
    "BINDING_PENDING",
    "BINDING_UNKNOWN",
    "BINDING_ZERO_MEASURED",
    "FAILURE_STATE_TABLE",
    "NAMED_STATE_COUNT",
    "NamedState",
    "generate_html",
    "render_state",
    "validate_failure_state_table",
]
