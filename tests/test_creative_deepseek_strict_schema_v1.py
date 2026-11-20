"""Service capability projection tests; the full native contract stays local."""
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_deepseek_strict_schema_v1 as compiler
from src.content_factory import creative_goal_legal_usage_source_audit_v2 as source
from tests.test_creative_goal_legal_usage_source_audit_v1 import authority, goal
from tests.test_creative_goal_legal_usage_source_audit_v2 import synthetic_source


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def alternatives(*kinds):
    return {"oneOf": [obj({"kind": {"const": kind}, "reason": {"type": "string"}}) for kind in kinds]}


def walk(schema):
    yield schema
    if isinstance(schema, dict):
        for value in schema.values():
            yield from walk(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from walk(value)


def test_actual_source_v2_projection_retains_every_c_g_and_native_kind(goal, authority):
    original = source.build_source_schema(goal, authority, context_sha256="d" * 64)
    snapshot = deepcopy(original)
    service, manifest = compiler.compile_source_schema_with_manifest(original)
    assert original == snapshot and original != service
    assert set(service["properties"]["legal_usage_scan"]["properties"]) == set(original["properties"]["legal_usage_scan"]["properties"])
    assert not any(set(row) & {"$ref", "$defs", "oneOf", "allOf", "if", "then", "else", *compiler.REMOVED_CONSTRAINTS}
                   for row in walk(service) if isinstance(row, dict))
    for row in walk(service):
        if isinstance(row, dict) and row.get("type") == "object":
            assert set(row["required"]) == set(row["properties"]) and row["additionalProperties"] is False
    native = synthetic_source(goal, authority)
    Draft202012Validator(original).validate(native)
    Draft202012Validator(service).validate(native)
    assert manifest["original_contract_sha256"] == source.digest(original)
    assert manifest["service_schema_sha256"] == source.digest(service)
    assert manifest["service_schema_is_weaker_than_local_contract"]
    assert manifest["original_local_contract_validation_required"] and not manifest["semantic_gate_changed"]
    operations = {row["operation"] for row in manifest["transformations"]}
    assert {"expand_local_ref", "disjoint_kind_oneOf_to_anyOf", "exact_frozen_judgment_to_status_anyOf", "local_only_constraint"} <= operations


@pytest.mark.parametrize("status,revision,valid", [
    ("pass", "", True), ("pass", "changed", False), ("fail", "complete native revision", True),
    ("fail", "", False), ("fail", "   ", False), ("unknown", "", True),
    ("unknown", "native uncertainty", True), ("other", "", False)])
def test_exact_frozen_judgment_preserves_status_revision_conditions(status, revision, valid):
    original = obj({"claim": deepcopy(compiler.FROZEN_JUDGMENT)})
    service = compiler.compile_source_schema(original)
    native = {"claim": {"status": status, "reason": "native judgment", "required_revision": revision}}
    assert Draft202012Validator(original).is_valid(native) is valid
    assert Draft202012Validator(service).is_valid(native) is valid


def test_local_bounds_and_uniqueness_remain_effective_after_weaker_service_projection():
    original = obj({"observations": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 3},
                                     "minItems": 1, "maxItems": 2, "uniqueItems": True}})
    service, manifest = compiler.compile_source_schema_with_manifest(original)
    assert set(row["keyword"] for row in manifest["transformations"] if row["operation"] == "local_only_constraint") == compiler.REMOVED_CONSTRAINTS
    for native in ({"observations": []}, {"observations": ["a", "a"]}, {"observations": ["abcd"]}, {"observations": ["a", "b", "c"]}):
        Draft202012Validator(service).validate(native)
        with pytest.raises(ValidationError):
            Draft202012Validator(original).validate(native)


