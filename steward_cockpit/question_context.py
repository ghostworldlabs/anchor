"""Plain-data snapshots of a question and the response that explains it.

These helpers neither render HTML nor interpret saved text as instructions.
Authorization scope is retained as data; saving a question grants no authority.
"""

import hashlib
import json
import re


MAX_CONTEXT_CHARS = 12_000


def _json_copy(value):
    """Copy JSON data without silently widening an invalid authorization scope."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _source_window(response_text, question):
    if len(response_text) <= MAX_CONTEXT_CHARS:
        return response_text, False

    position = response_text.rfind(question)
    if position < 0:
        start = 0
    else:
        surrounding = max(0, MAX_CONTEXT_CHARS - len(question))
        start = max(0, position - surrounding // 2)
        start = min(start, len(response_text) - MAX_CONTEXT_CHARS)
    return response_text[start:start + MAX_CONTEXT_CHARS], True


def _explicit_recommendation(response_text):
    """Return a verbatim line carrying an explicit recommendation marker."""
    for line in response_text.splitlines():
        excerpt = line.strip()
        marker = re.sub(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", excerpt)
        marker = marker.replace("**", "").replace("__", "")
        if re.match(r"^(?:I recommend\b|Recommendation\s*:)\s*\S", marker, re.IGNORECASE):
            if len(excerpt) <= MAX_CONTEXT_CHARS:
                return excerpt
    return ""


def save_question_context(question, response_text, *, asked_at, source_ref="", scope=None):
    """Return a JSON snapshot, preserving the question and original source ref.

    ``context`` is a literal source substring of at most 12,000 characters.
    When shortened, its window includes the question if the question occurs in
    the source and fits. The separate ``question`` field is always exact, even
    for questions longer than that bound. ``truncated`` signals lost context.

    The stable ID binds question, source reference, and JSON authorization scope;
    a changed timestamp or context window alone does not create a new identity.
    Invalid strings or non-JSON scope/timestamps raise TypeError or ValueError.
    """
    if not isinstance(question, str) or not isinstance(response_text, str):
        raise TypeError("question and response_text must be strings")
    if not question.strip():
        raise ValueError("question must not be empty")
    if not isinstance(source_ref, str):
        raise TypeError("source_ref must be a string")

    authorization_scope = _json_copy(scope)
    context, truncated = _source_window(response_text, question)
    identity = json.dumps(
        [question, source_ref, authorization_scope],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "question": question,
        "context": context,
        "truncated": truncated,
        "recommendation": _explicit_recommendation(response_text),
        "alternatives": [],
        "authorization_scope": authorization_scope,
        "asked_at": _json_copy(asked_at),
        "source_ref": source_ref,
    }


def normalize_question_context(value):
    """Normalize a saved dictionary or legacy question string; otherwise None.

    Unknown fields and supplied IDs are not trusted. Invalid JSON scope causes
    rejection rather than replacement with a broader scope. Existing truncation
    remains visible, and explicit saved recommendations remain plain strings.
    """
    if isinstance(value, str):
        value = {"question": value}
    if not isinstance(value, dict):
        return None
    question = value.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    context = value.get("context", value.get("response_text", ""))
    source_ref = value.get("source_ref", "")
    try:
        normalized = save_question_context(
            question,
            context if isinstance(context, str) else "",
            asked_at=value.get("asked_at"),
            source_ref=source_ref if isinstance(source_ref, str) else "",
            scope=value.get("authorization_scope", value.get("scope")),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    normalized["truncated"] = normalized["truncated"] or value.get("truncated") is True
    recommendation = value.get("recommendation")
    if isinstance(recommendation, str):
        explicit = _explicit_recommendation(recommendation)
        if explicit:
            normalized["recommendation"] = explicit
    alternatives = value.get("alternatives")
    if isinstance(alternatives, list):
        normalized["alternatives"] = [item for item in alternatives if isinstance(item, str)]
    return normalized
