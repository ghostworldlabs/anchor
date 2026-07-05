#!/usr/bin/env python3
"""Anchor reaper — the ONE canonical liveness/ownership surface (stdlib only).

Wave 1 of the *zombie-hunter → safe-to-arm* build. This module collapses the
five historically-drifted orphan discriminators (the ``/api/rnd/orphan_check``
banner, the Swarm & Owner View freeze, the ``zombie_terminal_start`` brief, the
armed kill-daemon's ``live_ids`` provider, and the boot reconcile) onto ONE
import surface fed by ONE immutable per-sweep snapshot. Every later safety
property (abstain-not-kill, bounded blast radius, restart-durable freeze, the
arming ladder) leans on this structural foundation: if two call sites can
classify the same session against different/narrower inputs, no downstream
safety proof holds.

────────────────────────────────────────────────────────────────────────────
OWNER-ENUMERATION CONTRACT (the load-bearing definition — criterion 15)
────────────────────────────────────────────────────────────────────────────
A registered-RUNNING session is a true orphan ONLY if it is identity-alive AND
has **no live owner**. Being attached to a PTY/browser stream is just ONE kind
of owner. The canonical live-owner set is::

    live_owner_ids(snapshot) = attached_pty_ids
                             ∪ job_owned_ids
                             ∪ transitive-parent-owned_ids

where

  • ``attached_pty_ids``   — sessions with a live PTY/browser stream
                             (``pty_manager.live_sessions()``).
  • ``job_owned_ids``      — sessions backed by an actively-running OWNING job
                             (``job_runner._holder_is_active`` — the session_id
                             IS the job_id for a swarm/lane job).
  • parent-owned (transitive) — a session whose ``parent_session_id`` chain
                             reaches a live owner is itself owned. Walked to a
                             fixpoint over the immutable snapshot.

Ownership is enumerated from the **launch-time identity the registry recorded**
(session records + their owning jobs + the ``parent_session_id`` lineage),
NEVER from live OS parentage. So a backend PID re-parented to PID 1 after its
launcher exited stays owned as long as its owning job / a live parent still
claims it — a session is never orphaned *merely because its OS parent exited*.

INVARIANTS enforced in code:

  1. The snapshot is built EXACTLY ONCE per sweep (:func:`build_snapshot`) and is
     immutable (a frozen dataclass over frozensets + read-only mappings).
  2. :func:`live_owner_ids` is a PURE function of the snapshot — no self-sourcing,
     no I/O, rebuilt fresh each sweep so no drift carries across sweeps.
  3. :func:`classify` takes the live-owner set AND the positive-liveness map as
     its ONLY inputs (both REQUIRED positional args): a new consumer is
     compile-forced to supply them, so it cannot silently classify against a
     narrower input set.

The line is **live owner**, never "effort-bound": binding to an effort must NOT
neuter the hunter. A genuinely-orphaned swarm (identity-alive, no live owner)
still classifies ``kill``.

Stdlib only. No third-party imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

import proc_probe
import session_registry


# ── Verdict taxonomy (re-exported so callers depend on ONE source) ──────────
VERDICT_SKIP = "skip"
VERDICT_ABSTAIN = "abstain"
VERDICT_REAP_DEAD = "reap_dead"
VERDICT_REAP_RECYCLED = "reap_recycled"
VERDICT_ALIVE = "alive"
VERDICT_KILL = "kill"

#: Sentinel for :func:`build_snapshot`'s ``probe`` argument meaning "do NOT probe
#: PID identity for this snapshot" — used by the ownership-only callers (e.g.
#: :func:`zombie_hunter.live_owner_ids`) that never consult positive-liveness.
NO_PROBE = object()


# ── Positive-liveness signals (per session) ─────────────────────────────────

@dataclass(frozen=True)
class PositiveSignals:
    """Per-session liveness signals sampled ONCE when the snapshot is built.

    Wave 1 carries only the identity-probe outcome — the LIVE creation time of
    the session's owning PID (``None`` when the PID no longer resolves to an
    accessible process). Wave 2 enriches this with corroborated positive signals
    (git ``index.lock`` presence, session heartbeat, owned-socket probe,
    worktree write mtime, a CPU sample), each gated on owning-PID-alive
    corroboration. The field set is intentionally forward-compatible.
    """

    owner_pid: Optional[int] = None
    #: The owning PID's live creation time (epoch seconds). ``None`` ⇒ the PID
    #: has no accessible live process (gone / exited / access-denied).
    owner_create_time: Optional[float] = None


# ── The immutable per-sweep snapshot ────────────────────────────────────────

@dataclass(frozen=True)
class LivenessSnapshot:
    """The ONE immutable input every reaper decision is derived from.

    Built EXACTLY ONCE per sweep by :func:`build_snapshot`. Frozen: attributes
    cannot be reassigned, the id-sets are ``frozenset``, and the maps are
    ``MappingProxyType`` (read-only) — so a decision can never mutate the
    snapshot, and two sweeps never share drifting state.
    """

    #: Sessions with a live PTY/browser stream.
    attached_pty_ids: frozenset = field(default_factory=frozenset)
    #: Sessions backed by an actively-running owning job.
    job_owned_ids: frozenset = field(default_factory=frozenset)
    #: Sessions transitively owned via their ``parent_session_id`` lineage.
    parent_owned_ids: frozenset = field(default_factory=frozenset)
    #: pid → (pid, create_time, image_path) — the launch-time identity tuples.
    pid_identity: Mapping[int, Tuple[int, Optional[float], Optional[str]]] = \
        field(default_factory=lambda: MappingProxyType({}))
    #: session_id → :class:`PositiveSignals` sampled once for this sweep.
    positive_liveness: Mapping[str, PositiveSignals] = \
        field(default_factory=lambda: MappingProxyType({}))


def build_snapshot(attached_pty_ids=None, records=None, job_active=None,
                   probe=None) -> LivenessSnapshot:
    """Build the immutable per-sweep :class:`LivenessSnapshot` — call ONCE/sweep.

    ``attached_pty_ids`` — the base set of sessions with a live PTY/browser
                           stream; defaults to ``pty_manager.live_sessions()``.
    ``records``          — the RUNNING session records to consider; defaults to
                           ``session_registry.list_sessions(status="running")``.
    ``job_active``       — callable ``session_id -> bool`` reporting whether an
                           actively-running OWNING job backs the session;
                           defaults to ``job_runner._holder_is_active``.
    ``probe``            — supplies ``creation_time(pid)`` for the identity /
                           positive-liveness sampling; defaults to
                           :mod:`proc_probe`. Pass :data:`NO_PROBE` to skip the
                           per-PID probe entirely (ownership-only callers).

    Best-effort: any probe/import failure degrades to "not owned via that path"
    / "identity unknown", never raises.
    """
    # ── attached ────────────────────────────────────────────────────────────
    if attached_pty_ids is None:
        try:
            import pty_manager
            attached_pty_ids = set(pty_manager.live_sessions())
        except Exception:
            attached_pty_ids = set()
    attached = set(attached_pty_ids or ())

    # ── owning-job predicate ─────────────────────────────────────────────────
    if job_active is None:
        try:
            import job_runner
            job_active = job_runner._holder_is_active
        except Exception:  # pragma: no cover - defensive against an import cycle
            job_active = lambda _sid: False

    # ── the RUNNING records for this sweep ───────────────────────────────────
    if records is None:
        try:
            records = session_registry.list_sessions(status="running")
        except Exception:
            records = []

    by_id = {}
    job_owned = set()
    for rec in records or []:
        sid = rec.get("session_id")
        if not sid:
            continue
        by_id[sid] = rec
        if sid in attached:
            continue
        try:
            if job_active(sid):
                job_owned.add(sid)
        except Exception:  # pragma: no cover - a probe failure is "not owned"
            pass

    # ── transitive parent-owned closure from (attached ∪ job_owned) ──────────
    # Iterate to a fixpoint (bounded by the record count — small). Rebuilt fresh
    # every sweep; never incrementally mutated across sweeps.
    seeded = set(attached) | job_owned
    parent_owned = set()
    changed = True
    while changed:
        changed = False
        for sid, rec in by_id.items():
            if sid in seeded or sid in parent_owned:
                continue
            parent = rec.get("parent_session_id")
            if parent and (parent in seeded or parent in parent_owned):
                parent_owned.add(sid)
                changed = True

    # ── identity tuples + positive-liveness (probe each PID ONCE) ────────────
    pid_identity = {}
    positive = {}
    do_probe = probe is not NO_PROBE
    if do_probe and probe is None:
        probe = proc_probe
    if do_probe:
        for sid, rec in by_id.items():
            pid = rec.get("pid")
            if not pid:
                continue
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            try:
                actual = probe.creation_time(pid_int)
            except Exception:
                actual = None
            pid_identity[pid_int] = (pid_int, actual, None)
            positive[sid] = PositiveSignals(owner_pid=pid_int,
                                            owner_create_time=actual)

    return LivenessSnapshot(
        attached_pty_ids=frozenset(attached),
        job_owned_ids=frozenset(job_owned),
        parent_owned_ids=frozenset(parent_owned),
        pid_identity=MappingProxyType(dict(pid_identity)),
        positive_liveness=MappingProxyType(dict(positive)),
    )


# ── Pure derivations over the immutable snapshot ────────────────────────────

def live_owner_ids(snapshot) -> set:
    """The canonical live-owner set — a PURE function of ``snapshot``.

    Returns ``attached_pty_ids ∪ job_owned_ids ∪ transitive-parent-owned`` as a
    NEW set each call. No self-sourcing, no I/O: it only reads the immutable
    snapshot, so two sweeps over the same registry state yield equal sets with
    no drift carried across sweeps.
    """
    return (set(snapshot.attached_pty_ids)
            | set(snapshot.job_owned_ids)
            | set(snapshot.parent_owned_ids))


def live_pid_ids(snapshot) -> set:
    """Sessions whose recorded PID resolves to a LIVE process (identity present).

    This is process-liveness, NOT ownership: a session is "PID-alive" whenever
    its owning PID currently hosts an accessible process — whether it is genuine
    work OR a true orphan the banner/daemon handle. The boot reconcile uses this
    to leave PID-alive records RUNNING and reconcile only dead PIDs, so it never
    silently reaps an orphan at startup.
    """
    return {sid for sid, sig in snapshot.positive_liveness.items()
            if sig is not None and sig.owner_create_time is not None}


def classify(record, live_owner_ids, positive_liveness, *, tol=2.0) -> str:
    """Pure verdict for one ``record`` — the ONLY inputs are the live-owner set
    and the positive-liveness map (both REQUIRED positional args).

    A new consumer is compile-forced to supply both, so it cannot classify a
    session against a narrower input set than every other call site.

    Verdicts:
      - ``"skip"``          — record is not RUNNING; not our concern.
      - ``"abstain"``       — missing identity (no token / pid / create-time):
                              NEVER kill, NEVER auto-reap; flag for review.
      - ``"reap_dead"``     — the recorded PID has no live process (identity
                              absent from the positive-liveness map): gone
                              already, reconcile the registry only (no kill).
      - ``"reap_recycled"`` — the PID is live but its creation time differs: the
                              PID was reused by a DIFFERENT process; reconcile,
                              NEVER kill the new owner.
      - ``"alive"``         — our process, still running, and OWNED: leave it.
      - ``"kill"``          — our process, still running, and NO live owner →
                              orphan → kill + reap.
    """
    if record.get("status") != session_registry.STATUS_RUNNING:
        return VERDICT_SKIP

    pid = record.get("pid")
    ctime = record.get("proc_create_time")
    token = record.get("crypt_token")

    # Missing identity → never killable / never auto-reapable.
    if not token or not pid or ctime is None:
        return VERDICT_ABSTAIN

    sid = record.get("session_id")
    signals = positive_liveness.get(sid) if positive_liveness else None
    actual = signals.owner_create_time if signals is not None else None
    if actual is None:
        # No live process for this PID — reconcile only (no kill).
        return VERDICT_REAP_DEAD
    if abs(actual - ctime) > tol:
        # PID recycled by a different process — never kill the new owner.
        return VERDICT_REAP_RECYCLED

    owners = live_owner_ids if live_owner_ids is not None else ()
    if sid in owners:
        return VERDICT_ALIVE
    return VERDICT_KILL


def classify_record(record, snapshot, *, tol=2.0) -> str:
    """The single classify entry every call site uses.

    Classifies one ``record`` against the immutable ``snapshot`` — its live-owner
    set AND its positive-liveness map — so all five discriminators share the
    identical provider. Bypassing this (hand-rolling :func:`classify` args, or
    reaching back into the old per-site input set) is what the Wave-1 stub-gate
    is designed to catch.
    """
    return classify(record, live_owner_ids(snapshot), snapshot.positive_liveness,
                    tol=tol)
