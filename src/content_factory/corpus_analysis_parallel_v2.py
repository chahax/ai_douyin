"""Bounded, checkpointed corpus analysis with one independently reviewed merge.

The parent owns provider admission, usage accounting and the execution lock. This
module never retries an exception from ``call`` and never grants additional scope.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import json
from pathlib import Path
import threading

from jsonschema.exceptions import ValidationError

from src.platform_adapter.fanqie_book_corpus import atomic
from . import corpus_analysis_contract_v2 as contract


VERSION = "corpus_analysis_scheduler/v2.1"
ROOT = "parallel_analysis"


class AnalysisStopped(RuntimeError):
    """The persisted analysis cannot safely advance to the writer."""


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _freeze(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def _same_or_freeze(path, value):
    if path.exists():
        if contract.digest(_read(path)) != contract.digest(value):
            raise AnalysisStopped("checkpoint_binding_changed:" + path.name)
    else:
        _freeze(path, value)


def _setup(run, source, config):
    run = Path(run)
    root = run / ROOT
    if config.get("version") != contract.VERSION:
        raise ValueError("analysis_policy_version_mismatch")
    chapters = source["chapters"]
    workers = config.get("workers", 2)
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("analysis_workers_out_of_range")
    groups = config.get("groups") or contract.plan_groups(
        chapters, config.get("max_chars", 12000), config.get("context_chars", 2000))
    if len({g["id"] for g in groups}) != len(groups):
        raise ValueError("duplicate_group_id")
    # Validate before writing a checkpoint or calling a model. Core chapters must
    # be covered exactly once; neighbouring excerpts are not coverage credit.
    indices = [index for group in groups for index in group["chapter_indices"]]
    if len(indices) != len(set(indices)) or set(indices) != {c["index"] for c in chapters}:
        raise ValueError("parallel_core_coverage_invalid")
    for group in groups:
        if not group["id"].startswith("G") or not group["id"][1:].isdigit():
            raise ValueError("unsafe_group_id")
        contract.group_payload(chapters, group, "")
    binding = {"version": VERSION, "source_sha256": contract.digest(source),
               "config_sha256": contract.digest(config), "groups": groups,
               "grouping_sha256": contract.digest(groups)}
    root.mkdir(parents=True, exist_ok=True)
    _same_or_freeze(root / "BINDING.json", binding)
    return run, root, groups, workers, binding


def _group_state(root, group):
    path = root / "groups" / group["id"] / "STATE.json"
    if not path.exists():
        return {"group_id": group["id"], "attempt": 1, "status": "pending"}
    return _read(path)


def _record_group(root, group, value):
    atomic(root / "groups" / group["id"] / "STATE.json", value)


def _attempt_dir(root, group, state):
    return root / "groups" / group["id"] / f"attempt_{state['attempt']:03d}"


def _protocol_error(exc):
    # JSON schema errors can include the entire input; store the compact reason.
    return {"type": type(exc).__name__, "reason": str(exc).splitlines()[0][:500]}


def _phase(run, directory, name, role, prompt, payload, schema, validate, call,
           stop_event=None, phase_binding=None):
    """Reuse exact checkpoints; allow one repair only after a complete response."""
    directory.mkdir(parents=True, exist_ok=True)
    binding = {"name": name, "prompt_sha256": contract.digest(prompt),
               "payload_sha256": contract.digest(payload), "schema_sha256": contract.digest(schema),
               "upstream": phase_binding or {}}
    _same_or_freeze(directory / "BINDING.json", binding)
    accepted_path = directory / "ACCEPTED.json"
    if accepted_path.exists():
        accepted = _read(accepted_path)
        value = _read(directory / accepted["output_file"])
        if (accepted["binding_sha256"] != contract.digest(binding)
                or accepted["output_sha256"] != contract.digest(value)):
            raise AnalysisStopped("accepted_analysis_changed")
        validated = validate(value)
        if accepted["validated_sha256"] != contract.digest(validated):
            raise AnalysisStopped("accepted_validation_changed")
        return validated
    state_path = directory / "STATE.json"
    prior = _read(state_path) if state_path.exists() else {}
    if prior.get("status") in {"call_failed_no_retry", "protocol_failed"}:
        raise AnalysisStopped("analysis_phase_requires_explicit_disposition:" + name)
    error = None
    previous = None
    for repair in (False, True):
        suffix = "REPAIR" if repair else "INITIAL"
        raw_path = directory / (suffix + ".json")
        call_name = name + ("_REPAIR" if repair else "")
        request_payload = {**deepcopy(payload), "output_schema": deepcopy(schema)}
        if repair:
            request_payload.update(previous_analysis=previous, validation_error=error,
                                   repair_instruction="只修正格式、引用及覆盖错误，逐条核对原文；不新增剧情或补造事实。")
        if raw_path.exists():
            value = _read(raw_path)
        else:
            # A stopped sibling prevents new model dispatch, including repairs.
            if stop_event is not None and stop_event.is_set():
                atomic(state_path, {"status": "protocol_failed" if repair else "not_started",
                                    "name": call_name, "reason": "sibling_failed"})
                raise AnalysisStopped("sibling_failed_before_dispatch")
            if prior.get("status") == "in_flight" and prior.get("name") == call_name:
                # Only the parent's existing completed artifact can prove that
                # this is a local checkpoint recovery, not an unknown replay.
                if not (run / (call_name + ".json")).exists():
                    raise AnalysisStopped("unresolved_model_call:" + call_name)
            atomic(state_path, {"status": "in_flight", "name": call_name})
            try:
                value = call(call_name, role, prompt, request_payload, json_output=True)
            except Exception as exc:
                atomic(state_path, {"status": "call_failed_no_retry", "name": call_name,
                                    "error_type": type(exc).__name__})
                if stop_event is not None:
                    stop_event.set()
                raise AnalysisStopped("model_call_not_retriable:" + call_name) from exc
            _freeze(raw_path, value)
            atomic(state_path, {"status": "response_received", "name": call_name,
                                "output_sha256": contract.digest(value)})
        try:
            validated = validate(value)
        except (ValueError, ValidationError) as exc:
            error = _protocol_error(exc)
            _same_or_freeze(directory / (suffix + "_REJECTED.json"), error)
            previous = value
            if repair:
                atomic(state_path, {"status": "protocol_failed", "name": call_name,
                                    "error": error})
                if stop_event is not None:
                    stop_event.set()
                raise AnalysisStopped("analysis_protocol_failed:" + name) from exc
            continue
        _freeze(accepted_path, {"binding_sha256": contract.digest(binding),
                               "output_file": raw_path.name,
                               "output_sha256": contract.digest(value),
                               "validated_sha256": contract.digest(validated)})
        atomic(state_path, {"status": "accepted", "name": call_name})
        return validated
    raise AssertionError("unreachable")


def _one_group(run, root, source, group, call, stop_event):
    state = _group_state(root, group)
    if state["status"] in {"protocol_failed", "call_failed_no_retry"}:
        raise AnalysisStopped("group_requires_explicit_retry:" + group["id"])
    directory = _attempt_dir(root, group, state)
    name = f"PARALLEL_{group['id']}_ATTEMPT_{state['attempt']:03d}"
    payload = contract.group_model_payload(source["chapters"], group,
                                           source.get("manifest", {}).get("book_name", source.get("book_name", "")))
    state.update(status="running")
    _record_group(root, group, state)
    try:
        value = _phase(run, directory, name, "director", contract.ANALYZE_PROMPT,
                       payload, contract.group_model_schema(group, payload),
                       lambda raw: contract.bind_group_evidence(raw, source["chapters"], group),
                       call, stop_event=stop_event)
    except Exception:
        stop_event.set()
        phase_state = _read(directory / "STATE.json") if (directory / "STATE.json").exists() else {}
        # A call with no complete response is never marked as a retryable format
        # rejection. Also keep cached-data corruption outside automatic repair.
        status = phase_state.get("status", "call_failed_no_retry")
        if status not in {"protocol_failed", "not_started"}:
            status = "call_failed_no_retry"
        state.update(status=status)
        _record_group(root, group, state)
        raise
    state.update(status="accepted", accepted_sha256=contract.digest(value))
    _record_group(root, group, state)
    return value


def _validate_cached(run, root, source, groups, call):
    """Check all saved successes before any new request can be admitted."""
    values = {}
    for group in groups:
        state = _group_state(root, group)
        if state["status"] in {"protocol_failed", "call_failed_no_retry"}:
            raise AnalysisStopped("group_requires_explicit_retry:" + group["id"])
        if state["status"] == "accepted":
            directory = _attempt_dir(root, group, state)
            accepted_path = directory / "ACCEPTED.json"
            if not accepted_path.exists():
                raise AnalysisStopped("accepted_checkpoint_missing:" + group["id"])
            accepted = _read(accepted_path)
            if not (directory / accepted["output_file"]).exists():
                raise AnalysisStopped("accepted_output_missing:" + group["id"])
            value = _one_group(run, root, source, group, call, threading.Event())
            if state.get("accepted_sha256") != contract.digest(value):
                raise AnalysisStopped("accepted_group_changed:" + group["id"])
            values[group["id"]] = value
    return values


def run_analysis(run, source, config, call):
    """Return all accepted analyses and a semantically approved unified summary.

    Call under the parent's durable execution lock. The provider ``call`` must
    itself serialize budget admission and persist claims before remote dispatch.
    """
    run, root, groups, workers, binding = _setup(run, source, config)
    values = _validate_cached(run, root, source, groups, call)
    queued = iter([group for group in groups if group["id"] not in values])
    stop_event = threading.Event()
    failures = []
    atomic(root / "STATE.json", {"status": "analyzing", "accepted_groups": sorted(values),
                                "binding_sha256": contract.digest(binding)})
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="corpus-group") as pool:
        pending = {}

        def fill_slots():
            while len(pending) < workers and not stop_event.is_set():
                group = next(queued, None)
                if group is None:
                    break
                future = pool.submit(_one_group, run, root, source, group, call, stop_event)
                pending[future] = group

        fill_slots()
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                group = pending.pop(future)
                try:
                    values[group["id"]] = future.result()
                except Exception as exc:
                    stop_event.set()
                    failures.append({"group_id": group["id"], "error_type": type(exc).__name__,
                                     "reason": str(exc).splitlines()[0][:200]})
            # No unbounded executor queue: a replacement is submitted only after
            # completed results have been inspected for a failure.
            fill_slots()
    if failures:
        atomic(root / "STATE.json", {"status": "needs_attention", "accepted_groups": sorted(values),
                                    "failures": failures, "downstream_ready": False})
        raise AnalysisStopped("parallel_analysis_groups_incomplete")
    analyses = [values[group["id"]] for group in groups]
    try:
        payload = contract.merge_payload(analyses, source)
        summary = _phase(run, root / "global_merge", "PARALLEL_GLOBAL_MERGE", "director",
                         contract.MERGE_PROMPT, payload, contract.merge_schema(analyses),
                         lambda raw: contract.validate_merge(raw, analyses, source), call,
                         phase_binding={"analyses_sha256": contract.digest(analyses)})
        reviewed = _phase(run, root / "global_review", "PARALLEL_GLOBAL_REVIEW", "director",
                          contract.GLOBAL_REVIEW_PROMPT,
                          contract.global_review_payload(summary, analyses, source),
                          contract.global_review_schema(analyses),
                          lambda raw: contract.validate_global_review(raw, summary, analyses, source), call,
                          phase_binding={"summary_sha256": contract.digest(summary)})
        _same_or_freeze(root / "GLOBAL_REVIEWED.json", reviewed)
        if not reviewed.get("validation", {}).get("downstream_ready"):
            atomic(root / "STATE.json", {"status": "needs_attention", "accepted_groups": sorted(values),
                                        "reason": "global_semantic_review_or_conflict_blocked", "downstream_ready": False})
            raise AnalysisStopped("global_semantic_review_or_conflict_blocked")
    except Exception:
        if not (root / "GLOBAL_REVIEWED.json").exists():
            atomic(root / "STATE.json", {"status": "needs_attention", "accepted_groups": sorted(values),
                                        "reason": "global_analysis_failed", "downstream_ready": False})
        raise
    result = {"analyses": analyses, "global_analysis": reviewed}
    _same_or_freeze(root / "RESULT.json", result)
    atomic(root / "STATE.json", {"status": "complete", "accepted_groups": sorted(values),
                                "downstream_ready": True, "result_sha256": contract.digest(result)})
    return result


def prepare_retry(run, source, config, group_ids, reason):
    """Record a deliberate retry of *known* group protocol failures, without I/O calls.

    Use within the parent execution lock and its original remaining budget. Old
    attempts, response artifacts, failures and consumption remain unchanged.
    """
    run, root, groups, _, binding = _setup(run, source, config)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("analysis_retry_reason_required")
    if not isinstance(group_ids, list) or not group_ids or len(set(group_ids)) != len(group_ids):
        raise ValueError("analysis_retry_groups_required")
    lookup = {group["id"]: group for group in groups}
    if not set(group_ids) <= set(lookup):
        raise ValueError("unknown_retry_group")
    prior = {identifier: _group_state(root, lookup[identifier]) for identifier in group_ids}
    for identifier, state in prior.items():
        phase_path = _attempt_dir(root, lookup[identifier], state) / "STATE.json"
        phase = _read(phase_path) if phase_path.exists() else {}
        if state["status"] != "protocol_failed" or phase.get("status") != "protocol_failed":
            raise AnalysisStopped("only_known_protocol_failure_can_retry:" + identifier)
    for group in groups:
        if _group_state(root, group)["status"] in {"running", "call_failed_no_retry"}:
            raise AnalysisStopped("unresolved_group_prevents_retry:" + group["id"])
    if (root / "global_merge" / "BINDING.json").exists():
        raise AnalysisStopped("global_analysis_already_frozen")
    records = []
    for identifier, state in prior.items():
        next_attempt = state["attempt"] + 1
        record = {"group_id": identifier, "before_state": state, "attempt": next_attempt,
                  "reason": reason.strip(), "binding_sha256": contract.digest(binding),
                  "additional_budget": 0}
        _freeze(root / "groups" / identifier / f"RETRY_{next_attempt:03d}.json", record)
        _record_group(root, lookup[identifier], {"group_id": identifier, "attempt": next_attempt,
                                               "status": "pending"})
        records.append(record)
    return records


def retry_failed_analysis(run, source, config, call, *, group_ids, reason):
    prepare_retry(run, source, config, group_ids, reason)
    return run_analysis(run, source, config, call)
