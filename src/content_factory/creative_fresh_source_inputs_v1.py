"""Pure new-batch input bridge; no old run, client, claim or counter access.

The supplied bundle retains complete metadata and source bytes. Model projection
uses the existing compact_context only after current-time validation of the full
packet. A manifest proves byte identity, not that metadata is a legal conclusion.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import creative_fresh_legal_source_v1 as source
from . import creative_legal_tag_graph_bridge_v1 as graph
from . import creative_compact_legal_context_v1 as compact

VERSION = "creative_fresh_source_inputs/v1"
REQUIRED_ARTIFACTS = frozenset({
    "COLLECTION_RESULT.json", "LIVE_IDENTITY_CHECK.json", "TREND_SOURCE.json",
    "TAG_GRAPH.json", "SOURCE_PACKET.json", "CORE_CANDIDATES.json", "SELECTED_CORE.json",
    "DIRECTION_WIRE_PREVIEW.json", "R01_FULL.md", "EXPRESSION_STANDARDS.json",
    "VERIFIED_LEGAL_CONTEXT.json", "SOURCE_REPORT.md",
})
BINDING_FIELDS = ("account_uuid", "profile_version", "domain_strategy_id", "strategy_version")
GOAL_FIELDS = frozenset({"contract_version", "constraints", "audience_goals", "planning_rules",
                         "division_of_work", "limitations"})
LEGACY_COLLECTION_CLI = Path(__file__).resolve().parents[2] / "scripts/run_account_video_research.py"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _ordinary(path):
    return not path.is_symlink() and not getattr(path, "is_junction", lambda: False)()


def _json(raw, *, object_required=True):
    value = source._parse(raw)
    digest(value)  # Also rejects finite-looking JSON numbers that overflow to inf.
    _require(not object_required or type(value) is dict, "JSON object required")
    return value


def _unchanged(files):
    for path, expected in files.items():
        target = Path(path)
        _require(target.is_file() and _ordinary(target) and _sha(target.read_bytes()) == expected,
                 "input bytes changed during verification: " + path)


def _wire_value(wire):
    # The source exporter saves sorted JSON files, while its original preview
    # contains a JSON-string message made before that ordering change. Compare
    # the exact nested values, retaining the preview's original byte hash above.
    result = deepcopy(wire)
    for message in result.get("messages", []):
        if message.get("role") == "user" and type(message.get("content")) is str:
            message["content"] = _json(message["content"].encode("utf-8"))
    return result


def normalize_collection_result(native_path, *, original_helper_exit_code):
    """Adapt a successful metadata helper result, never pretend the old CLI ran.

    The caller supplies its observed helper exit code and saves this derived
    wrapper separately. Its native file and exit-policy code are included in
    the next input freeze by build_inputs, rather than replacing the original.
    """
    _require(isinstance(native_path, (str, Path)) and bool(str(native_path)),
             "explicit original native collection path required")
    path = Path(native_path)
    _require(path.is_file() and _ordinary(path), "original native collection file required")
    path = path.resolve(strict=True)
    raw = path.read_bytes()
    native = _json(raw)
    status = native.get("status")
    _require(type(original_helper_exit_code) is int and original_helper_exit_code == 0,
             "known successful helper exit required; do not infer it from legacy status")
    _require(status in ("completed", "awaiting_media_analysis")
             and native.get("sample_gate", {}).get("passed") is True
             and native.get("account_key") == "account01"
             and type(native.get("profile_version")) is int and native["profile_version"] > 0
             and type(native.get("account_uuid")) is str and bool(native["account_uuid"])
             and type(native.get("collection_run_id")) is str and bool(native["collection_run_id"]),
             "only exact successful metadata native branches can be wrapped; blocked stays blocked")
    if status == "awaiting_media_analysis":
        _require(native.get("stopped_reason") == "incomplete_source_media_analysis",
                 "metadata-only completion must preserve its original pending-analysis reason")
    code = 0 if status == "completed" else 1
    return {"status": status, "exit_code": code, "result": deepcopy(native),
        "new_model_calls": 0, "new_media_calls": 0, "original_request_redispatched": False,
        "normalization": {"schema": VERSION + "/collection_wrapper", "native_path": str(path),
            "native_file_sha256": _sha(raw), "original_helper_exit_code": original_helper_exit_code,
            "legacy_cli_executed": False, "exit_code_is_observed_helper_exit": False,
            "exit_code_basis": "existing legacy CLI metadata-only status mapping, not an executed legacy CLI",
            "legacy_exit_policy_path": str(LEGACY_COLLECTION_CLI),
            "legacy_exit_policy_sha256": _sha(LEGACY_COLLECTION_CLI.read_bytes()),
            "mapping": {"completed": 0, "awaiting_media_analysis": 1},
            "native_status_modified": False, "audio_visual_analysis_verified_by_this_adapter": False,
            "original_video_av_analysis_completed": False if status == "awaiting_media_analysis" else None}}


def _verified_bundle(source_dir, now):
    root = Path(source_dir)
    _require(root.is_dir() and _ordinary(root), "ordinary source bundle directory required")
    root = root.resolve(strict=True)
    manifest_path = root / "SOURCE_MANIFEST.json"
    _require(manifest_path.is_file() and _ordinary(manifest_path), "source manifest required")
    manifest_raw = manifest_path.read_bytes()
    manifest = _json(manifest_raw)
    _require(manifest.get("schema") == source.VERSION, "exact fresh-source manifest required")
    artifacts = manifest.get("artifact_sha256")
    _require(type(artifacts) is dict and REQUIRED_ARTIFACTS <= set(artifacts),
             "complete source artifact manifest required")
    for name, expected in artifacts.items():
        _require(type(name) is str and name not in ("", ".", "..", "SOURCE_MANIFEST.json")
                 and "/" not in name and "\\" not in name and ":" not in name and _hash(expected),
                 "flat source filenames and original SHA256 required")
    _require({path.name for path in root.iterdir()} == set(artifacts) | {"SOURCE_MANIFEST.json"},
             "source directory has missing or untracked artifacts")
    files = {str(manifest_path): _sha(manifest_raw)}
    raw = {}
    for name, expected in artifacts.items():
        path = root / name
        _require(path.is_file() and _ordinary(path) and path.resolve().parent == root,
                 "source artifact must be an ordinary local file")
        raw[name] = path.read_bytes()
        _require(_sha(raw[name]) == expected, "source artifact SHA changed: " + name)
        files[str(path)] = expected
    docs = {name: _json(raw[name], object_required=name != "CORE_CANDIDATES.json")
            for name in REQUIRED_ARTIFACTS if name.endswith(".json")}
    current = source._time(now, "now")
    prepared = source._time(manifest.get("prepared_at"), "prepared_at")
    floor = source._time(manifest.get("requested_after"), "requested_after")
    _require(floor <= prepared <= current, "source preparation chronology invalid")
    for name in ("model_calls", "media_calls", "collection_calls", "publishing_calls"):
        _require(type(manifest.get(name)) is int and manifest[name] == 0,
                 "source preparation cannot authorize or claim model/media operations")
    for name in ("submitted", "dispatch_allowed", "automatic_retry", "human_confirmation",
                 "creative_quality_passed", "old_records_modified", "old_budget_reset"):
        _require(manifest.get(name) is False, "source-only preparation boundary changed")
    trend, packet = docs["TREND_SOURCE.json"], docs["SOURCE_PACKET.json"]
    profile, run = trend.get("account_profile", {}), trend.get("collection_run", {})
    binding = manifest.get("account_binding", {})
    _require(profile.get("account_key") == "account01" and profile.get("domain_strategy_id") == "legal_services"
             and profile.get("status") == "active" and profile.get("platform") == "douyin"
             and type(profile.get("account_uuid")) is str and bool(profile["account_uuid"])
             and type(profile.get("strategy_version")) is str and bool(profile["strategy_version"])
             and type(profile.get("profile_version")) is int and profile["profile_version"] > 0
             and "案例拆解" in profile.get("allowed_formats", []) and "案例拆解" not in profile.get("forbidden_formats", [])
             and all(profile.get(key) == binding.get(key) for key in BINDING_FIELDS)
             and binding.get("account_key") == "account01" and _hash(binding.get("public_uid_sha256")),
             "account01 legal profile and manifest identity must agree")
    identity = docs["LIVE_IDENTITY_CHECK.json"]
    uid = identity.get("expected_public_id")
    _require(type(uid) is str and bool(uid) and _sha(uid.encode()) == binding["public_uid_sha256"],
             "original live public identity differs from source binding")
    checked = source._identity(identity, profile, {"public_uid": uid}, floor, current)
    wrapper = docs["COLLECTION_RESULT.json"]
    normalization = wrapper.get("normalization")
    if normalization is not None:
        _require(type(normalization) is dict and normalization.get("schema") == VERSION + "/collection_wrapper",
                 "unknown collection wrapper normalization")
        rebuilt = normalize_collection_result(normalization.get("native_path", ""),
            original_helper_exit_code=normalization.get("original_helper_exit_code"))
        _require(rebuilt == wrapper, "derived collection wrapper differs from original native/helper metadata")
        files[normalization["native_path"]] = normalization["native_file_sha256"]
        files[normalization["legacy_exit_policy_path"]] = normalization["legacy_exit_policy_sha256"]
    collected = source._collect(wrapper, profile)
    run_id = collected["collection_run_id"]
    _require(run.get("run_id") == run_id == manifest.get("collection_run_id")
             and run.get("status") == "completed"
             and all(run.get(key) == profile.get(key) for key in BINDING_FIELDS)
             and manifest.get("collection_status_original") == docs["COLLECTION_RESULT.json"]["status"],
             "exact completed collection run and profile binding required")
    started, finished = source._time(run.get("started_at"), "run start"), source._time(run.get("finished_at"), "run finish")
    _require(floor <= checked <= started <= finished <= prepared <= current,
             "identity and new collection chronology invalid")
    observations = trend.get("observations")
    _require(type(observations) is list and bool(observations), "same-batch observations required")
    for row in observations:
        _require(type(row) is dict and row.get("run_id") == run_id
                 and started <= source._time(row.get("collected_at"), "observation") <= finished,
                 "observation is not from the exact completed new batch")
    opportunity = trend.get("opportunity", {})
    _require(opportunity.get("account_key") == "account01" and opportunity.get("status") == "candidate"
             and all(opportunity.get(key) == profile.get(key) for key in BINDING_FIELDS),
             "source opportunity account/profile binding changed")
    age = trend.get("selection_policy", {}).get("max_sample_age_hours")
    _require(type(age) is int and 0 < age <= 72, "source sample age policy exceeds 72 hours")
    _require(packet.get("graph_source") == trend and packet.get("graph") == docs["TAG_GRAPH.json"]
             and manifest.get("source_sha256") == digest(trend)
             and manifest.get("packet_sha256") == digest(packet), "full source/graph/packet identity mismatch")
    reference = raw["R01_FULL.md"].decode("utf-8-sig")
    standards, legal = docs["EXPRESSION_STANDARDS.json"], docs["VERIFIED_LEGAL_CONTEXT.json"]
    _require(bool(reference.strip()) and packet.get("inputs", {}).get("reference_fulltext") == reference
             and packet["inputs"].get("expression_standards") == standards,
             "complete original R01/expression standards differ from packet")
    _require(source._time(legal.get("verified_at"), "legal verification") <= prepared,
             "legal context is from the future")
    selection = docs["SELECTED_CORE.json"]
    _require(selection.get("collection_run_id") == run_id
             and selection.get("source_opportunity_id") == opportunity.get("opportunity_id")
             and selection.get("selected_core") == packet.get("candidate")
             and selection.get("human_confirmation") is False,
             "selected core must bind this actual batch and packet")
    family = packet.get("selection_policy", {}).get("family_id")
    options = graph.select_candidates(docs["TAG_GRAPH.json"], family_id=family)
    _require(docs["CORE_CANDIDATES.json"] == options and packet["candidate"] in options,
             "selected tag core lacks exact same-batch support")
    families = selection.get("covered_legal_families")
    _require(type(families) is list and bool(families) and family in families
             and set(families) <= set(legal.get("covered_family_ids", ["family:labor"])),
             "selected core exceeds independently verified legal family")
    input_map = {"collection_result": "COLLECTION_RESULT.json", "identity_check": "LIVE_IDENTITY_CHECK.json",
        "reference_fulltext": "R01_FULL.md", "expression_standards": "EXPRESSION_STANDARDS.json",
        "verified_legal_context": "VERIFIED_LEGAL_CONTEXT.json"}
    inputs_meta = manifest.get("input_artifacts", {})
    _require(set(inputs_meta) == set(input_map)
             and all(inputs_meta[key].get("sha256") == _sha(raw[name]) for key, name in input_map.items()),
             "original input artifact identities changed")
    fixed = {"inputs": inputs_meta, "databases": manifest.get("database_sha256"),
        "run_id": run_id, "core": packet["candidate"], "requested_after": manifest["requested_after"],
        "covered_legal_families": families, "max_sample_age_hours": age}
    _require(type(fixed["databases"]) is dict and len(fixed["databases"]) >= 2
             and all(_hash(value) for value in fixed["databases"].values()),
             "original database snapshot identities required")
    _require(manifest.get("fixed_input_sha256") == _sha(source._json_bytes(fixed)),
             "fixed new-source preparation identity changed")
    # Reconstruct the saved preview at its original preparation time only.
    # The independent current-time gate below remains mandatory.
    _require(_wire_value(docs["DIRECTION_WIRE_PREVIEW.json"]) == _wire_value(graph.build_wire(packet, legal,
             now=manifest["prepared_at"], stage="direction")), "saved source preview differs from original inputs")
    checked_packet = graph.validate_packet(packet, now=now)
    _require(checked_packet.get("sample_gate", {}).get("passed") is True
             and not checked_packet.get("blockers"), "complete current source gate failed")
    _unchanged(files)
    gate = {"schema": VERSION + "/source_gate", "valid": True,
        "current_source_freshness_verified": True, "verified_at": now,
        "source_dir": str(root), "source_manifest_file_sha256": _sha(manifest_raw),
        "fixed_input_sha256": manifest["fixed_input_sha256"], "source_packet_sha256": digest(packet),
        "source_sha256": digest(trend), "graph_sha256": digest(docs["TAG_GRAPH.json"]),
        "collection_run_id": run_id, "account_key": "account01", "selected_core": deepcopy(packet["candidate"]),
        "current_packet_gate": {key: deepcopy(checked_packet[key]) for key in
            ("status", "sample_gate", "blockers", "oldest_sample_age_hours", "prepared_at") if key in checked_packet},
        "source_files": sorted(files),
        "source_file_sha256": files, "source_binding_sha256": digest(files),
        "mtime_used_as_collection_time": False, "live_database_rechecked": False,
        "user_story_direction_alignment_proven": False, "metadata_is_legal_conclusion": False,
        "text_ready_for_director": False, "creative_quality_passed": False,
        "authorizes_new_dispatch": False, "model_calls": 0, "media_calls": 0}
    return gate, docs, raw


def verify_source_bundle(source_dir, *, now):
    """Verify one immutable full bundle at the supplied actual current time."""
    return _verified_bundle(source_dir, now)[0]


def build_inputs(source_dir, preferences_path, user_goals_path, *, now):
    """Build fresh inputs from explicit paths, never from old production INPUTS."""
    gate, docs, raw = _verified_bundle(source_dir, now)
    extras = {}
    for label, path in (("preferences", preferences_path), ("user_goals", user_goals_path)):
        path = Path(path)
        _require(path.is_file() and _ordinary(path), "ordinary explicit " + label + " file required")
        path = path.resolve(strict=True)
        data = path.read_bytes()
        extras[label] = (_json(data), str(path), _sha(data))
    preferences, goals = extras["preferences"][0], extras["user_goals"][0]
    _require(set(goals) <= GOAL_FIELDS and type(goals.get("contract_version")) is str
             and bool(goals["contract_version"].strip()), "functional user-goal contract required, not old run inputs")
    ids = []
    for table in ("constraints", "audience_goals"):
        rows = goals.get(table)
        _require(type(rows) is list and bool(rows), "functional user goal rows required")
        for row in rows:
            _require(type(row) is dict and type(row.get("id")) is str and bool(row["id"].strip())
                     and type(row.get("text")) is str and bool(row["text"].strip()), "nonblank functional goal IDs/text required")
            ids.append(row["id"])
    _require(len(ids) == len(set(ids)), "functional goal identities must be unique")
    reference = raw["R01_FULL.md"].decode("utf-8-sig")
    projected = compact.compact_context(docs["SOURCE_PACKET.json"], docs["VERIFIED_LEGAL_CONTEXT.json"],
        reference, docs["EXPRESSION_STANDARDS.json"], preferences, gate["source_binding_sha256"], now=now)
    inputs = {key: projected[key] for key in compact.CONTEXT_KEYS}
    inputs["user_goal_contract"] = deepcopy(goals)
    _require(inputs["reference_fulltext"] == reference
             and inputs["verified_legal_context"] == docs["VERIFIED_LEGAL_CONTEXT.json"]
             and inputs["expression_standards"] == docs["EXPRESSION_STANDARDS.json"]
             and inputs["production_preferences"] == preferences and inputs["user_goal_contract"] == goals,
             "complete current authorities cannot be rewritten by input projection")
    files = {**gate["source_file_sha256"], **{path: sha for _, path, sha in extras.values()}}
    _unchanged(files)
    evidence = {"schema": VERSION + "/inputs", "source_gate": gate,
        "input_files_sha256": files, "preferences_file_sha256": extras["preferences"][2],
        "user_goals_file_sha256": extras["user_goals"][2], "inputs_sha256": digest(inputs),
        "full_reference_sha256": digest(reference), "legal_context_sha256": digest(inputs["verified_legal_context"]),
        "expression_standards_sha256": digest(inputs["expression_standards"]),
        "user_goal_contract_sha256": digest(goals), "old_run_inputs_read": False,
        "projection_evidence": compact.projection_evidence(docs["SOURCE_PACKET.json"], projected, now=now),
        "user_story_direction_alignment_proven": False, "model_calls": 0, "media_calls": 0,
        "authorizes_new_dispatch": False, "creative_quality_passed": False}
    return {"inputs": inputs, "evidence": evidence, "source_files": sorted(files)}
