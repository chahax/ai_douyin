"""Native typed closed-scope evidence; frozen v9 responses are never converted.

The model owns extraction and meaning. This validator checks exact current
quotations, declared identities, and its report's structural self-consistency.
It has no provider or dispatch capability and does not interpret reason prose.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from . import creative_goal_drama_audit_contract_v9 as base

VERSION = "creative_goal_drama_audit/v10"
DRAMA_AUDIT_VERSION = VERSION
SOURCE_AUDIT_VERSION = base.SOURCE_AUDIT_VERSION
BUNDLE_VERSION = VERSION + "/audit_bundle"
GOAL_CHECKS = base.GOAL_CHECKS
digest, citations, prior = base.digest, base.citations, base.prior
build_evidence_catalog = base.build_evidence_catalog
build_evidence_manifest = base.build_evidence_manifest
build_commitment_usage_catalog = base.build_commitment_usage_catalog

FINDING_KINDS = (
    "undeclared_voice", "undeclared_prop", "undeclared_visible_actor",
    "undeclared_scene", "uncertain_identity", "explicit_state_contradiction",
)
OBSERVATION_TABLES = {
    "voice": ("audible_speakers", "declared_character_id"),
    "prop": ("operated_props", "declared_prop_id"),
}


class ScopeEvidenceContractError(ValueError):
    """A known audit evidence defect, not a planning-content finding."""

    code = "CLOSED_SCOPE_EVIDENCE_CONTRACT_REJECTED"

    def __init__(self, path, message, **details):
        self.diagnostics = [{"code": self.code, "path": path, "message": message, **details}]
        super().__init__(f"{self.code}: {path}: {message}")


def _object(fields):
    return base.base._object(fields)


def build_production_scope_catalog(native_goal):
    """Retain exact v9 IDs/beat evidence and add the actual scene registry."""
    result = deepcopy(base.build_production_scope_catalog(native_goal))
    scene_ids = [row["id"] for row in native_goal["whole_plan"].get("scenes", [])]
    if (any(type(value) is not str or not value.strip() for value in scene_ids)
            or len(scene_ids) != len(set(scene_ids))):
        raise ValueError("actual native scenes need unique nonempty IDs")
    result["declared_scene_ids"] = scene_ids
    return result


def _finding_schema(native_goal):
    catalog = build_evidence_catalog(native_goal)
    scopes = build_production_scope_catalog(native_goal)
    nonempty = {"type": "string", "minLength": 1, "pattern": r"\S"}
    own_g = [ref for scope in scopes["beat_scopes"].values() for ref in scope["evidence_refs"]]
    common = {"beat_id": {"enum": list(scopes["beat_scopes"])},
              "source_ref": {"enum": own_g}, "quote": deepcopy(nonempty),
              "explanation": deepcopy(nonempty)}
    variants = []
    for kind, (table, _) in OBSERVATION_TABLES.items():
        observation = {**deepcopy(common), "table": {"const": table},
                       "observation_index": {"type": "integer", "minimum": 0}}
        variants.append(_object({"kind": {"const": "undeclared_" + kind},
                                 "status": {"const": "fail"}, **deepcopy(observation)}))
        variants.append(_object({"kind": {"const": "uncertain_identity"},
                                 "status": {"const": "unknown"}, "entity_kind": {"const": kind},
                                 **deepcopy(observation)}))
    for kind in ("visible_actor", "scene"):
        direct = {**deepcopy(common), "entity_label": deepcopy(nonempty),
                  "declared_entity_id": {"type": "null"}}
        variants.append(_object({"kind": {"const": "undeclared_" + kind},
                                 "status": {"const": "fail"}, **deepcopy(direct)}))
        variants.append(_object({"kind": {"const": "uncertain_identity"},
                                 "status": {"const": "unknown"}, "entity_kind": {"const": kind},
                                 **deepcopy(direct)}))
    entity_ids = {"actor": scopes["declared_actor_ids"], "prop": scopes["declared_prop_ids"],
                  "scene": scopes["declared_scene_ids"]}
    quote = _object({"source_ref": {"enum": list(catalog)}, "quote": deepcopy(nonempty)})
    # A finite type/identity pair prevents an actor ID from being used as a prop.
    for kind, identifiers in entity_ids.items():
        if not identifiers:
            continue
        variants.append(_object({"kind": {"const": "explicit_state_contradiction"},
            "status": {"const": "fail"}, "entity_kind": {"const": kind},
            "entity_id": {"enum": identifiers}, "explanation": deepcopy(nonempty),
            "evidence": {"type": "array", "items": deepcopy(quote), "minItems": 2,
                         "maxItems": len(catalog), "uniqueItems": True}}))
    return {"type": "array", "items": {"oneOf": variants}, "uniqueItems": True,
            "maxItems": len(catalog) * len(FINDING_KINDS)}


def build_drama_schema(native_goal, *, context_sha256):
    """All v9 C/G, commitments, and scope tables remain required and exact."""
    schema = base.build_drama_schema(native_goal, context_sha256=context_sha256)
    schema["properties"]["schema"] = {"const": DRAMA_AUDIT_VERSION}
    schema["properties"]["closed_scope_findings"] = _finding_schema(native_goal)
    schema["required"].append("closed_scope_findings")
    Draft202012Validator.check_schema(schema)
    return schema


def _closed_scope_evidence(document, native_goal):
    catalog = build_evidence_catalog(native_goal)
    scopes = build_production_scope_catalog(native_goal)
    closed = document["goal_checks"]["closed_production_scope"]
    checked_refs = set(closed["evidence_refs"] + closed["counterevidence_refs"])
    compiled, covered, subjects = [], set(), set()

    def quotation(ref, quote, path):
        if ref not in checked_refs:
            raise ScopeEvidenceContractError(path, "typed finding evidence must be checked by the closed-scope judgment",
                                             source_ref=ref)
        original = catalog[ref]
        if not quote.strip() or quote not in original["quote"]:
            raise ScopeEvidenceContractError(path, "quotation must occur verbatim in the exact current C/G source",
                                             source_ref=ref)
        return {"source_ref": ref, "quote": quote, "document_path": original["document_path"],
                "original_quote": original["quote"]}

    for index, finding in enumerate(document["closed_scope_findings"]):
        path = f"/closed_scope_findings/{index}"
        kind = finding["kind"]
        result = deepcopy(finding)
        if kind == "explicit_state_contradiction":
            refs = [item["source_ref"] for item in finding["evidence"]]
            if len(set(refs)) != len(refs):
                raise ScopeEvidenceContractError(path + "/evidence", "state contradiction needs at least two distinct current C/G sources")
            result["evidence"] = [quotation(item["source_ref"], item["quote"], path + f"/evidence/{i}")
                                  for i, item in enumerate(finding["evidence"])]
            subject = (kind, finding["entity_kind"], finding["entity_id"], tuple(sorted(refs)))
        else:
            entity_kind = finding["entity_kind"] if kind == "uncertain_identity" else kind.removeprefix("undeclared_")
            beat_id, ref = finding["beat_id"], finding["source_ref"]
            if ref not in scopes["beat_scopes"][beat_id]["evidence_refs"]:
                raise ScopeEvidenceContractError(path + "/source_ref", "scope finding must use its own actual beat G evidence")
            result["evidence"] = [quotation(ref, finding["quote"], path)]
            if entity_kind in OBSERVATION_TABLES:
                table, field = OBSERVATION_TABLES[entity_kind]
                pointer = (beat_id, table, finding["observation_index"])
                observations = document["scope_observations"][beat_id][table]
                if pointer[2] >= len(observations):
                    raise ScopeEvidenceContractError(path + "/observation_index", "finding must bind an existing observation; reviewer omissions are not planning defects")
                observed = observations[pointer[2]]
                if (observed["source_ref"], observed["quote"]) != (ref, finding["quote"]):
                    raise ScopeEvidenceContractError(path, "finding source and quote must exactly match its own indexed observation")
                if observed[field] is not None:
                    raise ScopeEvidenceContractError(path, "known declared identity cannot be reported as undeclared or uncertain",
                                                     declared_id=observed[field], observation_path=f"/scope_observations/{beat_id}/{table}/{pointer[2]}")
                covered.add(pointer)
                result["observation_path"] = f"/scope_observations/{beat_id}/{table}/{pointer[2]}"
                subject = pointer
            else:
                # Equality checks only: no inference about aliases, names, or
                # whether a passage semantically introduces another entity.
                ids = scopes["declared_actor_ids"] if entity_kind == "visible_actor" else scopes["declared_scene_ids"]
                if finding["entity_label"] in ids:
                    raise ScopeEvidenceContractError(path + "/entity_label", "known declared ID cannot be reported as undeclared or uncertain")
                subject = (beat_id, entity_kind, ref, finding["entity_label"])
        if subject in subjects:
            raise ScopeEvidenceContractError(path, "same observed entity or contradiction cannot be classified twice")
        subjects.add(subject)
        compiled.append(result)

    expected = "fail" if any(row["status"] == "fail" for row in compiled) else "unknown" if compiled else "pass"
    if closed["status"] != expected:
        raise ScopeEvidenceContractError("/goal_checks/closed_production_scope/status",
                                         "closed-scope judgment must match its native typed findings", expected_status=expected)
    for beat_id, observations in document["scope_observations"].items():
        for table, field in OBSERVATION_TABLES.values():
            for index, observation in enumerate(observations[table]):
                if observation[field] is None and (beat_id, table, index) not in covered:
                    raise ScopeEvidenceContractError(f"/scope_observations/{beat_id}/{table}/{index}",
                                                     "null scope observation needs an undeclared or uncertain typed finding")
    return compiled


def validate_drama(document, native_goal, *, context_sha256):
    Draft202012Validator(build_drama_schema(native_goal, context_sha256=context_sha256)).validate(document)
    catalog = build_evidence_catalog(native_goal)
    scope_evidence, undeclared = base._scope_evidence(document, native_goal)
    closed_scope_evidence = _closed_scope_evidence(document, native_goal)
    usage_catalog = build_commitment_usage_catalog(native_goal)
    evidence, counterevidence, commitment_evidence = {}, {}, {}
    failures, uncertainties = [], []
    for table in ("goal_checks", "commitment_checks"):
        for key, row in document[table].items():
            if not row["counterexample_analysis"].strip():
                raise ValueError("drama checks need substantive comparison for counterexamples")
            refs = list(dict.fromkeys(row["evidence_refs"] + row["counterevidence_refs"]))
            quoted = [deepcopy(catalog[ref]) for ref in refs]
            counters = [deepcopy(catalog[ref]) for ref in row["counterevidence_refs"]]
            if table == "goal_checks":
                evidence[key], counterevidence[key] = quoted, counters
            else:
                commitment_evidence[key] = {"claim_ref": row["claim_ref"], "evidence": quoted,
                    "counterevidence": counters, "checked_usages": {
                        usage: [deepcopy(catalog[ref]) for ref in checked]
                        for usage, checked in row["checked_usages"].items()}}
            finding = {"target": "complete_native_goal", "audit_kind": "drama", "table": table,
                       "check": key, **deepcopy(row), "evidence": quoted}
            if table == "goal_checks" and key == "closed_production_scope":
                finding["closed_scope_findings"] = deepcopy(document["closed_scope_findings"])
                finding["closed_scope_finding_evidence"] = deepcopy(closed_scope_evidence)
            if row["status"] == "fail":
                failures.append(finding)
            elif row["status"] == "unknown":
                uncertainties.append(finding)
    return {"valid": True, "accepted": not failures and not uncertainties,
        "findings": failures, "uncertainties": uncertainties, "citations": evidence,
        "counterevidence_citations": counterevidence,
        "commitment_check_evidence": commitment_evidence,
        "commitment_usage_catalog": usage_catalog, "commitment_usage_coverage_complete": True,
        "commitment_semantic_extraction_proven": False,
        "scope_observation_evidence": scope_evidence, "undeclared_scope_observations": undeclared,
        "closed_scope_findings": deepcopy(document["closed_scope_findings"]),
        "closed_scope_finding_evidence": closed_scope_evidence,
        "closed_scope_report_self_consistent": True,
        "scope_observations_complete_extraction_proven": False, "audit_kind": "drama",
        "native_goal_sha256": digest(native_goal), "audit_sha256": digest(document),
        "audit_context_sha256": context_sha256, "native_review_modified": False,
        "citation_metadata_compiled": True, "evidence_catalog_count": len(catalog),
        "semantic_truth_deterministically_proven": False, "human_approved": False}


def build_bundle(native_source_audit, native_drama_audit):
    return {"schema": BUNDLE_VERSION, "native_source_audit": deepcopy(native_source_audit),
            "native_drama_audit": deepcopy(native_drama_audit)}


def validate_bundle(bundle, native_goal, *, source_context_sha256, drama_context_sha256):
    base.base._context_identity(source_context_sha256)
    base.base._context_identity(drama_context_sha256)
    if source_context_sha256 == drama_context_sha256:
        raise ValueError("source and drama audits need their distinct actual payload identities")
    if (type(bundle) is not dict or set(bundle) != {"schema", "native_source_audit", "native_drama_audit"}
            or bundle["schema"] != BUNDLE_VERSION):
        raise ValueError("v10 bundle requires two complete native audit documents; no old bundle conversion")
    source = prior.validate_goal_source_audit(bundle["native_source_audit"], native_goal,
                                             context_sha256=source_context_sha256)
    drama = validate_drama(bundle["native_drama_audit"], native_goal, context_sha256=drama_context_sha256)
    return {"valid": True, "accepted": source["accepted"] and drama["accepted"],
        "findings": source["findings"] + drama["findings"],
        "uncertainties": source["uncertainties"] + drama["uncertainties"],
        "source_decision": source, "drama_decision": drama,
        "native_goal_sha256": digest(native_goal), "audit_sha256": digest(bundle),
        "source_context_sha256": source_context_sha256, "drama_context_sha256": drama_context_sha256,
        "native_review_modified": False, "combined_decisions_only": True,
        "native_single_combined_audit": False, "human_approved": False,
        "semantic_truth_deterministically_proven": False}
