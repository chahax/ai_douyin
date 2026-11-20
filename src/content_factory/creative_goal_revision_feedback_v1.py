"""Deterministic feedback projection; never rewrites a native planning document.

Only named compiler-produced evidence tables in complete goal-audit decisions
are replaced by references. Findings, uncertainties and unrecognized fields stay
verbatim. This is preparation, not audit admission or permission to dispatch.
The caller persists original diagnostics; a pure preview can leave that binding
pending and carries canonical JSON identities rather than a claimed file proof.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

VERSION = "creative_goal_revision_feedback/v1"
AUDIT_FIELDS = ("complete_same_source_goal_audits", "complete_same_source_goal_audit")
COMPILED_TABLES = (
    "citations", "counterevidence_citations", "commitment_check_evidence",
    "commitment_usage_catalog", "scope_observation_evidence",
)


class FeedbackProjectionError(ValueError):
    """A projection cannot establish the supplied original JSON identity."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _measure(value):
    text = _json(value)
    return {"sha256": digest(value), "characters": len(text),
            "utf8_bytes": len(text.encode("utf-8"))}


def _validate_json(value):
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str:
                raise FeedbackProjectionError("JSON object keys must be strings")
            _validate_json(child)
    elif type(value) is list:
        for child in value:
            _validate_json(child)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise FeedbackProjectionError("feedback must contain only JSON values")


def _pointer(parent, key):
    escaped = str(key).replace("~", "~0").replace("/", "~1")
    return parent + "/" + escaped


def _unresolved_rows(value, pointer=""):
    if type(value) is dict:
        if value.get("status") in ("fail", "unknown"):
            yield {"json_pointer": pointer, "status": value["status"], "sha256": digest(value)}
        for key in sorted(value):
            yield from _unresolved_rows(value[key], _pointer(pointer, key))
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from _unresolved_rows(child, _pointer(pointer, index))


def _unsafe_to_externalize(value):
    """Conservative structural guard; no Chinese prose is classified."""
    if type(value) is dict:
        if value.get("status") in ("fail", "unknown"):
            return True
        if any(value.get(key) not in (None, [], "", {}) for key in ("error", "errors")):
            return True
        if any(key in value and value[key] is None
               for key in ("declared_character_id", "declared_prop_id")):
            return True
        return any(_unsafe_to_externalize(child) for child in value.values())
    if type(value) is list:
        return any(_unsafe_to_externalize(child) for child in value)
    return False


def _resolve_pointer(document, pointer):
    value = document
    for key in pointer.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if type(value) is list else value[key]
    return value


def _original_artifact(diagnostics, path):
    artifact = {"canonical_json_sha256": digest(diagnostics), "local_path": None,
                "local_file_sha256": None, "local_json_verified": False,
                "local_binding_pending": True}
    if path is None:
        return artifact
    target = Path(path).resolve()
    try:
        raw = target.read_bytes()
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise FeedbackProjectionError("original diagnostics contain duplicate JSON keys")
                result[key] = value
            return result
        original = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs)
        _validate_json(original)
        if _json(original) != _json(diagnostics):
            raise FeedbackProjectionError("local original diagnostics differ from supplied JSON")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        if isinstance(exc, FeedbackProjectionError):
            raise
        raise FeedbackProjectionError("cannot verify original diagnostics artifact") from exc
    artifact.update(local_path=str(target), local_file_sha256=hashlib.sha256(raw).hexdigest(),
                    local_json_verified=True, local_binding_pending=False)
    return artifact


def _complete_decision(value):
    return (type(value) is dict and value.get("valid") is True
            and type(value.get("accepted")) is bool
            and type(value.get("findings")) is list
            and type(value.get("uncertainties")) is list
            and value.get("audit_kind") in ("source", "drama"))


def project_goal_revision_feedback(diagnostics, *, original_diagnostics_path=None):
    """Return ``{projected_diagnostics, projection_manifest}`` without mutation.

    ``diagnostics`` is the complete original JSON object, including separate
    verified pipeline diagnoses. An optional path must contain exactly that
    object and is read only. With no path, references bind original JSON pointers
    and canonical hashes; persisting/binding them remains the caller's duty.

    Complete decisions in the plural/singular same-source goal-audit fields are
    eligible. Only COMPILED_TABLES are externalized, and any nested fail/unknown,
    explicit error or null declared identity retains the entire table. Receipt,
    schema, context/source identities and all other fields pass through intact.
    Neither validity nor semantic authority of a finding is decided here.
    """
    if type(diagnostics) is not dict or not diagnostics:
        raise FeedbackProjectionError("complete nonempty original diagnostics object required")
    _validate_json(diagnostics)
    try:
        original_identity = _measure(diagnostics)
    except (ValueError, TypeError) as exc:
        raise FeedbackProjectionError("feedback contains invalid or nonfinite JSON") from exc
    artifact = _original_artifact(diagnostics, original_diagnostics_path)
    projected = deepcopy(diagnostics)
    unresolved = list(_unresolved_rows(diagnostics))
    externalized, retained = [], []
    for field in AUDIT_FIELDS:
        if field not in diagnostics:
            continue
        value = diagnostics[field]
        decisions = enumerate(value) if type(value) is list else [(None, value)]
        for index, decision in decisions:
            pointer = _pointer("", field)
            if index is not None:
                pointer = _pointer(pointer, index)
            if not _complete_decision(decision):
                retained.append({"json_pointer": pointer,
                                 "reason": "unrecognized or incomplete decision retained verbatim"})
                continue
            output = projected[field][index] if index is not None else projected[field]
            for table in COMPILED_TABLES:
                if table not in decision or not decision[table]:
                    continue
                table_pointer = _pointer(pointer, table)
                original_table = decision[table]
                protected = any(table_pointer.startswith(row["json_pointer"] + "/")
                                for row in unresolved)
                if (type(original_table) is not dict or protected
                        or _unsafe_to_externalize(original_table)):
                    retained.append({"json_pointer": table_pointer,
                                     "reason": "unrecognized table, unresolved row, explicit error or undeclared identity retained verbatim"})
                    continue
                identity = _measure(original_table)
                reference = {"schema": VERSION + "/original_table_reference",
                    "original_json_pointer": table_pointer,
                    "original_value_sha256": identity["sha256"],
                    "original_diagnostics_sha256": original_identity["sha256"],
                    "local_path": artifact["local_path"],
                    "local_binding_pending": artifact["local_binding_pending"],
                    "source_status": "passed" if decision["accepted"] and not
                        (decision["findings"] or decision["uncertainties"]) else "failed_or_unknown",
                    "disposition": "compiler_evidence_table_retained_in_original_diagnostics"}
                output[table] = reference
                externalized.append({"json_pointer": table_pointer, **identity,
                                     "source_status": reference["source_status"]})
    # Verify raw error rows, including future/unknown table shapes, survived.
    for row in unresolved:
        if digest(_resolve_pointer(projected, row["json_pointer"])) != row["sha256"]:
            raise FeedbackProjectionError("projection changed an original fail/unknown row")
    manifest = {"schema": VERSION + "/projection_manifest",
        "original_diagnostics": original_identity,
        "projected_diagnostics": _measure(projected),
        "original_artifact": artifact,
        "externalized_tables": externalized,
        "retained_tables_or_decisions": retained,
        "preserved_unresolved_rows": unresolved,
        "unrecognized_fields_preserved": True,
        "native_goal_document_consumed": False,
        "native_review_modified": False,
        "finding_semantic_authority_decided": False,
        "dispatch_performed": False}
    return {"projected_diagnostics": projected, "projection_manifest": manifest}
