"""Plain-data snapshots of a question and the response that explains it.

These helpers neither render HTML nor interpret saved text as instructions.
Authorization scope is retained as data; saving a question grants no authority.
"""

import hashlib
import json
import re


MAX_CONTEXT_CHARS = 12_000

#: Phrases that mark a real recommendation, checked over the TAIL of the turn
#: only (where the decision lives). Deliberately NARROW after the 2026-08-26
#: review: a false POSITIVE silently disables the check, which is the
#: expensive direction. Dropped from an earlier draft: bare "recommended"
#: (matches "as recommended by the plan") and "my call" (matches the exact
#: opposite sentence, "that's not my call - it's yours"). ONE matcher for the
#: engine's decision-shape check and the saved record (cockpit Wave C).
RECOMMEND_RE = re.compile(
    r"\b(i\s*(?:'|\u2019)?\s*(?:d|would)?\s*(?:recommend|suggest|propose)"
    r"|i\s*(?:'|\u2019)?\s*d?\s*lean\s+toward"
    r"|i\s*(?:'|\u2019)?\s*d?\s*go\s+with"
    r"|i\s+think\s+we\s+should|my\s+recommendation|my\s+advice\s+is"
    r"|recommendation\s*[:\u2014-]|the\s+right\s+move\s+is)", re.I)

#: How much of the turn tail counts as "where the decision is stated".
RECOMMEND_TAIL = 1200

_LIST_MARK = re.compile(r"^(?:#{1,6}\s+|[-*+\u2022]\s+|\d+[.)]\s+)")


def _clean(line):
    """Markdown markers out of a line, the words kept (for matching only)."""
    return _LIST_MARK.sub("", line.strip()).replace("**", "").replace("__", "").strip()


def _sentences(text):
    """(verbatim, cleaned, from_bullet) per sentence, line boundaries kept."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        bullet = bool(_LIST_MARK.match(line.strip()))
        for i, part in enumerate(re.split(r"(?<=[.!?])\s+", line.strip())):
            if part.strip():
                out.append((part.strip(), _clean(part), bullet and i == 0))
    return out


def parse_decision(text):
    """The decision shape read from the TAIL of a turn, before its last question:
    the recommendation (the last marker sentence with words beyond the marker),
    why (the sentence after it), the alternatives (bullet lines between the
    recommendation and the question, at most three) and the stake (the one
    sentence before the recommendation). Verbatim, bounded; "" / [] when absent."""
    sents = _sentences((text or "")[-RECOMMEND_TAIL:])
    q_idx = next((i for i in range(len(sents) - 1, -1, -1) if sents[i][1].endswith("?")), None)
    scan_end = q_idx if q_idx is not None else len(sents)
    rec_idx = None
    for i in range(scan_end - 1, -1, -1):
        m = RECOMMEND_RE.search(sents[i][1])
        if m and re.search(r"\w", sents[i][1][m.end():]):
            rec_idx = i
            break
    out = {"stake": "", "recommendation": "", "why": "", "alternatives": []}
    if rec_idx is None:
        return out
    out["recommendation"] = sents[rec_idx][0][:240]
    if rec_idx and not sents[rec_idx - 1][1].endswith("?"):
        out["stake"] = sents[rec_idx - 1][0][:240]
    after = sents[rec_idx + 1:scan_end]
    if after and not after[0][2] and not after[0][1].endswith("?"):
        out["why"] = after[0][0][:200]
        after = after[1:]
    out["alternatives"] = [v[:160] for v, c, b in after if b and not c.endswith("?")][:3]
    return out


def has_recommendation(text) -> bool:
    """True when a decision turn actually carried a recommendation (the tail
    only: a recommendation buried in a long narrative is not one about the
    question asked at the end)."""
    return bool(parse_decision(text)["recommendation"])


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


def save_question_context(question, response_text, *, asked_at, source_ref="", scope=None,
                          origin_id=None, what_changed=None):
    """Return a JSON snapshot, preserving the question and original source ref.

    ``context`` is a literal source substring of at most 12,000 characters.
    When shortened, its window includes the question if the question occurs in
    the source and fits. The separate ``question`` field is always exact, even
    for questions longer than that bound. ``truncated`` signals lost context.

    The stable ID binds question, source reference, and JSON authorization scope
    minus the turn (``source_turn_id``): the same question asked again on the
    same work is the same question; a changed timestamp, context window or turn
    alone does not create a new identity. ``origin_id`` (a reshaped re-ask of the
    same decision) makes THAT the identity: the shape changed, the decision did
    not. ``what_changed`` is the open question this one replaces. Invalid strings
    or non-JSON scope/timestamps raise TypeError or ValueError.
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
        [question, source_ref, {k: v for k, v in authorization_scope.items() if k != "source_turn_id"}
         if isinstance(authorization_scope, dict) else authorization_scope],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    shape = parse_decision(response_text)
    origin = origin_id if isinstance(origin_id, str) and re.fullmatch(r"[0-9a-f]{64}", origin_id) else None
    return {
        "id": origin or hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "question": question,
        "context": context,
        "truncated": truncated,
        "stake": shape["stake"],
        "recommendation": shape["recommendation"],
        "why": shape["why"],
        "alternatives": shape["alternatives"],
        "authorization_scope": authorization_scope,
        "asked_at": _json_copy(asked_at),
        "source_ref": source_ref,
        "origin_id": origin,
        "what_changed": str(what_changed)[:400] if isinstance(what_changed, str) else None,
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
            origin_id=value.get("origin_id"), what_changed=value.get("what_changed"),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    normalized["truncated"] = normalized["truncated"] or value.get("truncated") is True
    recommendation = value.get("recommendation")
    if isinstance(recommendation, str) and has_recommendation(recommendation):
        normalized["recommendation"] = recommendation.strip()[:240]
    for key in ("stake", "why"):
        if isinstance(value.get(key), str) and value[key].strip():
            normalized[key] = value[key].strip()[:240]
    alternatives = value.get("alternatives")
    if isinstance(alternatives, list) and alternatives:
        normalized["alternatives"] = [item[:160] for item in alternatives if isinstance(item, str)][:3]
    return normalized
