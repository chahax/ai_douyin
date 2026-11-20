"""A lossless C/G quotation view of one exact current native goal.

Every source field survives. Only the strings named by the current v10 evidence
catalog become typed references, and the catalog contains their original quotes
once at the original paths. Reconstruction checks the complete source identity;
neither this representation nor its validator proves creative correctness.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from . import creative_goal_drama_audit_contract_v10 as drama

VERSION = "creative_goal_evidence_view/v1"
REFERENCE_KEY = "$goal_evidence_ref"
VIEW_FIELDS = {"schema", "native_goal_sha256", "evidence_catalog", "goal_structure"}


class GoalEvidenceViewError(ValueError):
    """A view is not a complete lossless representation of its claimed source."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _validate_json(value):
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise GoalEvidenceViewError("JSON object keys must be strings")
            _validate_json(child)
    elif type(value) is list:
        for child in value:
            _validate_json(child)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise GoalEvidenceViewError("view and source must contain only JSON values")
    try:
        _json(value)
    except (TypeError, ValueError) as exc:
        raise GoalEvidenceViewError("invalid or nonfinite JSON value") from exc


def _valid_sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _parts(document_path):
    if type(document_path) is not str or not document_path or any(
            not part for part in document_path.split(".")):
        raise GoalEvidenceViewError("evidence needs an exact nonempty dotted document_path")
    return document_path.split(".")


def _child(container, part):
    if type(container) is dict:
        if part not in container:
            raise GoalEvidenceViewError("evidence document_path does not exist")
        return part
    if type(container) is list:
        if re.fullmatch(r"0|[1-9][0-9]*", part) is None:
            raise GoalEvidenceViewError("array document_path requires an unescaped canonical index")
        index = int(part)
        if index >= len(container):
            raise GoalEvidenceViewError("array evidence index is out of range")
        return index
    raise GoalEvidenceViewError("evidence document_path traverses a scalar")


def _location(document, document_path):
    parts = _parts(document_path)
    parent = document
    for part in parts[:-1]:
        parent = parent[_child(parent, part)]
    return parent, _child(parent, parts[-1])


def _catalog(value):
    if type(value) is not dict or not value:
        raise GoalEvidenceViewError("complete nonempty current C/G evidence catalog required")
    paths = set()
    for ref, row in value.items():
        if (type(ref) is not str or not ref or type(row) is not dict
                or set(row) != {"document_path", "quote"}
                or type(row["quote"]) is not str or not row["quote"].strip()):
            raise GoalEvidenceViewError("catalog rows require exact ref, document_path and original string quote")
        _parts(row["document_path"])
        if row["document_path"] in paths:
            raise GoalEvidenceViewError("duplicate evidence document_path")
        paths.add(row["document_path"])
    return value


def _native_catalog(native):
    try:
        return _catalog(drama.build_evidence_catalog(native))
    except GoalEvidenceViewError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise GoalEvidenceViewError("native goal cannot produce the exact current v10 C/G catalog") from exc


def _reject_reserved_source_keys(value):
    if type(value) is dict:
        if REFERENCE_KEY in value:
            raise GoalEvidenceViewError("native source collides with the reserved typed-reference key")
        for child in value.values():
            _reject_reserved_source_keys(child)
    elif type(value) is list:
        for child in value:
            _reject_reserved_source_keys(child)


def build_lossless_goal_evidence_view(native_goal):
    """Build and round-trip-verify a view, without modifying the native object."""
    if type(native_goal) is not dict or not native_goal:
        raise GoalEvidenceViewError("complete nonempty native goal object required")
    _validate_json(native_goal)
    _reject_reserved_source_keys(native_goal)
    catalog = deepcopy(_native_catalog(native_goal))
    structure = deepcopy(native_goal)
    for ref, row in catalog.items():
        parent, key = _location(structure, row["document_path"])
        if type(parent[key]) is not str or parent[key] != row["quote"]:
            raise GoalEvidenceViewError("catalog quote or path differs from the exact native string")
        parent[key] = {REFERENCE_KEY: ref}
    view = {"schema": VERSION, "native_goal_sha256": digest(native_goal),
            "evidence_catalog": catalog, "goal_structure": structure}
    reconstructed = reconstruct_goal(view, expected_native_goal_sha256=digest(native_goal))
    if _json(reconstructed) != _json(native_goal):
        raise GoalEvidenceViewError("round trip changed the complete original native object")
    return view


