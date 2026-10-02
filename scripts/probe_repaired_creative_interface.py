"""Explicit real text diagnostic, sharing frozen parent budget; never resume it."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jsonschema import Draft202012Validator
from src.content_factory.creative_diagnostic_spend import shared_diagnostic_root
from src.content_factory.creative_workflow_roles import CreativeRoleClients, role_config
from src.content_factory.creative_response_contract import exception_failure, response_failure, fault, validation_failure
from src.content_factory.creative_modular_contract import (
    build_direction_schema, validate_direction, build_local_schema,
    build_local_input, _compile_prefix,
)
PROJECT = Path(__file__).resolve().parents[1]
PARENT = PROJECT / "data/production_trials/boundary_live_action_reference_v15_20261001/round_01"
ROOT = shared_diagnostic_root(PARENT)
LEDGER = ROOT / "CALL_LEDGER.json"
LIMITS = {"micro": 1024, "direction": 8000, "local": 4096}
AUTHORIZATION = "用户2026-10-03明确要求：之前的修复方案落实后生产接口测试。文本诊断占用原任务剩余最多3次调用，不新增预算、不生成媒体、不发布。"

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()

def digest(value):
    return digest_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

def write(path, value, *, immutable=False):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if immutable:
        with path.open("x", encoding="utf-8") as out:
            out.write(text)
    else:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

def snapshot(root):
    return {str(p.relative_to(root)).replace("\\", "/"): digest_bytes(p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file()}

def sources():
    paths = list((PROJECT / "src/content_factory").glob("*.py"))
    paths += [Path(__file__).resolve(), PROJECT / "src/shared/config.py"]
    return {str(p.relative_to(PROJECT)).replace("\\", "/"): digest_bytes(p.read_bytes()) for p in sorted(paths)}

@contextmanager
def locked():
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "DISPATCH.lock"
    with lock.open("x", encoding="utf-8") as out:
        out.write(json.dumps({"pid": os.getpid(), "created_at": now()}))
    try:
        yield
    finally:
        lock.unlink()

def now():
    return datetime.now(timezone.utc).isoformat()

def check_binding(ledger):
    if ledger.get("schema") != "creative_shared_text_diagnostic/v1" or Path(ledger["parent_run"]).resolve() != PARENT.resolve():
        raise RuntimeError("diagnostic parent binding mismatch")
    if snapshot(PARENT) != ledger["parent_snapshot"]:
        raise RuntimeError("frozen parent files changed; diagnostic blocked")
    if digest(read(ROOT / "CONTEXT.json")) != ledger["context_sha256"]:
        raise RuntimeError("diagnostic context binding changed")
    if sources() != ledger["source_manifest"]:
        raise RuntimeError("diagnostic source binding changed")
    expected = {c["receipt"] for c in ledger["calls"]}
    present = {p.name for p in ROOT.glob("call_[0-9][0-9][0-9]_*.json")}
    if expected != present:
        raise RuntimeError("orphan or missing request receipt; reconcile before any dispatch")

def prepare():
    with locked():
        if LEDGER.exists():
            check_binding(read(LEDGER))
            return report()
        state = read(PARENT / "state.json")
        if (state["calls_started"], state["max_calls"], state["reported_tokens"], state["max_total_tokens"]) != (21, 24, 354328, 500000):
            raise RuntimeError("parent budget differs from verified authorization")
        if list(ROOT.glob("call_[0-9][0-9][0-9]_*.json")):
            raise RuntimeError("unreconciled diagnostic requests exist")
        old = read(PARENT / "director_state_plan__00.json")
        payload = json.loads(old["request"]["messages"][1]["content"])
        context = {k: deepcopy(payload[k]) for k in (
            "script", "creative_brief", "static_visual_manifest", "material_ref",
            "reference_pack", "reference_expression_rule")}
        reference_evidence = []
        for ref in context["reference_pack"]:
            # Verify full reference text equals the original on-disk reference.
            candidates = [value for value in ref.values() if isinstance(value, str)]
            full_text = max(candidates, key=len)
            path = PROJECT / "data/reference_reviews/reusable_expression_20261001/EXPRESSION_REFERENCE.md"
            actual = path.read_text(encoding="utf-8-sig")
            if full_text != actual.strip():
                raise RuntimeError("actual reference text differs from frozen request")
            reference_evidence.append({"source": str(path), "text_sha256": digest_bytes(full_text.encode("utf-8")),
                                       "characters": len(full_text), "frozen_request_contains_full_text": True,
                                       "source_text_sha256": digest_bytes(actual.encode("utf-8")),
                                       "normalization": "project material loader strips boundary whitespace only"})
        write(ROOT / "CONTEXT.json", context, immutable=True)
        config = role_config("writer")
        ledger = {
            "schema": "creative_shared_text_diagnostic/v1", "created_at": now(),
            "authorization": AUTHORIZATION, "parent_run": str(PARENT.resolve()),
            "parent_snapshot": snapshot(PARENT), "source_manifest": sources(),
            "parent_budget": {k: state[k] for k in (
                "calls_started", "max_calls", "reported_tokens", "max_total_tokens",
                "revision_rounds", "max_revisions", "contract_repairs_used", "max_contract_repairs")},
            "old_governance_binding": state.get("governance_binding", state.get("governance_pack_id")),
            "diagnostic_contract": "explicit_minimax_repaired_interface_probe/v1",
            "production_governance_migration": False, "automatic_retry": False,
            "sdk_max_retries": 0, "media_calls": 0, "calls": [],
            "context_sha256": digest(context), "reference_evidence": reference_evidence,
            "model": {"provider": config.provider, "model": config.model,
                      "endpoint_host": urlsplit(config.base_url).hostname,
                      "thinking": "disabled", "temperature": 0.4},
            "limitations": ["only interface and partial modular contract verification",
                           "no actual selected images exist in this parent input",
                           "no five-beat complete compilation or DeepSeek full-text review",
                           "no server internal telemetry; thinking execution cannot be proven from request intent"]
        }
        write(LEDGER, ledger, immutable=True)
    return report()

def usage_totals(ledger):
    known, reserved, ids = 0, 0, set()
    for call in ledger["calls"]:
        record = read(ROOT / call["receipt"])
        metadata = record.get("response_metadata", {})
        amount = metadata.get("total_tokens")
        if type(amount) is int and amount >= 0:
            identity = metadata.get("response_id") or ("call", call["ordinal"])
            if identity not in ids:
                known += amount
                ids.add(identity)
        else:
            reserved += call["token_reservation"]
    return known, reserved

def request_for(label):
    context = read(ROOT / "CONTEXT.json")
    if label == "micro":
        schema = {"type": "object", "additionalProperties": False, "required": ["probe", "accepted"],
                  "properties": {"probe": {"const": "repaired_interface_20261003"},
                                 "accepted": {"type": "boolean", "const": True}}}
        data = {"task": "调用submit_creative_json，提交probe=repaired_interface_20261003及accepted=true。"}
        instruction = "这是文本接口验收请求。用指定工具提交结果。"
    elif label == "direction":
        schema = build_direction_schema(context)
        data = {"context": context}
        instruction = ("为完整剧本生成整片规划。你负责全片情绪、因果、逐拍新增信息、观察对象、刺激、切镜理由和表演窗口要求，"
                       "以及合法初态和空间契约；局部动作和排时由后续模块安排。使用参考的表达机制，不照搬剧情。"
                       "对白和事件仍以原剧本为准。用指定工具提交完整本阶段合同。")
    else:
        direction = read(ROOT / "direction.parsed.json")
        ledger = read(LEDGER)
        source_call = next(c for c in ledger["calls"] if c["label"] == "direction")
        original = json.loads(read(ROOT / source_call["receipt"])["response_text"])
        if direction != original:
            raise RuntimeError("parsed direction differs from original model submission")
        data = build_local_input(context, direction, [])
        schema = build_local_schema(context, direction, data["beat_id"])
        instruction = ("为beat_id对应的一拍生成局部表演合同。完整剧本和整片规划用于理解前后因果，"
                       "只安排本拍动作组、对白表演与刺激反应窗口；不得重写全片规划、对白或实体状态。"
                       "input_sha256绑定完整输入，状态由编译器推导。用指定工具提交完整本阶段合同。")
        data["input_sha256"] = digest(data)
    messages = [{"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)}]
    return messages, schema

def prior_valid(ledger, label):
    predecessors = {"micro": [], "direction": ["micro"], "local": ["micro", "direction"]}[label]
    for name in predecessors:
        previous = next((c for c in ledger["calls"] if c["label"] == name), None)
        if previous is None or read(ROOT / previous["receipt"]).get("status") != "contract_validated":
            raise RuntimeError("prior diagnostic contract was not validated; no dependent dispatch")
    for call in ledger["calls"]:
        record = read(ROOT / call["receipt"])
        if record.get("status") in ("pending_response", "outcome_unknown") or type(record.get("response_metadata", {}).get("total_tokens")) is not int:
            raise RuntimeError("unknown outcome or usage; reconcile original request before any new dispatch")

def execute(label):
    with locked():
        ledger = read(LEDGER)
        check_binding(ledger)
        old_call = next((c for c in ledger["calls"] if c["label"] == label), None)
        if old_call:
            return {"status": "existing_receipt_no_dispatch", "receipt": old_call["receipt"],
                    "record_status": read(ROOT / old_call["receipt"])["status"]}
        prior_valid(ledger, label)
        base = ledger["parent_budget"]
        if base["calls_started"] + len(ledger["calls"]) >= base["max_calls"]:
            raise RuntimeError("shared parent call budget exhausted")
        messages, schema = request_for(label)
        max_tokens = LIMITS[label]
        # Same conservative Unicode-character planning basis as project workflow.
        reservation = len(json.dumps({"messages": messages, "tools": schema}, ensure_ascii=False)) + max_tokens
        known, reserved = usage_totals(ledger)
        if base["reported_tokens"] + known + reserved + reservation > base["max_total_tokens"]:
            raise RuntimeError("shared parent token budget insufficient for conservative reservation")
        ordinal = base["calls_started"] + len(ledger["calls"]) + 1
        receipt = f"call_{ordinal:03}_{label}.json"
        record = {"schema": "creative_production_interface_diagnostic_call/v1", "label": label,
                  "ordinal": ordinal, "status": "pending_response", "started_at": now(),
                  "request": {"messages": messages, "structured_schema": schema,
                              "parameters": {"max_completion_tokens": max_tokens, "temperature": 0.4,
                                             "thinking": "disabled", "model": ledger["model"]["model"],
                                             "tool_choice": {"type": "function", "function": {"name": "submit_creative_json"}}}},
                  "request_sha256": digest({"messages": messages, "schema": schema, "max_tokens": max_tokens}),
                  "token_reservation": reservation, "automatic_retry": False}
        write(ROOT / receipt, record, immutable=True)
        call = {"ordinal": ordinal, "label": label, "receipt": receipt,
                "status": "pending_response", "token_reservation": reservation, "response_metadata": {}}
        ledger["calls"].append(call)
        write(LEDGER, ledger)  # Persist uncertain outcome and charge ordinal BEFORE network.
        print(json.dumps({"status": "dispatching", "label": label, "ordinal": ordinal,
                          "max_completion_tokens": max_tokens}, ensure_ascii=False), flush=True)
        try:
            result = CreativeRoleClients().call("writer", messages, max_tokens=max_tokens,
                                                temperature=0.4, thinking="disabled", structured_schema=schema)
        except Exception as exc:
            failure = exception_failure(exc)
            record.update(status="interface_rejected" if failure["response_received"] else "outcome_unknown",
                          failure=failure, error=str(exc), completed_at=now())
            metadata = getattr(exc, "response_metadata", None)
            if metadata is not None:
                record["response_metadata"] = metadata
                record["response_text"] = getattr(exc, "response_text", None)
                record["response_payload"] = getattr(exc, "response_payload", None)
        else:
            record.update(status="response_received", response_metadata=result.metadata,
                          response_text=result.text, completed_at=now())
            write(ROOT / receipt, record)  # Save service result before parsing/compiling.
            failure = response_failure(result.metadata, result.text, require_tool=True)
            try:
                if failure:
                    raise RuntimeError(failure["code"])
                output = json.loads(result.text)
                Draft202012Validator(schema).validate(output)
                if label == "direction":
                    validate_direction(output, read(ROOT / "CONTEXT.json"))
                elif label == "local":
                    context = read(ROOT / "CONTEXT.json")
                    direction = read(ROOT / "direction.parsed.json")
                    compiled = _compile_prefix(context, direction, [output])
                    write(ROOT / "first_beat_compilation.json", compiled, immutable=True)
                    write(ROOT / "next_local_input.json", build_local_input(context, direction, [output]), immutable=True)
                write(ROOT / f"{label}.parsed.json", output, immutable=True)
                record["status"] = "contract_validated"
                record["semantic_approval"] = False
            except Exception as exc:
                if failure is None:
                    if isinstance(exc, (json.JSONDecodeError,)):
                        failure = fault("RESULT_JSON_INVALID", "state_contract", "complete_new_draft_then_full_review", received=True)
                    elif hasattr(exc, "validator"):
                        failure = fault("MODULE_SCHEMA_INVALID", "state_contract", "complete_new_draft_then_full_review", received=True)
                    else:
                        failure = validation_failure(exc)
                record.update(status="validation_rejected", failure=failure,
                              validation_error={"type": type(exc).__name__, "message": str(exc),
                                                "detail": getattr(exc, "detail", None)})
        write(ROOT / receipt, record)
        call.update(status=record["status"], response_metadata=record.get("response_metadata", {}),
                    failure=record.get("failure"))
        write(LEDGER, ledger)
        check_binding(ledger)
        return {"status": record["status"], "ordinal": ordinal, "label": label,
                "response_metadata": record.get("response_metadata", {}), "failure": record.get("failure"),
                "validation_error": record.get("validation_error"), "receipt": str(ROOT / receipt)}

def report():
    ledger = read(LEDGER)
    check_binding(ledger)
    known, reserved = usage_totals(ledger)
    base = ledger["parent_budget"]
    result = {"schema": "creative_production_interface_diagnostic_result/v1",
              "diagnostic_root": str(ROOT), "frozen_parent_unchanged": True,
              "source_binding_unchanged": True, "paid_text_calls": len(ledger["calls"]),
              "frozen_parent_calls": base["calls_started"],
              "effective_calls_started": base["calls_started"] + len(ledger["calls"]),
              "max_calls": base["max_calls"], "parent_reported_tokens": base["reported_tokens"],
              "diagnostic_reported_tokens": known, "unknown_token_reservations": reserved,
              "effective_reported_tokens": base["reported_tokens"] + known,
              "max_total_tokens": base["max_total_tokens"],
              "remaining_calls": base["max_calls"] - base["calls_started"] - len(ledger["calls"]),
              "remaining_token_budget_after_reservations": base["max_total_tokens"] - base["reported_tokens"] - known - reserved,
              "calls": [{"ordinal": c["ordinal"], "label": c["label"],
                         "status": read(ROOT / c["receipt"])["status"],
                         "response_metadata": read(ROOT / c["receipt"]).get("response_metadata", {}),
                         "failure": read(ROOT / c["receipt"]).get("failure"),
                         "validation_error": read(ROOT / c["receipt"]).get("validation_error")} for c in ledger["calls"]],
              "reference_evidence": ledger["reference_evidence"],
              "limitations": ledger["limitations"], "semantic_approval": False, "media_calls": 0,
              "production_governance_migration": False}
    write(ROOT / "RESULT.json", result)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "micro", "direction", "local", "report"])
    command = parser.parse_args().command
    result = prepare() if command == "prepare" else report() if command == "report" else execute(command)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
