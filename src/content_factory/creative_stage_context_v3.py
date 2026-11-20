"""Independent functional context projection, exact origin aliases and provenance.

Historical user quotations and an explicitly identified optional story strategy
remain local evidence. Complete law facts, sources, applicability and the current
script are never abbreviated. No client, filesystem, grant or service is used.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from . import creative_stage_context_v2 as prior

VERSION = "creative_stage_context/v3"
ContextError = prior.ContextError
STAGES = prior.STAGES
DEFAULT_POLICY = prior.DEFAULT_POLICY
_measure, _digest = prior._measure, prior._digest
_reference_occurrences = prior._reference_occurrences

_STRATEGY_PREFIX = "虚构事件中的当事人先保留真实书面事实、核对解除性质；"
_STRATEGY_ONLY = "当事人先保留真实书面事实、核对解除性质"
_GROUP_AUTHORITY = {"platform_metadata": "metadata_only",
                    "verified_legal": "verified_legal_with_conditions"}


def _text_identity(text):
    return {"characters": len(text), "utf8_bytes": len(text.encode("utf-8")),
            "utf8_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "semantic_sha256": _digest(text)}


def _remove_user_quotes(value, path, transformations):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            child_path = path + "." + key
            if key == "source_quote":
                if not isinstance(child, str):
                    raise ContextError(child_path + " must be original text")
                transformations.append({"source_path": child_path,
                    "disposition": "local_provenance_only", "category": "historical_user_quote",
                    "reason": "the functional user-goal text enters the model; the historical case wording stays local",
                    "original_text": child, "original_identity": _text_identity(child),
                    "projected_path": None})
            else:
                result[key] = _remove_user_quotes(child, child_path, transformations)
        return result
    if isinstance(value, list):
        return [_remove_user_quotes(child, path + "." + str(index), transformations)
                for index, child in enumerate(value)]
    return deepcopy(value)


def _user_projection(value, transformations):
    prior._object(value, "user_goal_contract")
    for table in ("constraints", "audience_goals"):
        rows = value.get(table)
        if type(rows) is not list or not rows:
            raise ContextError("user_goal_contract." + table + " requires functional goal rows")
        for index, row in enumerate(rows):
            path = f"user_goal_contract.{table}.{index}"
            prior._object(row, path)
            if not isinstance(row.get("id"), str) or not row["id"].strip():
                raise ContextError(path + ".id must be a readable nonblank identity")
            if not isinstance(row.get("text"), str) or not row["text"].strip():
                raise ContextError(path + ".text requires the already functionalized user goal")
    return _remove_user_quotes(value, "user_goal_contract", transformations)


def _legal_projection(value, transformations):
    result = deepcopy(prior._object(value, "verified_legal_context"))
    for key in ("facts", "sources"):
        if type(result.get(key)) is not list or not result[key] or any(type(row) is not dict or not row for row in result[key]):
            raise ContextError("verified_legal_context." + key + " requires complete nonempty source rows")
    boundaries = result.get("creative_boundaries")
    if boundaries is None:
        return result
    if type(boundaries) is not list or any(not isinstance(item, str) or not item.strip() for item in boundaries):
        raise ContextError("verified_legal_context.creative_boundaries must be nonblank original text rows")
    retained = []
    for index, original in enumerate(boundaries):
        source_path = f"verified_legal_context.creative_boundaries.{index}"
        strategy, text = None, original
        if original.startswith(_STRATEGY_PREFIX):
            strategy, text = _STRATEGY_PREFIX, original[len(_STRATEGY_PREFIX):]
            if not text.strip():
                raise ContextError(source_path + " strategy prefix requires its complete remaining boundary")
        elif original.rstrip("。") == _STRATEGY_ONLY:
            strategy, text = original, None
        projected_path = f"verified_legal_context.creative_boundaries.{len(retained)}" if text is not None else None
        if text is not None:
            retained.append(text)
        row = {"source_path": source_path,
               "disposition": "optional_strategy_local_only" if strategy is not None else "retained_unchanged",
               "category": "legal_context_boundary",
               "reason": "only the explicitly identified story strategy is withheld; remaining truthfulness/conditions stay exact" if strategy is not None else "not an identified removable story strategy; original boundary and any law conditions stay complete",
               "original_text": original, "original_identity": _text_identity(original),
               "projected_path": projected_path, "projected_text": text,
               "projected_identity": _text_identity(text) if text is not None else None}
        if strategy is not None:
            row["optional_strategy"] = {"original_text": strategy,
                                        "original_identity": _text_identity(strategy),
                                        "authority": "optional_creative_strategy_not_mandatory_legal_step"}
        transformations.append(row)
    result["creative_boundaries"] = retained
    # Explicitly prove this selective projection cannot rewrite legal values.
    for key, original in value.items():
        if key != "creative_boundaries" and result[key] != original:
            raise ContextError("legal source or applicability condition changed: " + key)
    return result


def _catalog(payload, original_source):
    source = payload["source_packet"]
    candidates = []
    tables = (("tag_observations", "tag_catalog", "tag_id", "label"),
              ("selected_relations", "selected_relations", "edge_id", "relation_basis"),
              ("selected_tag_families", "selected_tag_families", "family_id", "label"),
              ("representative_metadata", "representative_metadata", "item_id", "title"))
    for target_key, source_key, id_key, text_key in tables:
        originals = {row[id_key]: (index, row) for index, row in enumerate(original_source.get(source_key, []))}
        for index, row in enumerate(source[target_key]):
            original_id = row[id_key]
            original_index, original = originals[original_id]
            actual_text_key = text_key
            if target_key == "selected_relations" and not isinstance(row.get(text_key), str):
                actual_text_key = "relation_kind"
            text = row.get(actual_text_key)
            candidates.append((original_id, {"path": f"source_packet.{target_key}.{index}",
                "original_id": original_id, "authority": "metadata_only",
                "text": text if isinstance(text, str) else None,
                "text_path": f"source_packet.{target_key}.{index}.{actual_text_key}" if isinstance(text, str) else None},
                {"original_source_path": f"source_packet.{source_key}.{original_index}",
                 "original_source_identity": _measure(original)}))
    original_id = source["candidate"]["candidate_id"]
    text = source["candidate"].get("title")
    candidates.append((original_id, {"path": "source_packet.candidate", "original_id": original_id,
        "authority": "metadata_only", "text": text if isinstance(text, str) else None,
        "text_path": "source_packet.candidate.title" if isinstance(text, str) else None},
        {"original_source_path": "source_packet.candidate",
         "original_source_identity": _measure(original_source["candidate"])}))
    if len(candidates) != len({row[0] for row in candidates}):
        raise ContextError("platform origin identities overlap across catalog groups")
    platform, mappings = {}, []
    for index, (_, entry, local) in enumerate(sorted(candidates, key=lambda row: row[0]), 1):
        alias = "S" + str(index).zfill(3)
        platform[alias] = entry
        mappings.append({"alias": alias, "group": "platform_metadata", **deepcopy(entry), **local})
    legal = {"L" + str(index + 1).zfill(3): {
        "path": f"verified_legal_context.facts.{index}",
        "original_id": "L" + str(index + 1).zfill(3), "authority": "verified_legal_with_conditions"}
        for index, _ in enumerate(payload["verified_legal_context"].get("facts", []))}
    if not legal:
        raise ContextError("verified_legal_context requires complete nonempty facts")
    user = {}
    for table, authority in (("constraints", "user_constraint"), ("audience_goals", "user_audience_goal")):
        for index, row in enumerate(payload["user_goal_contract"][table]):
            if row["id"] in user or row["id"] in platform or row["id"] in legal:
                raise ContextError("user origin catalog contains a duplicate or ambiguous identity")
            user[row["id"]] = {"path": f"user_goal_contract.{table}.{index}",
                              "original_id": row["id"], "authority": authority}
    return {"platform_metadata": platform, "verified_legal": legal, "user": user}, mappings


def _validate_catalog(catalog):
    prior._object(catalog, "origin_catalog")
    if set(catalog) != {"platform_metadata", "verified_legal", "user"}:
        raise ContextError("origin_catalog must use the three explicit authority groups")
    seen = set()
    for group, entries in catalog.items():
        prior._object(entries, "origin_catalog." + group)
        for alias, entry in entries.items():
            if alias in seen or not isinstance(alias, str) or not alias:
                raise ContextError("origin aliases must be exact, distinct nonempty identities")
            seen.add(alias)
            prior._object(entry, "origin_catalog." + group + "." + alias)
            if any(not isinstance(entry.get(key), str) or not entry[key] for key in ("path", "original_id", "authority")):
                raise ContextError("origin alias requires exact original_id/path/authority")
            if group == "platform_metadata" and (not re.fullmatch(r"S[0-9]{3,}", alias) or int(alias[1:]) < 1):
                raise ContextError("platform origins require exact short S aliases")
            allowed = {"user_constraint", "user_audience_goal"} if group == "user" else {_GROUP_AUTHORITY[group]}
            if entry["authority"] not in allowed:
                raise ContextError("origin alias authority does not match its group")


def alias_origin_ids(catalog):
    """Return exact contract enums. No opaque-ID, case or approximate fallback."""
    _validate_catalog(catalog)
    return {"source_ids": list(catalog["platform_metadata"]),
            "legal_ids": list(catalog["verified_legal"]),
            "user_constraint_ids": list(catalog["user"])}


def resolve_origin_alias(catalog, alias):
    """Resolve one model-native alias to its supplied source, without rewriting it."""
    _validate_catalog(catalog)
    if not isinstance(alias, str):
        raise ContextError("origin alias must be an exact string")
    for group, entries in catalog.items():
        if alias in entries:
            return {"group": group, **deepcopy(entries[alias])}
    raise ContextError("unknown exact origin alias: " + alias)


def build_stage_context(stage, inputs):
    """Return {payload, manifest}; manifest.provenance_manifest is local only.

    Only payload belongs in provider messages. Goal/schema validation must use
    alias_origin_ids(payload['origin_catalog']); original IDs are not substitutes.
    Original input objects, all legal facts and the complete current script stay
    untouched. Freshness, authorization and semantic acceptance remain external.
    """
    prior._object(inputs, "inputs")
    prior._unknown(inputs, prior.INPUT_KEYS, "inputs")
    for key in ("user_goal_contract", "verified_legal_context", "source_packet"):
        if key not in inputs:
            raise ContextError("stage requires " + key)
    original_measure = _measure(inputs)
    projected_inputs, transformations = deepcopy(inputs), []
    projected_inputs["user_goal_contract"] = _user_projection(inputs["user_goal_contract"], transformations)
    projected_inputs["verified_legal_context"] = _legal_projection(inputs["verified_legal_context"], transformations)
    built = prior.build_stage_context(stage, projected_inputs)
    payload, manifest = built["payload"], built["manifest"]
    payload["source_packet"]["schema"] = VERSION + "/selected_source"
    catalog, mappings = _catalog(payload, inputs["source_packet"])
    _validate_catalog(catalog)
    payload["origin_catalog"] = catalog
    for row in manifest["field_manifest"]:
        if row["path"] in ("user_goal_contract", "verified_legal_context"):
            key = row["path"]
            row.update(disposition="projected", original=_measure(inputs[key]),
                       projected=_measure(payload[key]),
                       reason="functional model context; exact historical text/optional strategy retained in local provenance")
    manifest["field_manifest"].append({"path": "origin_catalog", "disposition": "derived",
        "reason": "exact short platform aliases map to unchanged actual source paths and identities",
        "projected": _measure(catalog)})
    for row in transformations:
        manifest["field_manifest"].append({"path": row["source_path"],
            "disposition": row["disposition"], "reason": row["reason"],
            "original": row["original_identity"], "projected_path": row["projected_path"]})
    policy, measure = manifest["context_policy"], _measure(payload)
    if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
        raise ContextError("alias context exceeds explicit safety budget; no content truncated")
    if _reference_occurrences(payload, inputs["reference_fulltext"]) != 1:
        raise ContextError("complete reference must enter actual payload exactly once")
    protected = {key: _measure(value) for key, value in inputs["verified_legal_context"].items()
                 if key != "creative_boundaries"}
    for key in protected:
        if payload["verified_legal_context"][key] != inputs["verified_legal_context"][key]:
            raise ContextError("complete legal value changed: " + key)
    manifest.update(schema=VERSION + "/manifest", input_identity=original_measure,
        payload_identity=measure, source_projection_output_sha256=_digest(payload["source_packet"]),
        origin_catalog_sha256=_digest(catalog), native_aliases_rewritten=False,
        legal_full_values_unchanged=protected,
        provenance_manifest={"schema": VERSION + "/local_provenance", "enters_provider_messages": False,
            "original_input_identity": original_measure, "transformations": transformations,
            "platform_alias_mappings": mappings,
            "scope": "original historical quotes and optional creative strategy, not added user/legal authority"})
    return built
