"""Local implementation pins and explicit, source-bound cloud authorization.

This module neither calls a model nor interprets conversation text as consent.
The caller must supply the user's current approval evidence explicitly. A new
run does not discard denials in its recorded previous-status ancestry.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit


VERSION = "corpus_scope/v8-temporal-subject"
PIPELINE_VERSION = "corpus_production/v8-temporal-subject"
PIN_FILES = (
    "corpus_scope_v8.py", "corpus_chapter_materials_v6.py", "corpus_production_v8.py",
    "corpus_temporal_policy_v1.py", "minimax_production_client_v1.py", "minimax_text_trial_client_v1.py",
    "creative_workflow_roles.py", "natural_director_role_clients_v10.py",
    "corpus_episode_state_v6.py", "corpus_production_contract_v6.py",
    "corpus_chapters_v4.py", "corpus_production_v3.py", "corpus_screenplay_v1.py",
    "corpus_analysis_parallel_v2.py", "corpus_parallel_calls_v2.py",
    "corpus_local_analysis_v2.py", "screenplay_role_runner_v5.py",
)


def _digest(value):
    # Match the production coordinator's frozen plan/source digest convention.
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("scope_evidence_must_be_object")
    return value


def _freeze(path, value):
    path = Path(path)
    if path.exists():
        previous = _read(path)
        if previous != value:
            raise ValueError("cloud_authorization_already_frozen")
        return previous
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    return value


def implementation_pin():
    """Read-only pin of the v8 implementation and its unchanged source/ledger helpers."""
    base = Path(__file__).resolve().parent
    return {"version": VERSION, "scope": "whole_v8_production_implementation",
            "files": {name: _file_sha(base / name) for name in PIN_FILES}}


def validate_implementation_pin(pin):
    if not isinstance(pin, dict) or pin != implementation_pin():
        raise ValueError("local_implementation_pin_changed")
    return True


def _destinations(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("cloud_destinations_missing")
    for role, destination in value.items():
        if (not isinstance(role, str) or not role or not isinstance(destination, dict)
                or set(destination) != {"provider", "model", "base_url"}
                or any(not isinstance(field, str) or not field.strip() for field in destination.values())):
            raise ValueError("cloud_destination_invalid")
        endpoint = urlsplit(destination["base_url"])
        if (endpoint.scheme not in {"http", "https"} or not endpoint.netloc
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("cloud_destination_must_exclude_credentials")
    return value


def _previous_status_path(plan, directory):
    value = plan.get("previous_status_path")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("previous_status_reference_invalid")
    path = Path(value)
    return (path if path.is_absolute() else directory / path).resolve()


def _denial_ancestry(run, plan):
    """Follow explicit provenance links, preserving every encountered denial."""
    denials, links, visited, seen_denials = [], [], set(), set()
    directory, current_plan = run, plan

    def record_denial(folder):
        path = (folder / "APPROVAL_REQUIRED.json").resolve()
        if path.exists() and str(path) not in seen_denials:
            seen_denials.add(str(path))
            denials.append({"path": str(path), "sha256": _file_sha(path)})

    for _ in range(128):
        directory = directory.resolve()
        if str(directory) in visited:
            raise ValueError("previous_status_ancestry_cycle")
        visited.add(str(directory))
        record_denial(directory)
        previous = _previous_status_path(current_plan, directory)
        if previous is None:
            return {"denial_records": denials, "previous_status_links": links}
        if not previous.is_file():
            raise ValueError("previous_status_evidence_missing")
        _read(previous)
        folder = previous.parent
        record_denial(folder)
        parent_plan_path = folder / "PLAN.json"
        if not parent_plan_path.is_file():
            links.append({"status_path": str(previous), "plan_path": None, "plan_sha256": None})
            return {"denial_records": denials, "previous_status_links": links}
        parent_plan = _read(parent_plan_path)
        # A phase STATE may point to a phase plan. Follow its verified parent
        # without treating a nested directory as a new independent lineage.
        if "parent_plan_sha256" in parent_plan:
            outer_path = folder.parent / "PLAN.json"
            if not outer_path.is_file():
                raise ValueError("previous_phase_parent_plan_missing")
            outer = _read(outer_path)
            if _digest(outer) != parent_plan["parent_plan_sha256"]:
                raise ValueError("previous_phase_parent_binding_changed")
            links.append({"status_path": str(previous), "plan_path": str(parent_plan_path.resolve()),
                          "plan_sha256": _digest(parent_plan)})
            folder, parent_plan, parent_plan_path = folder.parent, outer, outer_path
        links.append({"status_path": str(previous), "plan_path": str(parent_plan_path.resolve()),
                      "plan_sha256": _digest(parent_plan)})
        directory, current_plan = folder, parent_plan
    raise ValueError("previous_status_ancestry_too_deep")


def _context(run, supplied_plan=None):
    run = Path(run).resolve()
    plan, source = _read(run / "PLAN.json"), _read(run / "SOURCE.json")
    if supplied_plan is not None and plan != supplied_plan:
        raise ValueError("cloud_authorization_plan_changed")
    if plan.get("version") != PIPELINE_VERSION:
        raise ValueError("cloud_authorization_pipeline_version_mismatch")
    if _digest(source) != plan.get("source_sha256"):
        raise ValueError("cloud_authorization_source_changed")
    chapters = source.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("cloud_authorization_source_scope_missing")
    indices = [chapter.get("index") for chapter in chapters if isinstance(chapter, dict)]
    if (len(indices) != len(chapters) or any(type(index) is not int or index < 0 for index in indices)
            or indices != sorted(set(indices)) or indices != plan.get("source_chapters")):
        raise ValueError("cloud_authorization_chapter_scope_mismatch")
    book_id = source.get("manifest", {}).get("book_id")
    if not isinstance(book_id, (str, int)) or isinstance(book_id, bool) or not str(book_id):
        raise ValueError("cloud_authorization_book_identity_missing")
    models = _destinations(plan.get("cloud_models"))
    return {"version": VERSION, "plan_sha256": _digest(plan),
            "source_sha256": plan["source_sha256"], "source_book_id": str(book_id),
            "approved_chapter_indices": indices, "approved_destinations": models,
            "ancestry": _denial_ancestry(run, plan)}


def record_cloud_authorization(run, user_statement, *, approved_source_sha256,
                               approved_destinations, approved_chapter_indices=None):
    """Freeze explicit approval supplied by the caller; never infer it from PLAN.

    The caller decides whether the provided current conversation evidence is an
    actual human approval. This function verifies its structured scope. Existing
    APPROVAL_REQUIRED records remain intact and require separate disposition.
    """
    if not isinstance(user_statement, str) or not user_statement.strip():
        raise ValueError("current_explicit_cloud_approval_evidence_required")
    context = _context(run)
    if approved_source_sha256 != context["source_sha256"]:
        raise ValueError("approved_source_scope_mismatch")
    if _destinations(approved_destinations) != context["approved_destinations"]:
        raise ValueError("approved_destinations_mismatch")
    if approved_chapter_indices is not None and approved_chapter_indices != context["approved_chapter_indices"]:
        raise ValueError("approved_chapters_mismatch")
    record = {**context, "approval_evidence_text": user_statement,
              "approval_origin": "explicit_current_user_evidence_supplied_by_caller",
              "old_denials_preserved": True, "current_run_denial_disposition_performed": False}
    return _freeze(Path(run).resolve() / "CLOUD_AUTHORIZATION.json", record)


def require_cloud_authorization(run, plan):
    run = Path(run).resolve()
    path = run / "CLOUD_AUTHORIZATION.json"
    if not path.is_file():
        raise ValueError("explicit_cloud_authorization_required")
    authorization = _read(path)
    if (authorization.get("approval_origin") != "explicit_current_user_evidence_supplied_by_caller"
            or not isinstance(authorization.get("approval_evidence_text"), str)
            or not authorization["approval_evidence_text"].strip()
            or authorization.get("old_denials_preserved") is not True
            or authorization.get("current_run_denial_disposition_performed") is not False):
        raise ValueError("cloud_authorization_evidence_invalid")
    context = _context(run, plan)
    for key, value in context.items():
        if authorization.get(key) != value:
            raise ValueError("cloud_authorization_scope_or_ancestry_changed")
    if (run / "APPROVAL_REQUIRED.json").exists():
        raise ValueError("current_run_approval_denial_requires_separate_disposition")
    return authorization
