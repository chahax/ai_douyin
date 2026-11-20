"""Source-field scope coverage, without the independently audited commitments.

Every current beat G and ending G has a native observation row. Coverage,
quotation, identity and report consistency are checked deterministically;
whether the model extracted every human/operation remains unproved.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from . import creative_goal_drama_audit_contract_v10 as prior

VERSION = "creative_goal_drama_audit/v11"
DRAMA_AUDIT_VERSION = VERSION
SOURCE_AUDIT_VERSION = prior.SOURCE_AUDIT_VERSION
BUNDLE_VERSION = VERSION + "/audit_bundle"
GOAL_CHECKS = prior.GOAL_CHECKS
FINDING_KINDS = prior.FINDING_KINDS
OBSERVATION_TABLES = prior.OBSERVATION_TABLES
ScopeEvidenceContractError = prior.ScopeEvidenceContractError
digest, citations = prior.digest, prior.citations
build_evidence_catalog = prior.build_evidence_catalog
build_evidence_manifest = prior.build_evidence_manifest
build_commitment_usage_catalog = prior.build_commitment_usage_catalog


def _object(fields):
    return {"type": "object", "properties": fields,
            "required": list(fields), "additionalProperties": False}


def _context_identity(value):
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise ValueError("actual drama audit needs a lowercase SHA-256 context identity")


def build_scope_source_catalog(native_goal):
    """Exact current G paths, not keyword extraction or inferred operations."""
    catalog = build_evidence_catalog(native_goal)
    beats = native_goal["whole_plan"]["beats"]
    if not beats:
        raise ValueError("source-field scope needs complete actual beats")
    rows = {}
    for index, beat in enumerate(beats):
        path = f"whole_plan.beats.{index}."
        own = {ref: {"document_path": row["document_path"], "source_scope": "beat",
                     "beat_id": beat["id"]}
               for ref, row in catalog.items() if ref.startswith("G") and row["document_path"].startswith(path)}
        if not own:
            raise ValueError("each actual beat needs original G source fields")
        rows.update(own)
    ending = {ref: {"document_path": row["document_path"], "source_scope": "ending", "beat_id": None}
              for ref, row in catalog.items()
              if ref.startswith("G") and row["document_path"].startswith("whole_plan.ending.")}
    if not ending:
        raise ValueError("actual ending needs original G source fields")
    rows.update(ending)
    return rows


def build_production_scope_catalog(native_goal):
    result = deepcopy(prior.build_production_scope_catalog(native_goal))
    result["source_scopes"] = build_scope_source_catalog(native_goal)
    return result


def _scope_schema(native_goal):
    scopes = build_production_scope_catalog(native_goal)
    rows = {}
    for ref in scopes["source_scopes"]:
        # Vocabulary and array/object shape are shared; the intersection only
        # narrows source_ref to this exact row. No native fields are omitted.
        rows[ref] = {"allOf": [{"$ref": "#/$defs/scope_source_observations"},
            {"properties": {table: {"items": {"properties": {"source_ref": {"const": ref}}}}
                            for table, _ in OBSERVATION_TABLES.values()}}]}
    return _object(rows)


def _scope_definitions(native_goal):
    scopes = build_production_scope_catalog(native_goal)
    common = {"source_ref": {"type": "string"},
              "quote": {"type": "string", "minLength": 1, "pattern": r"\S"}}
    definitions = {
        "scope_source_ref": {"enum": list(scopes["source_scopes"])},
        "scope_voice_observation": _object({**deepcopy(common),
            "declared_character_id": {"enum": [*scopes["declared_actor_ids"], None]}}),
        "scope_prop_observation": _object({**deepcopy(common),
            "declared_prop_id": {"enum": [*scopes["declared_prop_ids"], None]}}),
    }
    definitions["scope_source_observations"] = _object({
        "audible_speakers": {"type": "array", "items": {"$ref": "#/$defs/scope_voice_observation"}, "uniqueItems": True},
        "operated_props": {"type": "array", "items": {"$ref": "#/$defs/scope_prop_observation"}, "uniqueItems": True},
    })
    return definitions


def _finding_schema(native_goal):
    catalog = build_evidence_catalog(native_goal)
    scopes = build_production_scope_catalog(native_goal)
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    common = {"source_ref": {"$ref": "#/$defs/scope_source_ref"},
              "quote": deepcopy(text), "explanation": deepcopy(text)}
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
        direct = {**deepcopy(common), "entity_label": deepcopy(text), "declared_entity_id": {"type": "null"}}
        variants.append(_object({"kind": {"const": "undeclared_" + kind},
                                 "status": {"const": "fail"}, **deepcopy(direct)}))
        variants.append(_object({"kind": {"const": "uncertain_identity"},
                                 "status": {"const": "unknown"}, "entity_kind": {"const": kind},
                                 **deepcopy(direct)}))
    quote = _object({"source_ref": {"$ref": "#/$defs/evidence_refs/items"}, "quote": deepcopy(text)})
    entity_ids = {"actor": scopes["declared_actor_ids"], "prop": scopes["declared_prop_ids"],
                  "scene": scopes["declared_scene_ids"]}
    for kind, identifiers in entity_ids.items():
        if identifiers:
            variants.append(_object({"kind": {"const": "explicit_state_contradiction"},
                "status": {"const": "fail"}, "entity_kind": {"const": kind},
                "entity_id": {"enum": identifiers}, "explanation": deepcopy(text),
                "evidence": {"type": "array", "items": deepcopy(quote), "minItems": 2,
                             "maxItems": len(catalog), "uniqueItems": True}}))
    return {"type": "array", "items": {"oneOf": variants}, "uniqueItems": True,
            "maxItems": len(catalog) * len(FINDING_KINDS)}


def build_drama_schema(native_goal, *, context_sha256):
    _context_identity(context_sha256)
    schema = deepcopy(prior.build_drama_schema(native_goal, context_sha256=context_sha256))
    schema["properties"]["schema"] = {"const": DRAMA_AUDIT_VERSION}
    schema["properties"].pop("commitment_checks")
    schema["required"].remove("commitment_checks")
    schema["$defs"].pop("commitment_judgment", None)
    schema["$defs"].update(_scope_definitions(native_goal))
    schema["properties"]["scope_observations"] = _scope_schema(native_goal)
    schema["properties"]["closed_scope_findings"] = _finding_schema(native_goal)
    Draft202012Validator.check_schema(schema)
    return schema


def _scope_evidence(document, native_goal):
    catalog = build_evidence_catalog(native_goal)
    sources = build_scope_source_catalog(native_goal)
    compiled, undeclared = {}, []
    for ref, observations in document["scope_observations"].items():
        compiled[ref] = {}
        for table, field in OBSERVATION_TABLES.values():
            rows = []
            for index, observed in enumerate(observations[table]):
                if observed["source_ref"] != ref:
                    raise ScopeEvidenceContractError(f"/scope_observations/{ref}/{table}/{index}",
                        "observation must use its exact current source field")
                if not observed["quote"].strip() or observed["quote"] not in catalog[ref]["quote"]:
                    raise ScopeEvidenceContractError(f"/scope_observations/{ref}/{table}/{index}/quote",
                        "scope quote must occur verbatim in its exact native G source", source_ref=ref)
                rows.append({**deepcopy(observed), **deepcopy(sources[ref]),
                             "original_quote": catalog[ref]["quote"]})
                if observed[field] is None:
                    undeclared.append({"source_ref": ref, "table": table, "observation_index": index,
                                       **deepcopy(observed)})
            compiled[ref][table] = rows
    return compiled, undeclared


def _closed_scope_evidence(document, native_goal):
    catalog = build_evidence_catalog(native_goal)
    scopes = build_production_scope_catalog(native_goal)
    closed = document["goal_checks"]["closed_production_scope"]
    checked = set(closed["evidence_refs"] + closed["counterevidence_refs"])
    compiled, covered, subjects = [], set(), set()

    def quotation(ref, quote, path):
        if ref not in checked:
            raise ScopeEvidenceContractError(path, "typed finding evidence must be checked by closed scope", source_ref=ref)
        if not quote.strip() or quote not in catalog[ref]["quote"]:
            raise ScopeEvidenceContractError(path, "quotation must occur verbatim in exact current C/G source", source_ref=ref)
        return {"source_ref": ref, "quote": quote,
                "document_path": catalog[ref]["document_path"], "original_quote": catalog[ref]["quote"]}

    for index, finding in enumerate(document["closed_scope_findings"]):
        path = f"/closed_scope_findings/{index}"
        kind = finding["kind"]
        result = deepcopy(finding)
        if kind == "explicit_state_contradiction":
            refs = [item["source_ref"] for item in finding["evidence"]]
            if len(set(refs)) != len(refs):
                raise ScopeEvidenceContractError(path + "/evidence", "state contradiction requires distinct current sources")
            result["evidence"] = [quotation(item["source_ref"], item["quote"], path + f"/evidence/{i}")
                                  for i, item in enumerate(finding["evidence"])]
            subject = (kind, finding["entity_kind"], finding["entity_id"], tuple(sorted(refs)))
        else:
            entity_kind = finding["entity_kind"] if kind == "uncertain_identity" else kind.removeprefix("undeclared_")
            ref = finding["source_ref"]
            result["evidence"] = [quotation(ref, finding["quote"], path)]
            if entity_kind in OBSERVATION_TABLES:
                table, field = OBSERVATION_TABLES[entity_kind]
                pointer = (ref, table, finding["observation_index"])
                observed_rows = document["scope_observations"][ref][table]
                if pointer[2] >= len(observed_rows):
                    raise ScopeEvidenceContractError(path + "/observation_index", "finding needs an existing exact source observation")
                observed = observed_rows[pointer[2]]
                if (observed["source_ref"], observed["quote"]) != (ref, finding["quote"]):
                    raise ScopeEvidenceContractError(path, "finding source/quote must match its indexed observation exactly")
                if observed[field] is not None:
                    raise ScopeEvidenceContractError(path, "known declared identity cannot be reported as undeclared or uncertain",
                                                     declared_id=observed[field])
                covered.add(pointer)
                result["observation_path"] = f"/scope_observations/{ref}/{table}/{pointer[2]}"
                subject = pointer
            else:
                identifiers = scopes["declared_actor_ids"] if entity_kind == "visible_actor" else scopes["declared_scene_ids"]
                if finding["entity_label"] in identifiers:
                    raise ScopeEvidenceContractError(path + "/entity_label", "known declared ID cannot be classified as undeclared or uncertain")
                subject = (ref, entity_kind, finding["entity_label"])
        if subject in subjects:
            raise ScopeEvidenceContractError(path, "same observed entity or state contradiction cannot be classified twice")
        subjects.add(subject)
        compiled.append(result)
    expected = "fail" if any(row["status"] == "fail" for row in compiled) else "unknown" if compiled else "pass"
    if closed["status"] != expected:
        raise ScopeEvidenceContractError("/goal_checks/closed_production_scope/status",
                                        "closed scope must match its native typed findings", expected_status=expected)
    for ref, observations in document["scope_observations"].items():
        for table, field in OBSERVATION_TABLES.values():
            for index, observation in enumerate(observations[table]):
                if observation[field] is None and (ref, table, index) not in covered:
                    raise ScopeEvidenceContractError(f"/scope_observations/{ref}/{table}/{index}",
                        "null observation needs an undeclared or uncertain typed finding")
    return compiled


def validate_drama(document, native_goal, *, context_sha256):
    Draft202012Validator(build_drama_schema(native_goal, context_sha256=context_sha256)).validate(document)
    catalog = build_evidence_catalog(native_goal)
    scope_evidence, undeclared = _scope_evidence(document, native_goal)
    closed_evidence = _closed_scope_evidence(document, native_goal)
    evidence, counters, failures, uncertainties = {}, {}, [], []
    for key, row in document["goal_checks"].items():
        refs = list(dict.fromkeys(row["evidence_refs"] + row["counterevidence_refs"]))
        evidence[key] = [{"source_ref": ref, **deepcopy(catalog[ref])} for ref in refs]
        counters[key] = [{"source_ref": ref, **deepcopy(catalog[ref])} for ref in row["counterevidence_refs"]]
        finding = {"target": "complete_native_goal", "audit_kind": "drama", "table": "goal_checks",
                   "check": key, **deepcopy(row), "evidence": deepcopy(evidence[key])}
        if key == "closed_production_scope":
            finding.update(closed_scope_findings=deepcopy(document["closed_scope_findings"]),
                           closed_scope_finding_evidence=deepcopy(closed_evidence))
        if row["status"] == "fail": failures.append(finding)
        elif row["status"] == "unknown": uncertainties.append(finding)
    return {"valid": True, "accepted": not failures and not uncertainties,
        "findings": failures, "uncertainties": uncertainties, "citations": evidence,
        "counterevidence_citations": counters, "scope_observation_evidence": scope_evidence,
        "undeclared_scope_observations": undeclared,
        "closed_scope_findings": deepcopy(document["closed_scope_findings"]),
        "closed_scope_finding_evidence": closed_evidence, "closed_scope_report_self_consistent": True,
        "scope_source_catalog": build_scope_source_catalog(native_goal), "scope_source_coverage_complete": True,
        "scope_observations_complete_extraction_proven": False, "audit_kind": "drama",
        "native_goal_sha256": digest(native_goal), "audit_sha256": digest(document),
        "audit_context_sha256": context_sha256, "native_review_modified": False,
        "citation_metadata_compiled": True, "evidence_catalog_count": len(catalog),
        "commitments_reviewed_in_this_packet": False,
        "semantic_truth_deterministically_proven": False, "human_approved": False}


def build_bundle(native_source_audit, native_drama_audit):
    return {"schema": BUNDLE_VERSION, "native_source_audit": deepcopy(native_source_audit),
            "native_drama_audit": deepcopy(native_drama_audit)}


def validate_bundle(bundle, native_goal, *, source_context_sha256, drama_context_sha256):
    _context_identity(source_context_sha256)
    _context_identity(drama_context_sha256)
    if source_context_sha256 == drama_context_sha256:
        raise ValueError("source/drama audits need distinct actual payload identities")
    if (type(bundle) is not dict or set(bundle) != {"schema", "native_source_audit", "native_drama_audit"}
            or bundle["schema"] != BUNDLE_VERSION):
        raise ValueError("v11 requires two complete current native documents, never a converted old bundle")
    source = prior.prior.validate_goal_source_audit(bundle["native_source_audit"], native_goal,
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
