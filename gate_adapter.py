#!/usr/bin/env python3
"""Anchor gate adapter — in-session answers to skill gates (Wave 5).

The keystone gate mechanism (MASTER-PLAN.md D2 + "Gate adapter" bullet +
Spike-0): a skill's ``AskUserQuestion`` tool_use **surfaces in the stream-json
output** even though it auto-dismisses headless. Anchor parses that frame into a
prompt-box record, persists ``state=awaiting-input`` onto the job record so a
reattaching client (incl. over Tailscale) can load the pending question, and
answers it by sending the user's choice as a **single plain text turn** into the
running session's stdin — which continues the session.

Frozen requirements satisfied here:
- Parse a stream-json line/stream → detect an ``AskUserQuestion`` tool_use →
  produce a prompt-box record ``{question, options, tool_use_id}`` (carrying
  enough to render: question text, option labels/descriptions, multiSelect).
- Persist the awaiting-input state onto the job record under
  ``paths.WRITE_LOCK`` (``state`` field + ``pending_prompt``) so a fresh client
  can reattach and answer.
- ``answer(job_or_tool_use_id, choice)`` writes a SINGLE stdin text turn to the
  running session and is **single-consumer**: two concurrent answers for one
  ``tool_use_id`` produce exactly ONE stdin write; the second is a no-op. This is
  enforced with the write-lock + a ``gate_consumed`` marker on the record.

The actual stdin write goes to the job's process stdin (owned by
``job_runner``). To keep ``job_runner``'s Wave-4 launch contract untouched (its
``Popen`` is created with ``stdin=DEVNULL``), the destination is resolved
through a small **stdin-sink registry**: production code registers the live
process's ``stdin`` (a writable file object); tests register a fake sink. Live
``claude`` is NEVER invoked here.

Stdlib only. No third-party imports.
"""

import json
import threading
import time

import paths as _paths
import job_runner as _jr

# ── Constants ──────────────────────────────────────────────────────────────

#: Job state when a gate question is pending an answer.
STATE_AWAITING_INPUT = "awaiting-input"

#: Tool name that denotes a Claude Code gate (the AskUserQuestion tool).
ASK_TOOL_NAME = "AskUserQuestion"

# ── Stdin-sink registry ─────────────────────────────────────────────────────
# Maps job_id -> a writable sink (the running session's process stdin in
# production, or a fake sink object in tests). A sink only needs ``write`` +
# ``flush``. Kept out of job_runner so the Wave-4 launch contract is unchanged.
_SINKS = {}
_SINKS_LOCK = threading.RLock()


def register_stdin_sink(job_id: str, sink) -> None:
    """Register the writable stdin sink for a job.

    ``sink`` is any object exposing ``write(str)`` and ``flush()`` — in
    production the live subprocess's ``stdin``; in tests a fake sink.
    """
    with _SINKS_LOCK:
        _SINKS[job_id] = sink


def _get_stdin_sink(job_id: str):
    """Resolve the stdin sink for a job, falling back to the live process.

    Prefers an explicitly registered sink; otherwise tries the live job's
    process stdin (only present if the job was launched with a stdin pipe).
    Returns ``None`` if no writable destination is available.
    """
    with _SINKS_LOCK:
        sink = _SINKS.get(job_id)
    if sink is not None:
        return sink
    # Fall back to the live job's process stdin if it exposes one.
    with _jr._LIVE_LOCK:
        live = _jr._LIVE.get(job_id)
    if live is not None:
        stdin = getattr(live.proc, "stdin", None)
        if stdin is not None:
            return stdin
    return None


def _drop_stdin_sink(job_id: str) -> None:
    """Forget a job's sink (test/maintenance helper)."""
    with _SINKS_LOCK:
        _SINKS.pop(job_id, None)


# ── Parsing: stream-json AskUserQuestion → prompt-box record ─────────────────

