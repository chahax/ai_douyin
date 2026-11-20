"""Compile only the verified source-v2 contract to DeepSeek strict Schema.

This is a service capability projection, not a new local admission contract.
Bounds/uniqueness absent from the documented strict subset remain in the
original contract and MUST still be checked by the stage's local validator.
Unknown schema rules fail before transport; only disjoint kind oneOf and the
exact frozen source judgment conditional receive explicit translations.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator, SchemaError

from . import creative_goal_legal_usage_source_audit_v1 as frozen_source
from . import creative_goal_legal_usage_source_audit_v2 as source

VERSION = "creative_deepseek_strict_schema/v1"
REMOVED_CONSTRAINTS = frozenset({"minLength", "maxLength", "minItems", "maxItems", "uniqueItems"})
ALLOWED = frozenset({"type", "properties", "required", "additionalProperties", "items", "enum",
                     "pattern", "description", "anyOf", "oneOf", "const", "$ref", "$defs"})
TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean"})
digest = source.digest
FROZEN_JUDGMENT = deepcopy(frozen_source._judgment())
FROZEN_STATUSES = tuple(frozen_source.STATUSES)


class StrictSchemaError(ValueError):
    code = "DEEPSEEK_STRICT_SCHEMA_UNSUPPORTED"

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        super().__init__(f"{self.code} {path}: {reason}")


def compile_source_schema_with_manifest(schema):
    """Return a detached service schema and auditable, deterministic projection.

    All definitions, including unreferenced definitions, are inspected. Local
    refs must be definition refs without validation siblings; recursive refs
    and unsupported rules cannot disappear through projection.
    """
    if type(schema) is not dict or schema.get("type") != "object":
        raise StrictSchemaError("/", "function parameters must be a complete object schema")
    try:
        Draft202012Validator.check_schema(schema)
        digest(schema)
    except (ValueError, TypeError, UnicodeError, SchemaError) as exc:
        raise StrictSchemaError("/", "original schema is not valid finite JSON Schema") from exc
    original = deepcopy(schema)
    defs = original.get("$defs", {})
    if type(defs) is not dict:
        raise StrictSchemaError("/$defs", "definitions must be an object")
    changes = []

    def fail(path, reason):
        raise StrictSchemaError(path, reason)

    def reference(ref, path):
        if type(ref) is not str or not ref.startswith("#/$defs/") or "/" in ref[len("#/$defs/"):]:
            fail(path, "only direct local definition refs are supported")
        token = ref[len("#/$defs/"):]
        # JSON Pointer escaping is interpreted, never an invented new key.
        if "~" in token.replace("~0", "").replace("~1", ""):
            fail(path, "invalid reference escape")
        name = token.replace("~1", "/").replace("~0", "~")
        if name not in defs:
            fail(path, "reference target missing")
        return name, defs[name]

    def walk(node, path, stack=()):
        if type(node) is not dict:
            fail(path, "boolean and non-object subschemas are not verified for this service")
        # The frozen claim judgment is the sole accepted conditional shape.
        if "allOf" in node or "if" in node or "then" in node or "else" in node:
            if node != FROZEN_JUDGMENT:
                fail(path, "conditional rule is not the exact frozen claim judgment")
            branches = []
            for status in FROZEN_STATUSES:
                branch = deepcopy(node)
                branch.pop("allOf")
                branch["properties"]["status"] = {"const": status}
                if status == "pass":
                    branch["properties"]["required_revision"]["const"] = ""
                elif status == "fail":
                    branch["properties"]["required_revision"].update(frozen_source._nonblank())
                branches.append(walk(branch, path + "/native_status/" + status, stack))
            changes.append({"path": path, "operation": "exact_frozen_judgment_to_status_anyOf",
                            "discriminator": "status", "values": list(FROZEN_STATUSES),
                            "equivalent_before_documented_bound_projection": True})
            return {"anyOf": branches}
        unsupported = set(node) - ALLOWED - REMOVED_CONSTRAINTS
        if unsupported:
            fail(path, "unsupported keywords: " + ",".join(sorted(unsupported)))
        if "$defs" in node and path != "/":
            fail(path, "nested definitions are not verified")
        if "$ref" in node:
            if set(node) - {"$ref", "description"}:
                fail(path, "validation siblings of a ref are not supported")
            name, target = reference(node["$ref"], path)
            if name in stack:
                fail(path, "recursive definition reference")
            value = walk(target, path + "/ref:" + name, (*stack, name))
            if "description" in node:
                value["description"] = node["description"]
            changes.append({"path": path, "operation": "expand_local_ref", "reference": node["$ref"]})
            return value
        value = {}
        for key in sorted(set(node) & REMOVED_CONSTRAINTS):
            changes.append({"path": path + "/" + key, "operation": "local_only_constraint",
                            "keyword": key, "original": deepcopy(node[key])})
        for key in ("description", "pattern"):
            if key in node:
                if type(node[key]) is not str:
                    fail(path + "/" + key, "string required")
                value[key] = node[key]
        if "type" in node:
            if type(node["type"]) is not str or node["type"] not in TYPES:
                fail(path + "/type", "only verified scalar type names are supported")
            value["type"] = node["type"]
        if "const" in node:
            if type(node["const"]) is not str or "enum" in node:
                fail(path + "/const", "only unambiguous string const can become a singleton enum")
            if "type" in value and value["type"] != "string":
                fail(path + "/const", "string const conflicts with declared type")
            value.update(type="string", enum=[node["const"]])
            changes.append({"path": path + "/const", "operation": "string_const_to_singleton_enum"})
        elif "enum" in node:
            enum = node["enum"]
            if type(enum) is not list or not enum or not all(type(item) is str for item in enum):
                fail(path + "/enum", "only nonempty string enum is verified")
            if "type" in value and value["type"] != "string":
                fail(path + "/enum", "enum conflicts with declared type")
            value.update(type="string", enum=deepcopy(enum))
        if node.get("type") == "object" or "properties" in node:
            if node.get("type") != "object":
                fail(path, "object properties require explicit type")
            props, required = node.get("properties"), node.get("required")
            if type(props) is not dict or type(required) is not list or any(type(key) is not str for key in required):
                fail(path, "object properties and complete required list must be explicit")
            if len(required) != len(set(required)) or set(required) != set(props) or node.get("additionalProperties") is not False:
                fail(path, "every property must be required and additionalProperties must be false")
            value.update(properties={key: walk(child, path + "/properties/" + key, stack)
                                     for key, child in props.items()},
                         required=deepcopy(required), additionalProperties=False)
        elif {"required", "additionalProperties"} & set(node):
            fail(path, "object rules cannot be attached to a non-object")
        if node.get("type") == "array":
            if "items" not in node:
                fail(path, "array items must be explicit")
            value["items"] = walk(node["items"], path + "/items", stack)
        elif "items" in node:
            fail(path, "items requires array type")
        for operator in ("anyOf", "oneOf"):
            if operator not in node:
                continue
            if "anyOf" in node and "oneOf" in node:
                fail(path, "combined alternatives are not supported")
            if set(node) - {operator, "description", "$defs"}:
                fail(path, "alternative validation siblings are not supported")
            alternatives = node[operator]
            if type(alternatives) is not list or len(alternatives) < 2:
                fail(path, "at least two alternatives required")
            branches = [walk(child, path + "/" + operator + "/" + str(i), stack)
                        for i, child in enumerate(alternatives)]
            if operator == "oneOf":
                kinds = []
                for branch in branches:
                    kind = branch.get("properties", {}).get("kind", {})
                    enum = kind.get("enum", [])
                    if branch.get("type") != "object" or "kind" not in branch.get("required", []) or len(enum) != 1 or type(enum[0]) is not str:
                        fail(path, "oneOf must have a required singleton string kind discriminator")
                    kinds.append(enum[0])
                if len(set(kinds)) != len(kinds):
                    fail(path, "oneOf kind branches overlap")
                changes.append({"path": path, "operation": "disjoint_kind_oneOf_to_anyOf",
                                "discriminator": "kind", "values": kinds, "equivalent": True})
            value["anyOf"] = branches
        if not value:
            fail(path, "unconstrained schemas are not verified")
        return value

    # Inspect even unused definitions; unsupported/cyclic rules cannot hide.
    for name, definition in defs.items():
        walk(definition, "/$defs/" + name, (name,))
    service = walk(original, "/")
    Draft202012Validator.check_schema(service)
    # Repeated expansion changes are retained by path, not silently compressed.
    manifest = {"schema": VERSION + "/manifest", "original_contract_sha256": digest(original),
                "service_schema_sha256": digest(service), "transformations": changes,
                "local_only_keywords": sorted(REMOVED_CONSTRAINTS),
                "service_schema_is_weaker_than_local_contract": any(row["operation"] == "local_only_constraint" for row in changes),
                "original_local_contract_validation_required": True,
                "semantic_gate_changed": False, "original_contract_mutated": False}
    return service, manifest


def compile_source_schema(schema):
    return compile_source_schema_with_manifest(schema)[0]
