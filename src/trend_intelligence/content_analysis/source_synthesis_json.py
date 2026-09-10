"""A narrow, auditable repair for quoted speech in synthesis ``text`` fields.

The raw model answer is never changed by this function. It cannot repair a
schema, citations, truncation, or arbitrary malformed JSON. Existing evidence
and schema validation remains mandatory after parsing.
"""
from __future__ import annotations

import hashlib
import json
import re

from .artifacts import parse_model_json

ALGORITHM_VERSION = "source-text-adjacent-evidence-quote-escape/v1"
_TEXT_START = re.compile(r'"text"\s*:\s*"')
_EVIDENCE_BOUNDARY = re.compile(r'"\s*,\s*"evidence_ids"\s*:\s*\[')
_FENCED_DOCUMENT = re.compile(r'\s*```(?:json)?\r?\n(?P<body>[\s\S]*?)\r?\n```\s*')
_STRUCTURAL_TEXT = re.compile(r'[{}\[\]:,]')
_CHINESE_PROSE = re.compile(r'[\u3400-\u9fff]')


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unescaped_at(text: str, offset: int) -> bool:
    slashes, index = 0, offset - 1
    while index >= 0 and text[index] == "\\":
        slashes += 1
        index -= 1
    return slashes % 2 == 0


def _bare_quotes(text: str) -> list[int]:
    positions, index = [], 0
    while index < len(text):
        if text[index] == "\\":
            # Preserve every existing escape byte, valid or otherwise. JSON
            # parsing later rejects invalid escapes instead of repairing them.
            index += 2
        else:
            if text[index] == '"':
                positions.append(index)
            index += 1
    return positions


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("quote repair refuses ambiguous duplicate JSON fields")
        value[key] = item
    return value


def parse_source_synthesis_json(raw: str) -> tuple[dict, dict | None]:
    """Parse normally, or escape only paired quotes in text→evidence_ids fields.

    A repair is refused if the candidate string contains ASCII JSON structure
    punctuation, raw control characters, odd/unpaired quotes, or a possible
    field boundary. Each quoted span must contain Chinese prose, so adjacent
    JSON literals/operators and English-only spans are conservatively refused.
    """
    try:
        return parse_model_json(raw), None
    except json.JSONDecodeError as initial_error:
        return _repair_adjacent_text_quotes(raw, initial_error)


def _repair_adjacent_text_quotes(raw: str, initial_error: json.JSONDecodeError) -> tuple[dict, dict]:
    stripped = raw.strip()
    if stripped.startswith("```"):
        wrapper = _FENCED_DOCUMENT.fullmatch(raw)
        if wrapper is None:
            raise initial_error  # Never discard trailing prose or an unfinished fence.
        document_start, document_end = wrapper.span("body")
    else:
        document_start, document_end = 0, len(raw)
    document = raw[document_start:document_end]
    if not document.lstrip().startswith("{") or not document.rstrip().endswith("}"):
        raise initial_error
    insertions = []
    for start in _TEXT_START.finditer(document):
        if not _unescaped_at(document, start.start()):
            continue
        end = next((candidate for candidate in _EVIDENCE_BOUNDARY.finditer(document, start.end())
                    if _unescaped_at(document, candidate.start())), None)
        if end is None:
            continue
        body = document[start.end():end.start()]
        quotes = _bare_quotes(body)
        if not quotes:
            continue
        # ASCII structural characters can indicate a swallowed key/value, an
        # array/object, or concatenated fields. Never attempt those cases.
        if (_STRUCTURAL_TEXT.search(body) or any(ord(character) < 32 for character in body)
                or len(quotes) % 2 or
                any(not _CHINESE_PROSE.search(body[left + 1:right])
                    for left, right in zip(quotes[::2], quotes[1::2]))):
            raise initial_error
        insertions.extend(document_start + start.end() + position for position in quotes)
    if not insertions or len(insertions) != len(set(insertions)):
        raise initial_error
    insertions.sort()
    # Apply from right to left so offsets refer to the untouched raw answer.
    repaired = raw
    for offset in reversed(insertions):
        repaired = repaired[:offset] + "\\" + repaired[offset:]
    repaired_document = (repaired[document_start:document_end + len(insertions)]
                         if document_start else repaired[:document_end + len(insertions)])
    # Reject duplicate fields in repaired candidates: an apparent second text
    # boundary must not be hidden by json.loads' usual last-value-wins behavior.
    try:
        result = json.loads(repaired_document, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise initial_error from exc
    if not isinstance(result, dict):
        raise initial_error
    return result, {
        "algorithm_version": ALGORITHM_VERSION,
        "repair_kind": "escape_paired_quotes_inside_text_before_evidence_ids",
        "original_sha256": _digest(raw),
        "repaired_sha256": _digest(repaired),
        "inserted_character": "\\",
        "insertion_offsets": insertions,
        "offset_unit": "unicode_codepoints_in_original_raw_answer",
        "inserted_escape_count": len(insertions),
        "semantic_or_schema_validation_performed": False,
    }
