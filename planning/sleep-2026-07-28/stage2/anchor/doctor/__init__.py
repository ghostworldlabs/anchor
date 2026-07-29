"""Doctor package — real diagnose + banner issue-payload handoff (W14).

Re-exports the ``diagnose`` and ``banner_handoff`` *submodules* (not the
``diagnose`` function of the same name). Callers that need the callable use
``diagnose.diagnose`` or ``from anchor.doctor.diagnose import diagnose``.
Binding the function on this package under that name would shadow the module
and break ``from anchor.doctor import diagnose`` → ``.WAVE_ID``.
"""
from __future__ import annotations

from . import banner_handoff, diagnose
from .banner_handoff import (
    IssuePayload,
    RedetectionForbidden,
    banner_issue_payload,
    doctor_entry,
    issue_payload_hash,
)
from .diagnose import (
    CONTRACT_FAULTS,
    DiagnosisResult,
    Finding,
    Reading,
    SystemState,
    force_fault,
    healthy_system,
    parse_fault_contracts,
    take_readings,
)

__all__ = [
    "banner_handoff",
    "diagnose",
    "CONTRACT_FAULTS",
    "DiagnosisResult",
    "Finding",
    "IssuePayload",
    "Reading",
    "RedetectionForbidden",
    "SystemState",
    "banner_issue_payload",
    "doctor_entry",
    "force_fault",
    "healthy_system",
    "issue_payload_hash",
    "parse_fault_contracts",
    "take_readings",
]