def parse_event(event) -> list:
    """Parse one stream-json event (dict or JSON str) → prompt-box records.

    Returns a list of prompt-box records — one per question in the gate's
    ``input.questions`` array — for any ``AskUserQuestion`` ``tool_use`` block
    found in an assistant message. Non-gate events yield an empty list.

    A prompt-box record has the shape::

        {
          "tool_use_id": "toolu_...",   # the tool_use block id
          "question": "...",            # the question text
          "header": "...",              # short header (optional, may be "")
          "options": [                  # render-ready options
            {"label": "...", "description": "..."}, ...
          ],
          "multiSelect": false,
        }

    Multiple questions in a single gate frame share the one ``tool_use_id`` but
    are disambiguated by ``question_index``.
    """
    if isinstance(event, (str, bytes)):
        text = event.decode("utf-8") if isinstance(event, bytes) else event
        text = text.strip()
        if not text:
            return []
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return []
    if not isinstance(event, dict):
        return []
    if event.get("type") != "assistant":
        return []
    message = event.get("message") or {}
    content = message.get("content")
    if not isinstance(content, list):
        return []

    records = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        if block.get("name") != ASK_TOOL_NAME:
            continue
        tool_use_id = block.get("id")
        questions = ((block.get("input") or {}).get("questions")) or []
        for q_index, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            opts = []
            for opt in (q.get("options") or []):
                if isinstance(opt, dict):
                    opts.append({
                        "label": opt.get("label", ""),
                        "description": opt.get("description", ""),
                    })
                else:
                    opts.append({"label": str(opt), "description": ""})
            records.append({
                "tool_use_id": tool_use_id,
                "question_index": q_index,
                "question": q.get("question", ""),
                "header": q.get("header", ""),
                "options": opts,
                "multiSelect": bool(q.get("multiSelect", False)),
            })
    return records


def parse_stream(stream) -> list:
    """Parse an iterable of stream-json lines → all prompt-box records.

    ``stream`` may be a list of lines, a file object, or any iterable of
    newline-delimited JSON strings. Returns the flattened list of prompt-box
    records (usually 0 or 1 for a single gate).
    """
    out = []
    for line in stream:
        out.extend(parse_event(line))
    return out


def parse_stream_file(path) -> list:
    """Parse a stream-json ``.jsonl`` fixture file → prompt-box records."""
    from pathlib import Path
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        return parse_stream(fh)


def session_id_from_stream(stream) -> str:
    """Best-effort: pull the ``session_id`` from an init/system event."""
    for line in stream:
        if isinstance(line, (str, bytes)):
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            text = text.strip()
            if not text:
                continue
            try:
                ev = json.loads(text)
            except json.JSONDecodeError:
                continue
        elif isinstance(line, dict):
            ev = line
        else:
            continue
        if ev.get("session_id"):
            return ev["session_id"]
    return None


# ── Persisting awaiting-input onto the job record ────────────────────────────

def mark_awaiting_input(job_id: str, prompt: dict) -> dict:
    """Persist a pending gate prompt onto the job record under the write lock.

    Sets ``state`` -> ``awaiting-input`` and stores ``pending_prompt`` (the
    prompt-box record) plus a cleared ``gate_consumed`` marker so a reattaching
    client can load + answer it. The pre-existing runner ``status`` field is
    left untouched (the runner owns process lifecycle); ``state`` is the gate's
    own dimension. Returns the updated record.
    """
    with _paths.WRITE_LOCK:
        rec = _jr.load_record(job_id) or {"job_id": job_id}
        rec["state"] = STATE_AWAITING_INPUT
        rec["pending_prompt"] = prompt
        rec["gate_consumed"] = False
        _jr._write_record(rec)
        return rec


def ingest_stream(job_id: str, stream) -> dict:
    """Parse a stream + persist the first gate found onto the job record.

    Convenience for the launch/tail path: scans the stream for an
    ``AskUserQuestion`` gate; if one is found, persists awaiting-input and
    returns the prompt-box record; otherwise returns ``None``.
    """
    records = parse_stream(stream)
    if not records:
        return None
    prompt = records[0]
    mark_awaiting_input(job_id, prompt)
    return prompt


