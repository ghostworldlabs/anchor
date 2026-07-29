"""Session open / run / attach entry points (W10+).

Re-exports the ``open_work`` / ``run_work`` / ``attach`` *submodules* (not
the functions of the same name). Callers that need the callable use
``open_work.open_work`` or ``from anchor.session.open_work import open_work``.
Binding the functions on this package under those names would shadow the
modules and break ``from anchor.session import open_work`` → ``.OPEN_REASONS``.
"""
from __future__ import annotations

from . import attach, open_work, run_work
from .attach import (
    ATTACH_REASONS,
    AttachReason,
    AttachedSession,
    CannotAttach,
    CannotRetry,
    RetryAction,
)
from .open_work import (
    OPEN_REASONS,
    CannotOpen,
    OpenReason,
    OpenedWork,
)
from .run_work import (
    RUN_REASONS,
    CannotRun,
    LiveRunHandle,
    RunReason,
)

__all__ = [
    "open_work",
    "run_work",
    "attach",
    "OPEN_REASONS",
    "CannotOpen",
    "OpenReason",
    "OpenedWork",
    "RUN_REASONS",
    "CannotRun",
    "LiveRunHandle",
    "RunReason",
    "ATTACH_REASONS",
    "AttachReason",
    "AttachedSession",
    "CannotAttach",
    "CannotRetry",
    "RetryAction",
]