def reconstruct_goal(view, *, expected_native_goal_sha256=None):
    """Strictly restore all original fields and verify current C/G and source SHA.

    If an externally frozen source SHA is available, pass it as the optional
    expected identity. A self-consistent view by itself is a representation,
    not proof that its source has been adopted or semantically approved.
    """
    if type(view) is not dict or set(view) != VIEW_FIELDS or view.get("schema") != VERSION:
        raise GoalEvidenceViewError("exact current lossless-view schema and fields required")
    _validate_json(view)
    claimed_sha = view["native_goal_sha256"]
    if not _valid_sha(claimed_sha):
        raise GoalEvidenceViewError("native source SHA must be a lowercase SHA-256 identity")
    if expected_native_goal_sha256 is not None and (
            not _valid_sha(expected_native_goal_sha256) or claimed_sha != expected_native_goal_sha256):
        raise GoalEvidenceViewError("view differs from the externally expected native source SHA")
    catalog = _catalog(view["evidence_catalog"])
    if type(view["goal_structure"]) is not dict or not view["goal_structure"]:
        raise GoalEvidenceViewError("complete original goal structure required")
    seen_refs, seen_paths = set(), set()

    def restore(value, parts):
        if type(value) is dict:
            if REFERENCE_KEY in value:
                if set(value) != {REFERENCE_KEY} or type(value[REFERENCE_KEY]) is not str:
                    raise GoalEvidenceViewError("typed string reference has wrong type or extra fields")
                ref = value[REFERENCE_KEY]
                if ref not in catalog:
                    raise GoalEvidenceViewError("unknown typed C/G reference")
                path = ".".join(map(str, parts))
                if ref in seen_refs or path in seen_paths:
                    raise GoalEvidenceViewError("duplicate typed reference or document_path")
                if catalog[ref]["document_path"] != path:
                    raise GoalEvidenceViewError("typed reference is at the wrong original document_path")
                # Resolve the original dotted path too, rejecting ambiguous keys,
                # escaped indices, nonexistent paths and non-string leaves.
                parent, key = _location(view["goal_structure"], path)
                if parent[key] is not value:
                    raise GoalEvidenceViewError("ambiguous or escaped evidence document_path")
                seen_refs.add(ref)
                seen_paths.add(path)
                return catalog[ref]["quote"]
            return {key: restore(child, [*parts, key]) for key, child in value.items()}
        if type(value) is list:
            return [restore(child, [*parts, index]) for index, child in enumerate(value)]
        return deepcopy(value)

    reconstructed = restore(view["goal_structure"], [])
    if seen_refs != set(catalog):
        raise GoalEvidenceViewError("missing typed references or extra catalog rows")
    if _native_catalog(reconstructed) != catalog:
        raise GoalEvidenceViewError("catalog has missing, extra, changed or renumbered current C/G evidence")
    if digest(reconstructed) != claimed_sha:
        raise GoalEvidenceViewError("reconstructed complete native source SHA differs")
    return reconstructed


def validate_lossless_goal_evidence_view(view, native_goal=None):
    """Return a local identity proof; no text judgment or dispatch occurs."""
    if native_goal is not None:
        if type(native_goal) is not dict or not native_goal:
            raise GoalEvidenceViewError("complete original native goal required for source comparison")
        _validate_json(native_goal)
    expected = digest(native_goal) if native_goal is not None else None
    reconstructed = reconstruct_goal(view, expected_native_goal_sha256=expected)
    if native_goal is not None and _json(reconstructed) != _json(native_goal):
        raise GoalEvidenceViewError("complete reconstructed object differs from supplied original")
    return {"schema": VERSION + "/validation", "valid": True,
        "native_goal_sha256": digest(reconstructed), "view_sha256": digest(view),
        "evidence_catalog_sha256": digest(view["evidence_catalog"]),
        "evidence_row_count": len(view["evidence_catalog"]),
        "external_native_source_verified": native_goal is not None,
        "complete_native_round_trip_verified": True, "native_values_modified": False,
        "quote_validation_relaxed": False, "semantic_quality_proven": False,
        "dispatch_performed": False}