def load_pending_prompt(job_id: str):
    """Return the pending prompt-box record for a job, or ``None``.

    Used by a fresh/reattaching client (incl. over Tailscale) to load the
    question it must answer. Only returns a prompt while the gate is genuinely
    awaiting input and has not yet been consumed.
    """
    rec = _jr.load_record(job_id)
    if rec is None:
        return None
    if rec.get("state") != STATE_AWAITING_INPUT:
        return None
    if rec.get("gate_consumed"):
        return None
    # GATE-2: never surface an unanswerable prompt for a terminal job (the
    # session is gone, so the gate can no longer be answered). The gate ``state``
    # and runner ``status`` are orthogonal; this only guards the read path.
    if rec.get("status") in _jr.TERMINAL_STATUSES:
        return None
    return rec.get("pending_prompt")


def _find_job_id(job_id_or_tool_use_id: str):
    """Resolve either a job_id or a pending tool_use_id to a job_id.

    Lets a client answer by the ``tool_use_id`` it saw in the prompt box,
    matching the AC wording ("two concurrent answer POSTs for one tool_use_id").
    """
    # Direct job_id hit?
    if _jr.load_record(job_id_or_tool_use_id) is not None:
        return job_id_or_tool_use_id
    # Otherwise search for a record whose prompt carries this tool_use_id.
    # GATE-1: an ANSWERABLE match (gate state awaiting-input, not consumed,
    # runner status not terminal) always wins, and a consumed/terminal record
    # with the same tool_use_id must NOT shadow a fresh awaiting gate. On
    # multiple answerable matches, prefer the NEWEST (by started_at, falling back
    # to record mtime) so a fresh gate wins over an older one.
    #
    # If there is NO answerable match, fall back to the newest CONSUMED match
    # (looked up via the retired ``resolved_prompt``) purely so ``answer()`` can
    # report the benign "already-consumed" no-op for that tool_use_id rather than
    # an indistinguishable "unknown". The fallback can never shadow an answerable
    # gate because answerable matches take strict priority.
    best_job_id = None
    best_key = None
    consumed_job_id = None
    consumed_key = None
    for rec in _jr.list_records():
        cand_job_id = rec.get("job_id")
        active_prompt = rec.get("pending_prompt") or {}
        if (active_prompt.get("tool_use_id") == job_id_or_tool_use_id
                and rec.get("state") == STATE_AWAITING_INPUT
                and not rec.get("gate_consumed")
                and rec.get("status") not in _jr.TERMINAL_STATUSES):
            sort_key = _record_recency(rec, cand_job_id)
            if best_key is None or sort_key > best_key:
                best_key = sort_key
                best_job_id = cand_job_id
            continue
        # Track consumed/retired matches as a no-op-reporting fallback only.
        retired = rec.get("resolved_prompt") or active_prompt
        if retired.get("tool_use_id") == job_id_or_tool_use_id:
            sort_key = _record_recency(rec, cand_job_id)
            if consumed_key is None or sort_key > consumed_key:
                consumed_key = sort_key
                consumed_job_id = cand_job_id
    if best_job_id is not None:
        return best_job_id
    return consumed_job_id


def _record_recency(rec: dict, job_id) -> float:
    """Recency key for tie-breaking matches — ``started_at`` else record mtime.

    Larger means newer. Used so a fresh awaiting gate wins over an older one
    that happens to share the same tool_use_id.
    """
    started = rec.get("started_at")
    if isinstance(started, (int, float)):
        return float(started)
    try:
        return _jr._record_path(job_id).stat().st_mtime
    except (OSError, AttributeError, TypeError):
        return 0.0


# ── Answering: single-consumer stdin text turn ───────────────────────────────

