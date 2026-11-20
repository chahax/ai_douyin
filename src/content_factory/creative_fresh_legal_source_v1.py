"""Read-only preparation of one genuinely new legal metadata batch.

No client, repository constructor, collection, model, media or approval operation
is available here. The caller must supply a completed, source-bound collection.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from scripts.prepare_trend_creative_workflow import export_source
from src.content_factory import creative_legal_tag_graph_bridge_v1 as bridge
from src.content_factory.creative_story_emotion import digest
from src.trend_intelligence.legal_tag_graph_v1 import build_graph, FAMILY_LABELS

VERSION = "creative_fresh_legal_source/v1"
_BINDING = ("account_uuid", "profile_version", "domain_strategy_id", "strategy_version")


class FreshSourceError(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _fail(code, detail):
    raise FreshSourceError(code, detail)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("INPUT_JSON_INVALID", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse(raw):
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs,
                          parse_constant=lambda x: _fail("INPUT_JSON_INVALID", "nonfinite JSON"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("INPUT_JSON_INVALID", str(exc))


def _load(value, label):
    if isinstance(value, dict):
        raw = _json_bytes(value)
        return deepcopy(value), raw, {"kind": "provided_object", "sha256": _sha(raw)}
    path = Path(value).resolve()
    raw = path.read_bytes()
    parsed = _parse(raw)
    if not isinstance(parsed, dict):
        _fail("INPUT_JSON_INVALID", f"{label} must be an object")
    return parsed, raw, {"kind": "file", "path": str(path), "sha256": _sha(raw)}


def _time(value, label):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone missing")
        return result.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        _fail("INPUT_TIME_INVALID", label)


def _db_hashes(paths):
    result = {}
    for path in paths:
        path = Path(path).resolve()
        if not path.is_file():
            _fail("INPUT_DATABASE_MISSING", str(path))
        result[str(path)] = _sha(path.read_bytes())
        wal = Path(str(path) + "-wal")
        if wal.is_file():
            result[str(wal)] = _sha(wal.read_bytes())
    return result


def _ro(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _current_account(profile_db, expected_account_key, expected_account_uuid):
    with _ro(profile_db) as conn:
        rows = conn.execute(
            "SELECT a.account_uuid,a.account_key,a.status AS account_status,"
            "v.profile_version,v.domain_strategy_id,v.strategy_version,v.profile_json "
            "FROM douyin_accounts a JOIN account_strategy_versions v ON v.account_uuid=a.account_uuid "
            "WHERE a.account_key=? AND v.is_active=1", (expected_account_key,)).fetchall()
        if len(rows) != 1:
            _fail("ACCOUNT_BINDING_INVALID", "one current active profile required")
        row = dict(rows[0])
        bindings = conn.execute(
            "SELECT account_uuid,account_key,platform,public_uid,status FROM account_runtime_bindings "
            "WHERE account_uuid=?", (row["account_uuid"],)).fetchall()
    if len(bindings) != 1:
        _fail("ACCOUNT_BINDING_INVALID", "one current runtime binding required")
    binding = dict(bindings[0])
    profile = _parse(row["profile_json"].encode("utf-8"))
    if (expected_account_uuid is not None and row["account_uuid"] != expected_account_uuid
            or row["account_status"] != "active" or binding["status"] != "active"
            or binding["account_key"] != expected_account_key or binding["platform"] != "douyin"
            or profile.get("account_key") != expected_account_key or profile.get("status") != "active"
            or any(profile.get(k) != row[k] for k in _BINDING)):
        _fail("ACCOUNT_BINDING_INVALID", "current profile/account/runtime identity mismatch")
    if (profile.get("domain_strategy_id") != "legal_services"
            or "案例拆解" not in profile.get("allowed_formats", [])
            or "案例拆解" in profile.get("forbidden_formats", [])):
        _fail("ACCOUNT_FORMAT_BLOCKED", "current legal account must allow case analysis")
    return profile, binding


def _identity(check, profile, binding, floor, current):
    checked = _time(check.get("at_utc"), "identity check time")
    uid = binding.get("public_uid")
    if (check.get("healthy") is not True or not uid
            or check.get("expected_public_id") != uid or check.get("actual_public_id") != uid
            or check.get("account_key") != profile["account_key"]
            or type(check.get("profile_version")) is not int
            or check.get("profile_version") != profile["profile_version"]
            or not floor <= checked <= current):
        _fail("LIVE_IDENTITY_INVALID", "fresh exact current-account identity check required")
    return checked


def _collect(wrapper, profile):
    result = wrapper.get("result")
    if not isinstance(result, dict):
        _fail("COLLECTION_INCOMPLETE", "known CLI wrapper/result required")
    status, exit_code = wrapper.get("status"), wrapper.get("exit_code")
    # A metadata-complete research run may wait for original-video analysis.
    known = ((status == "completed" and type(exit_code) is int and exit_code == 0)
             or (status == "awaiting_media_analysis" and type(exit_code) is int and exit_code == 1))
    if not known or result.get("status") != status:
        _fail("COLLECTION_INCOMPLETE", "only explicit complete metadata branches accepted")
    if not result.get("collection_run_id") or not isinstance(result["collection_run_id"], str):
        _fail("COLLECTION_INCOMPLETE", "exact collection run ID required")
    if (result.get("sample_gate", {}).get("passed") is not True
            or type(result.get("profile_version")) is not int
            or any(result.get(k) != profile[k] for k in ("account_uuid", "account_key", "profile_version"))):
        _fail("COLLECTION_BINDING_INVALID", "collection sample gate/current account mismatch")
    return result


def _candidate_metadata(row, op, profile, run, rows, floor, current):
    if any(row[k] != op.get(k) or row[k] != profile[k] for k in _BINDING):
        raise ValueError("SQL/payload/current strategy mismatch")
    if (row["opportunity_id"] != op.get("opportunity_id") or row["status"] != "candidate"
            or op.get("status") != "candidate" or op.get("account_key") != profile["account_key"]):
        raise ValueError("candidate identity/status mismatch")
    score = row["score"]
    if (type(score) not in (int, float) or not math.isfinite(score)
            or type(op.get("opportunity_score")) not in (int, float)
            or not math.isfinite(op["opportunity_score"]) or op["opportunity_score"] != score):
        raise ValueError("candidate score mismatch")
    created = _time(row["created_at"], "SQL opportunity creation")
    if (created != _time(op.get("created_at"), "payload opportunity creation")
            or not _time(run["started_at"], "run start") <= created <= current
            or created < floor or row["valid_until"] != op.get("valid_until")
            or not _time(op.get("valid_from"), "candidate validity start") <= current
            or not current < _time(op.get("valid_until"), "candidate validity end")):
        raise ValueError("candidate old, future or outside validity")
    selected = op.get("selected_item_ids")
    items = {r["item_id"] for r in rows}
    if (not isinstance(selected, list) or not selected or any(not isinstance(i, str) for i in selected)
            or len(set(selected)) != len(selected) or not set(selected) <= items):
        raise ValueError("candidate selected items do not belong uniquely to this run")


def prepare_source_bundle(*, collect_result, trend_db, profile_db, reference_fulltext_path,
                          standards_path, verified_legal_context_path, now, requested_after,
                          identity_check, expected_account_key="account01", expected_account_uuid=None,
                          legal_context_family_ids=("family:labor",), max_sample_age_hours=72):
    """Return frozen file bytes and proven metadata; nothing is submitted or adopted."""
    current, floor = _time(now, "now"), _time(requested_after, "requested_after")
    if floor > current:
        _fail("INPUT_FROM_FUTURE", "requested_after exceeds now")
    if type(max_sample_age_hours) is not int or max_sample_age_hours <= 0:
        _fail("FRESHNESS_POLICY_INVALID", "positive integer hours required")
    families = tuple(legal_context_family_ids)
    if (not families or len(set(families)) != len(families)
            or any(f not in FAMILY_LABELS for f in families)):
        _fail("LEGAL_CONTEXT_COVERAGE_INVALID", "explicit supported legal families required")
    families = tuple(sorted(families, key=lambda f: (f != "family:labor", f)))
    wrapper, wrapper_raw, wrapper_meta = _load(collect_result, "collection result")
    check, check_raw, check_meta = _load(identity_check, "identity check")
    standards, standards_raw, standards_meta = _load(standards_path, "standards")
    facts, facts_raw, facts_meta = _load(verified_legal_context_path, "legal context")
    ref_path = Path(reference_fulltext_path).resolve()
    ref_raw = ref_path.read_bytes()
    reference = ref_raw.decode("utf-8-sig")
    if not reference.strip():
        _fail("REFERENCE_MISSING", "complete R01 reference required")
    if (facts.get("schema") != "verified_legal_story_context/v1" or not facts.get("sources")
            or not facts.get("facts") or not facts.get("creative_boundaries")):
        _fail("LEGAL_CONTEXT_INVALID", "separately verified legal context required")
    if _time(facts.get("verified_at"), "legal context verification") > current:
        _fail("INPUT_FROM_FUTURE", "legal context verification exceeds now")
    # Existing verified context is explicitly a labor-law context. Other legal
    # families require coverage declared inside the separately verified input.
    declared_coverage = facts.get("covered_family_ids", ["family:labor"])
    if not isinstance(declared_coverage, list) or not set(families) <= set(declared_coverage):
        _fail("LEGAL_CONTEXT_COVERAGE_INVALID", "requested family exceeds verified context coverage")
    databases = (Path(trend_db).resolve(), Path(profile_db).resolve())
    before = _db_hashes(databases)
    profile, binding = _current_account(profile_db, expected_account_key, expected_account_uuid)
    checked = _identity(check, profile, binding, floor, current)
    result = _collect(wrapper, profile)
    run_id = result["collection_run_id"]
    with _ro(trend_db) as conn:
        found = conn.execute("SELECT * FROM trend_collection_runs WHERE run_id=?", (run_id,)).fetchone()
        if not found:
            _fail("COLLECTION_RUN_MISSING", "exact new collection ID not stored")
        run = dict(found)
        candidates = [dict(r) for r in conn.execute(
            "SELECT opportunity_id,account_uuid,profile_version,domain_strategy_id,strategy_version,status,"
            "score,valid_until,payload_json,created_at FROM trend_content_opportunities "
            "WHERE account_uuid=? AND profile_version=? AND domain_strategy_id=? AND strategy_version=? "
            "AND status='candidate' ORDER BY score DESC,opportunity_id", tuple(profile[k] for k in _BINDING))]
    if run.get("status") != "completed" or any(run.get(k) != profile[k] for k in _BINDING):
        _fail("COLLECTION_RUN_INVALID", "SQL exact completed current-account run required")
    started, finished = _time(run.get("started_at"), "run start"), _time(run.get("finished_at"), "run finish")
    if not floor <= checked <= started <= finished <= current:
        _fail("COLLECTION_NOT_NEW", "identity/fresh collection chronology invalid")
    rejected, chosen = [], None
    # Prefer covered labor issues, then highest valid opportunity and supported core.
    for family in families:
        for row in candidates:
            try:
                source, _ = export_source(trend_db, profile_db, row["opportunity_id"], run_id,
                    tag_scope="account_positioning", max_sample_age_hours=max_sample_age_hours)
                if source["account_profile"] != profile:
                    _fail("ACCOUNT_BINDING_INVALID", "exported strategy differs from current profile")
                observations = source["observations"]
                if not observations or any(not started <= _time(r.get("collected_at"), "observation") <= finished
                                           for r in observations):
                    _fail("OBSERVATIONS_NOT_NEW", "only exact new-run collected rows accepted")
                _candidate_metadata(row, source["opportunity"], profile, run, observations, floor, current)
                graph = build_graph(source)
                options = bridge.select_candidates(graph, family_id=family)
                if not options:
                    raise ValueError("no supported issue in covered legal family")
                packet = bridge.build_packet(source, graph, reference, standards, now=now,
                    focus_label=options[0]["title"], family_id=family)
                if packet["blockers"]:
                    raise ValueError("source gates failed: " + ",".join(packet["blockers"]))
                direction_wire = bridge.build_wire(packet, facts, now=now, stage="direction")
                chosen = (source, graph, packet, options, direction_wire)
                break
            except FreshSourceError as exc:
                if exc.code not in {"INPUT_TIME_INVALID"}:
                    raise
                rejected.append({"opportunity_id": row["opportunity_id"], "family_id": family, "reason": str(exc)})
            except (ValueError, KeyError, TypeError) as exc:
                rejected.append({"opportunity_id": row["opportunity_id"], "family_id": family, "reason": str(exc)})
        if chosen:
            break
    if not chosen:
        _fail("NO_ELIGIBLE_NEW_OPPORTUNITY", json.dumps(rejected, ensure_ascii=False))
    if _db_hashes(databases) != before:
        _fail("INPUT_CHANGED", "database or WAL changed during preparation")
    input_meta = {"collection_result": wrapper_meta, "identity_check": check_meta,
                  "reference_fulltext": {"kind": "file", "path": str(ref_path), "sha256": _sha(ref_raw)},
                  "expression_standards": standards_meta, "verified_legal_context": facts_meta}
    for meta in input_meta.values():
        if meta["kind"] == "file" and _sha(Path(meta["path"]).read_bytes()) != meta["sha256"]:
            _fail("INPUT_CHANGED", "input file changed during preparation")
    source, graph, packet, options, direction_wire = chosen
    core = deepcopy(packet["candidate"])
    selection = {"schema": "fresh_legal_core_selection/v1", "selected_core": core,
        "source_opportunity_id": source["opportunity"]["opportunity_id"], "collection_run_id": run_id,
        "policy": "covered labor family first; highest valid stored opportunity score; highest supported issue score",
        "covered_legal_families": list(families), "rejected_candidates": rejected,
        "selection_authority": "delegated_automatic_metadata_selection", "human_confirmation": False}
    values = {"COLLECTION_RESULT.json": wrapper_raw, "LIVE_IDENTITY_CHECK.json": check_raw,
        "TREND_SOURCE.json": _json_bytes(source), "TAG_GRAPH.json": _json_bytes(graph),
        "SOURCE_PACKET.json": _json_bytes(packet), "CORE_CANDIDATES.json": _json_bytes(options),
        "SELECTED_CORE.json": _json_bytes(selection), "DIRECTION_WIRE_PREVIEW.json": _json_bytes(direction_wire),
        "R01_FULL.md": ref_raw, "EXPRESSION_STANDARDS.json": standards_raw,
        "VERIFIED_LEGAL_CONTEXT.json": facts_raw}
    values["SOURCE_REPORT.md"] = (f"# 新法律来源准备\n\n本轮采集：{run_id}\n\n"
        f"原研究状态：{wrapper['status']}；元数据样本门通过，原片音画未在本轮核实。\n\n"
        f"自动选择核心：{core['title']}（{core['support_video_count']}个本批视频，"
        f"{core['visible_author_count']}个可见作者）。共现与分类不构成法律结论。\n\n"
        "R01全文、六项表达标准与独立法律上下文已进入未派发请求预览。"
        "尚无模型调用、完整剧本、导演产物或创作质量通过；未伪写用户批准。\n").encode("utf-8")
    manifest = {"schema": VERSION, "prepared_at": now, "requested_after": requested_after,
        "collection_run_id": run_id, "collection_status_original": wrapper["status"],
        "original_video_av_analysis_completed": False, "evidence_scope": "fresh metadata only; original video not watched",
        "account_binding": {**{k: profile[k] for k in _BINDING}, "account_key": profile["account_key"],
                            "public_uid_sha256": _sha(binding["public_uid"].encode("utf-8"))},
        "database_sha256": before, "input_artifacts": input_meta,
        "artifact_sha256": {n: _sha(raw) for n, raw in values.items()},
        "source_sha256": digest(source), "packet_sha256": digest(packet),
        "model_calls": 0, "media_calls": 0, "collection_calls": 0, "publishing_calls": 0,
        "submitted": False, "dispatch_allowed": False, "automatic_retry": False,
        "human_confirmation": False, "creative_quality_passed": False,
        "old_records_modified": False, "old_budget_reset": False}
    manifest["fixed_input_sha256"] = _sha(_json_bytes({"inputs": input_meta, "databases": before,
        "run_id": run_id, "core": core, "requested_after": requested_after,
        "covered_legal_families": list(families), "max_sample_age_hours": max_sample_age_hours}))
    values["SOURCE_MANIFEST.json"] = _json_bytes(manifest)
    return {"content": values, "manifest": manifest, "source": source, "graph": graph,
            "packet": packet, "selected_core": core, "direction_wire": direction_wire}


def write_source_bundle(output, bundle):
    """Create new immutable files, or accept an exact-byte replay; refuse conflicts."""
    output = Path(output).resolve()
    content = bundle["content"]
    if not content or any(Path(n).name != n or not isinstance(v, bytes) for n, v in content.items()):
        _fail("BUNDLE_INVALID", "flat artifact names and byte payloads required")
    manifest = bundle.get("manifest")
    if (not isinstance(manifest, dict) or manifest.get("schema") != VERSION
            or content.get("SOURCE_MANIFEST.json") != _json_bytes(manifest)
            or manifest.get("artifact_sha256") != {n: _sha(raw) for n, raw in content.items()
                                                   if n != "SOURCE_MANIFEST.json"}):
        _fail("BUNDLE_INVALID", "prepared manifest/artifact hashes changed")
    if output.exists() and (not output.is_dir() or output.is_symlink()):
        _fail("BUNDLE_CONFLICT", "output must be an ordinary directory")
    if output.exists() and {p.name for p in output.iterdir()} - set(content):
        _fail("BUNDLE_CONFLICT", "unrelated files already exist")
    for name, raw in content.items():
        target = output / name
        if target.exists() and (not target.is_file() or target.is_symlink() or target.read_bytes() != raw):
            _fail("BUNDLE_CONFLICT", name)
    output.mkdir(parents=True, exist_ok=True)
    written, replayed = [], []
    for name, raw in content.items():
        target = output / name
        if target.exists():
            replayed.append(name)
        else:
            with target.open("xb") as stream:
                stream.write(raw)
            written.append(name)
    return {"output": str(output), "written": written, "replayed": replayed,
            "fixed_input_sha256": bundle["manifest"]["fixed_input_sha256"], "model_calls": 0}