@pytest.mark.parametrize("rule", [
    {"allOf": [{"type": "string"}]}, {"if": {"type": "string"}, "then": {"const": "x"}},
    {"not": {"type": "string"}}, {"type": "string", "format": "email"},
    {"type": "number", "minimum": 1}, {"type": "array", "prefixItems": []},
    {"type": "string", "made_up": True}, {"type": ["string", "null"]},
    {"const": 2}, {"enum": ["x", 2]}, {"type": "null"}, {}, False])
def test_unverified_schema_rules_fail_closed(rule):
    with pytest.raises(compiler.StrictSchemaError):
        compiler.compile_source_schema(obj({"field": rule}))


def test_modified_frozen_judgment_is_not_silently_relaxed():
    changed = deepcopy(compiler.FROZEN_JUDGMENT)
    changed["allOf"][0]["then"]["properties"]["required_revision"]["const"] = "changed"
    with pytest.raises(compiler.StrictSchemaError, match="not the exact frozen"):
        compiler.compile_source_schema(obj({"claim": changed}))


@pytest.mark.parametrize("mutation", [
    lambda s: s.pop("required"), lambda s: s.update(required=[]),
    lambda s: s.update(required=["field", "field"]), lambda s: s.update(additionalProperties=True),
    lambda s: s.pop("additionalProperties")])
def test_incomplete_objects_never_gain_required_or_closed_fields_implicitly(mutation):
    schema = obj({"field": {"type": "string"}})
    mutation(schema)
    with pytest.raises(compiler.StrictSchemaError):
        compiler.compile_source_schema(schema)


@pytest.mark.parametrize("branches", [
    alternatives("legal_assertion", "legal_assertion"),
    {"oneOf": [{"type": "string"}, {"type": "integer"}]},
    {"oneOf": [obj({"kind": {"enum": ["x", "y"]}}), obj({"kind": {"const": "z"}})]}])
def test_only_provably_disjoint_kind_oneof_can_become_anyof(branches):
    with pytest.raises(compiler.StrictSchemaError):
        compiler.compile_source_schema(obj({"row": branches}))


def test_disjoint_kind_anyof_does_not_accept_cross_kind_extra_fields():
    original = obj({"row": {"oneOf": [obj({"kind": {"const": "a"}, "a": {"type": "string"}}),
                                      obj({"kind": {"const": "b"}, "b": {"type": "string"}})]}})
    service = compiler.compile_source_schema(original)
    for native in ({"row": {"kind": "a", "b": "wrong"}}, {"row": {"kind": "a", "a": "ok", "b": "extra"}}):
        assert not Draft202012Validator(service).is_valid(native)


@pytest.mark.parametrize("ref", ["#/missing", "https://other.invalid/schema", "#/$defs/missing", "#/$defs/a/child"])
def test_nonlocal_or_missing_reference_is_not_dropped(ref):
    with pytest.raises(compiler.StrictSchemaError):
        compiler.compile_source_schema(obj({"field": {"$ref": ref}}))


def test_recursive_and_unused_unsupported_definitions_fail_closed():
    schema = obj({"field": {"type": "string"}})
    schema["$defs"] = {"unused": {"$ref": "#/$defs/unused"}}
    with pytest.raises(compiler.StrictSchemaError, match="recursive"):
        compiler.compile_source_schema(schema)
    schema["$defs"] = {"unused": {"type": "string", "format": "unverified"}}
    with pytest.raises(compiler.StrictSchemaError, match="unsupported"):
        compiler.compile_source_schema(schema)


def test_json_pointer_definition_escape_and_detached_expansion():
    schema = obj({"a": {"$ref": "#/$defs/a~1b~0c"}, "b": {"$ref": "#/$defs/a~1b~0c"}})
    schema["$defs"] = {"a/b~c": {"type": "string", "pattern": "^x$"}}
    service = compiler.compile_source_schema(schema)
    service["properties"]["a"]["pattern"] = "changed"
    assert service["properties"]["b"]["pattern"] == "^x$" and schema["$defs"]["a/b~c"]["pattern"] == "^x$"