def _format_turn(choice) -> str:
    """Render the user's choice as a single stdin text-turn payload.

    The continuation is a plain text turn (D2). We emit a stream-json
    user-message envelope terminated by a newline, which is what a long-lived
    ``--input-format stream-json`` session consumes. The exact envelope is not
    asserted by the gate; what matters is that exactly ONE turn is written.
    """
    if isinstance(choice, (list, tuple)):
        text = ", ".join(str(c) for c in choice)
    else:
        text = str(choice)
    envelope = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return json.dumps(envelope, ensure_ascii=False) + "\n"


class AnswerResult:
    """Outcome of an :func:`answer` call.

    ``written`` is True only for the single consumer that actually wrote the
    stdin turn; concurrent duplicates get ``written=False`` (no-oped).
    """

    __slots__ = ("written", "reason", "job_id")

    def __init__(self, written, reason, job_id=None):
        self.written = written
        self.reason = reason
        self.job_id = job_id

    def __repr__(self):
        return (f"AnswerResult(written={self.written!r}, "
                f"reason={self.reason!r}, job_id={self.job_id!r})")


def answer(job_id_or_tool_use_id: str, choice) -> AnswerResult:
    """Answer a pending gate by writing a SINGLE stdin text turn — once.

    Single-consumer guarantee (AC3): the consumed-marker check-and-set and the
    stdin write both happen **inside** ``paths.WRITE_LOCK``, so under concurrency
    exactly one caller observes ``gate_consumed == False``, performs the write,
    and flips the marker; every other concurrent caller sees the marker already
    set and no-ops. The job's ``state`` is advanced off ``awaiting-input`` so a
    reattaching client sees the gate resolved.

    Returns an :class:`AnswerResult`. ``written=True`` for the one consumer;
    ``written=False`` (with a ``reason``) for no-ops / unknown / not-awaiting.
    """
    with _paths.WRITE_LOCK:
        job_id = _find_job_id(job_id_or_tool_use_id)
        if job_id is None:
            return AnswerResult(False, "unknown", None)
        rec = _jr.load_record(job_id)
        if rec is None:
            return AnswerResult(False, "unknown", job_id)
        # GATE-2: a terminal job's session is gone — its gate is unanswerable
        # even if ``state`` still reads awaiting-input. No-op gracefully.
        if rec.get("status") in _jr.TERMINAL_STATUSES:
            return AnswerResult(False, "terminal", job_id)
        if rec.get("state") != STATE_AWAITING_INPUT:
            return AnswerResult(False, "not-awaiting", job_id)
        if rec.get("gate_consumed"):
            # A concurrent (or prior) answer already consumed this gate.
            return AnswerResult(False, "already-consumed", job_id)

        sink = _get_stdin_sink(job_id)
        if sink is None:
            # No writable session to continue. Do NOT consume the gate so a
            # later reattach (once a sink exists) can still answer.
            return AnswerResult(False, "no-sink", job_id)

        # Perform the single stdin write while still holding the lock, then flip
        # the consumed marker atomically with respect to other answerers.
        payload = _format_turn(choice)
        sink.write(payload)
        try:
            sink.flush()
        except Exception:
            pass

        rec["gate_consumed"] = True
        rec["state"] = "running"  # gate resolved; session continues
        rec["answered_at"] = time.time()
        rec["answer"] = (list(choice) if isinstance(choice, (list, tuple))
                         else choice)
        # GATE-1: retire the pending prompt so its tool_use_id can no longer be
        # matched by _find_job_id or surfaced by load_pending_prompt. Retained as
        # resolved_prompt for history. Done in the SAME write-lock critical
        # section as the consume + write, so single-consumer atomicity holds.
        resolved = rec.pop("pending_prompt", None)
        if resolved is not None:
            rec["resolved_prompt"] = resolved
        _jr._write_record(rec)
        return AnswerResult(True, "written", job_id)
