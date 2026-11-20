"""Independent, fail-closed novel adaptation text route.

The native structured draft is authoritative. Reading copies are deterministic
projections; media, account operations and human approval are outside this route.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from . import novel_adaptation_contracts_v1 as contracts
from .creative_workflow_roles import CreativeRoleClients, _response_model_matches
from src.shared.config import settings

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_REGISTRY = ROOT / "data/novel_adaptation_registry_v1"
VERSION = "novel_adaptation_pipeline/v1"
MAX_REQUEST_BYTES = 350000
MIN_LEGACY_MATCH_CHARACTERS = 32
TERMINAL = {"text_ready_for_director", "needs_attention", "content_revision_exhausted", "legacy_dispatch_blocked"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=_invalid_constant)


def _invalid_constant(value):
    raise ValueError("非法JSON数值：" + value)


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)


def _ensure(path, value):
    """Resume publication of existing accepted outputs without overwriting."""
    if Path(path).exists():
        if _read(path) != value:
            raise ValueError("既有交付文件与已接受原稿不符：" + str(path))
    else:
        _write(path, value)


def _binding(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": _sha(data), "bytes": len(data)}


def _verify_file(row):
    if _binding(row["path"]) != row:
        raise ValueError("冻结文件变化：" + row["path"])


def _protocol():
    result = {"writer": {"provider": settings.WRITER_AGENT_PROVIDER,
                       "model": settings.WRITER_AGENT_MODEL, "base_url": settings.WRITER_AGENT_BASE_URL},
            "director": {"provider": settings.DIRECTOR_AGENT_PROVIDER,
                         "model": settings.DIRECTOR_AGENT_MODEL, "base_url": settings.DIRECTOR_AGENT_BASE_URL},
            "sdk_automatic_retries": 0, "writer_max_completion_tokens": 20000, "review_max_tokens": 12000,
            "timeout_seconds": settings.SCRIPT_LLM_TIMEOUT_SECONDS, "api": "openai_chat_completions"}
    for role, provider in (("writer", "minimax"), ("director", "deepseek")):
        endpoint = urlsplit(result[role]["base_url"])
        if (result[role]["provider"] != provider or endpoint.scheme != "https" or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("角色供应商/端点不合已确认协议；不保存可能含凭据的URL")
    timeout = result["timeout_seconds"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("文本接口timeout必须为有限正数")
    return result


def _code_bindings():
    # Bind direct implementations plus the local imports they depend upon. This
    # avoids a changed provider/config/parser silently becoming a frozen run.
    import ast
    seen, queue = set(), [Path(__file__).resolve(), Path(contracts.__file__).resolve(),
                         ROOT / "src/content_factory/creative_workflow_roles.py", ROOT / "src/shared/config.py"]
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.level:
                parent = path.parent
                for _ in range(node.level - 1):
                    parent = parent.parent
                candidate = parent.joinpath(*node.module.split(".")).with_suffix(".py")
            elif node.module.startswith("src."):
                candidate = ROOT.joinpath(*node.module.split(".")).with_suffix(".py")
            else:
                continue
            if candidate.is_file():
                queue.append(candidate.resolve())
    return [_binding(path) for path in sorted(seen)]


def _receipt_file(value, receipt_path):
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    if path.parts and path.parts[0].lower() == "data":
        resolved = (ROOT / path).resolve()
        if not resolved.is_relative_to((ROOT / "data").resolve()):
            raise ValueError("采集回执data路径越出项目data目录")
        return resolved
    return (receipt_path.parent / path).resolve()


def _source(source_path, acquisition_receipt, title, book_id, scope):
    if bool(source_path) == bool(acquisition_receipt):
        raise ValueError("必须且只能选择正文文件或成功采集回执")
    evidence, paths, texts = [], [], []
    selection_scope = scope
    if acquisition_receipt:
        receipt_path = Path(acquisition_receipt).resolve()
        receipt_raw = receipt_path.read_bytes()
        receipt = json.loads(receipt_raw.decode("utf-8-sig"), parse_constant=_invalid_constant)
        if receipt.get("status") != "source_saved":
            raise ValueError("采集尚未成功保存正文")
        evidence.append({"path": str(receipt_path), "sha256": _sha(receipt_raw), "bytes": len(receipt_raw)})
        info = receipt.get("source", {})
        if book_id and info.get("book_id") and str(book_id) != str(info["book_id"]):
            raise ValueError("显式book_id与采集回执身份不符")
        title = title or info.get("book_name") or info.get("title")
        book_id = book_id or info.get("book_id")
        rows = info.get("chapters") or []
        if not rows:
            raise ValueError("采集回执没有显式章节正文清单，简介/material不能替代正文")
        for row in rows:
            chapter = row.get("path") or row.get("file")
            if not chapter:
                raise ValueError("章节缺正文文件")
            path = _receipt_file(chapter, receipt_path)
            raw = path.read_bytes()
            binding = {"path": str(path.resolve()), "sha256": _sha(raw), "bytes": len(raw)}
            if row.get("sha256") and row["sha256"] != binding["sha256"]:
                raise ValueError("采集章节SHA不符")
            paths.append(path.resolve())
            evidence.append(binding)
            texts.append(raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n"))
        if info.get("metadata_path"):
            metadata_path = _receipt_file(info["metadata_path"], receipt_path)
            metadata = _binding(metadata_path)
            if info.get("metadata_sha256") and info["metadata_sha256"] != metadata["sha256"]:
                raise ValueError("采集metadata SHA不符")
            evidence.append(metadata)
        # Acquired coverage is a program fact. A user's adaptation range/note
        # cannot replace real chapter counts with a claim to have read a book.
        scope = {"acquired_chapters": len(rows), "chapter_titles": [row.get("title", "") for row in rows],
                 "scope_note": "仅已获取章节，非整本小说"}
        if selection_scope is not None:
            scope["adaptation_scope"] = selection_scope
    else:
        paths = [Path(source_path).resolve()]
        raw = paths[0].read_bytes()
        evidence.append({"path": str(paths[0]), "sha256": _sha(raw), "bytes": len(raw)})
        texts.append(raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n"))
        title = title or paths[0].stem
        scope = scope or {"scope_note": "仅此正文文件；不推定已取得全书"}
    if len(paths) != len(set(paths)):
        raise ValueError("章节文件重复")
    for row in evidence:
        _verify_file(row)
    text = "\n\n".join(texts)
    if not text.strip():
        raise ValueError("正文为空")
    if "小说名称：" in text[:300] and "作品简介：" in text[:1000]:
        raise ValueError("文件包含作品简介封装，请选择实际章节正文")
    start, end = 0, len(text)
    if isinstance(selection_scope, dict):
        start = selection_scope.get("start_character", 0)
        end = selection_scope.get("end_character", len(text))
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError("正文选段边界非法")
    full_sha = _sha(text.encode("utf-8"))
    excerpt = text[start:end]
    source = {"title": str(title), "book_id": str(book_id or ""), "scope": scope,
              "full_source_sha256": full_sha, "excerpt_sha256": _sha(excerpt.encode("utf-8")),
              "start_character": start, "end_character": end, "text": excerpt}
    source["binding_id"] = _digest(source)
    return source, evidence, paths


def _legacy_blocks(source, paths, legacy_parent=None):
    candidates = set((ROOT / "data/novel_platform_trials").glob("*/FINAL_TRIAL_CHECKPOINT.json"))
    if legacy_parent:
        parent = Path(legacy_parent).resolve()
        candidates.add(parent if parent.is_file() else parent / "FINAL_TRIAL_CHECKPOINT.json")
    blocks = []
    for path in sorted(candidates):
        if not path.is_file():
            if legacy_parent:
                raise ValueError("显式历史任务缺终止检查点")
            continue
        old = _read(path)
        same_book = bool(source["book_id"] and str(old.get("book_id")) == source["book_id"])
        old_root = path.parent.resolve()
        same_path = any(candidate.is_relative_to(old_root) for candidate in paths)
        same_title = bool(source["title"] and old.get("book_name") == source["title"])
        same_body = source["full_source_sha256"] in {
            old.get("full_source_sha256"), old.get("body_sha256"), old.get("source_sha256")}
        if not (same_book or same_path or same_title or same_body or legacy_parent):
            # Detect copied source files without relying on a caller-provided ID.
            old_source = old_root / "ACQUISITION_RESULT_v4.json"
            if old_source.is_file():
                prior = _read(old_source)
                sha = prior.get("source_integrity", {}).get("body_sha256")
                same_body = sha in {source["full_source_sha256"], _sha(source["text"].strip().encode("utf-8"))} or any(_binding(p)["sha256"] == sha for p in paths)
                for row in prior.get("source", {}).get("chapters", []):
                    original = _receipt_file(row.get("file") or row.get("path") or "", old_source)
                    if original.is_file():
                        old_text = original.read_text(encoding="utf-8-sig").strip()
                        new_text = source["text"].strip()
                        body_only = re.sub(r"^第[^\n]{0,80}章[^\n]*\n", "", new_text).strip()
                        if old_text and (old_text in new_text or (len(body_only) >= MIN_LEGACY_MATCH_CHARACTERS and body_only in old_text)):
                            same_body = True
            selections = [old_root / "text_run/creative/SELECTED_SOURCE.json", old_root / "SELECTED_SOURCE.json",
                          *old_root.glob("*/SELECTED_SOURCE.json"), *old_root.glob("*/creative/SELECTED_SOURCE.json")]
            for selected_path in selections:
                if not selected_path.is_file():
                    continue
                prior_text = _read(selected_path).get("text")
                new_text = source["text"].strip()
                if isinstance(prior_text, str) and prior_text.strip() and (
                        new_text == prior_text.strip()
                        or (len(new_text) >= MIN_LEGACY_MATCH_CHARACTERS and (new_text in prior_text or prior_text.strip() in new_text))):
                    same_body = True
        if same_book or same_path or same_title or same_body or legacy_parent:
            if old.get("new_writer_requests_allowed_without_new_scope") is not True:
                blocks.append({"reason": "历史小说任务截断/候选耗尽；新入口仅可预览，不得重领派发",
                               "checkpoint": _binding(path), "calls_started": old.get("calls_started"),
                               "reported_tokens": old.get("known_reported_tokens"), "status": old.get("status")})
    return blocks


def _save_state(run, state):
    snapshots = sorted(run.glob("STATE_*.json"))
    number = len(snapshots) + 1
    snapshot = run / f"STATE_{number:05}.json"
    _write(snapshot, state)
    temp = run / (".state-" + uuid.uuid4().hex)
    temp.write_bytes(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
    temp.replace(run / "state.json")


def prepare(run_dir, *, source_path=None, acquisition_receipt=None, title=None, book_id=None, scope=None,
            registry_dir=None, max_calls=20, max_total_tokens=500000, max_revisions=2, legacy_parent=None):
    """Freeze source and contracts; never contacts a model or a browser."""
    run = Path(run_dir).resolve()
    protocol = _protocol()
    if protocol["writer"]["model"] != "MiniMax-M3" or protocol["director"]["model"] != "deepseek-flash":
        raise ValueError("当前路线只接已确认MiniMax/DeepSeek协议")
    source, evidence, paths = _source(source_path, acquisition_receipt, title, book_id, scope)
    if (run / "BINDING.json").exists():
        bound, _ = _verify(run)
        if bound["source"] != source or bound["budget"] != {
                "max_calls": max_calls, "max_total_tokens": max_total_tokens, "max_revisions": max_revisions}:
            raise ValueError("恢复不能更换来源或预算")
        return inspect(run)
    if any(type(value) is not int or value < 1 for value in (max_calls, max_total_tokens)):
        raise ValueError("调用和token预算必须为正整数")
    if type(max_revisions) is not int or not 0 <= max_revisions <= 2:
        raise ValueError("完整内容返修上限为全运行0至2轮")
    if run.exists() and any(run.iterdir()):
        raise ValueError("新运行目录必须为空，不能覆盖旧证据")
    blockers = _legacy_blocks(source, paths, legacy_parent)
    canonical = CANONICAL_REGISTRY.resolve()
    canonical.mkdir(parents=True, exist_ok=True)
    aliases = ["source_" + source["full_source_sha256"]]
    if source["book_id"]:
        aliases.append("book_" + _digest(source["book_id"]))
    # Title is a conservative additional guard if no stable platform ID exists.
    if source["title"]:
        aliases.append("title_" + _digest(source["title"].strip()))
    registry_paths = [canonical / (alias + ".json") for alias in aliases]
    registry_lock = canonical / ".registration.lock"
    with _lock(registry_lock):
        claim = {"schema": VERSION, "run_dir": str(run), "source_binding_id": source["binding_id"],
                 "story_id": aliases[0]}
        for path in registry_paths:
            if path.exists() and _read(path) != claim:
                raise RuntimeError("同故事已有运行；须恢复原目录，不能改目录或registry重领额度：" + _read(path)["run_dir"])
        for path in registry_paths:
            if not path.exists():
                _write(path, claim)
        if registry_dir and Path(registry_dir).resolve() != canonical:
            mirror = Path(registry_dir).resolve() / (aliases[0] + ".json")
            if mirror.exists() and _read(mirror) != claim:
                raise RuntimeError("附加登记冲突")
            if not mirror.exists():
                _write(mirror, claim)
            registry_paths.append(mirror)
        run.mkdir(parents=True, exist_ok=True)
        _write(run / "SOURCE.json", source)
        binding = {"schema": VERSION, "run_dir": str(run), "source": source,
                   "source_evidence": evidence, "original_source_paths": [str(p) for p in paths],
                   "source_file": _binding(run / "SOURCE.json"), "code_bindings": _code_bindings(),
                   "protocol": protocol, "contracts": {"version": contracts.VERSION,
                       "schemas": contracts.SCHEMAS, "prompts": contracts.PROMPTS,
                       "review_schema": contracts.REVIEW_SCHEMA, "review_prompt": contracts.REVIEW_PROMPT},
                   "registry": [_binding(p) for p in registry_paths], "story_id": aliases[0],
                   "budget": {"max_calls": max_calls, "max_total_tokens": max_total_tokens, "max_revisions": max_revisions},
                   "legacy_blockers": blockers, "automatic_media_submit": False}
        _write(run / "BINDING.json", binding)
        _write(run / "BINDING_ANCHOR.json", {"sha256": _digest(binding)})
        _save_state(run, {"schema": VERSION, "status": "legacy_dispatch_blocked" if blockers else "prepared",
                         "stage": "analysis", "calls_started": 0, "reported_tokens": 0,
                         "known_reported_tokens": 0, "revisions_used": 0, "pending_call": None,
                         "active": {}, "previous": None, "issues": [], "call_bindings": [],
                         "legacy_calls_started": max((b.get("calls_started") or 0 for b in blockers), default=0),
                         "legacy_reported_tokens": max((b.get("reported_tokens") or 0 for b in blockers), default=0)})
    return inspect(run)


@contextmanager
def _lock(path):
    path = Path(path)
    owner = uuid.uuid4().hex
    _write(path, {"owner": owner, "automatic_unlock": False})
    try:
        yield owner
    finally:
        if path.exists() and _read(path).get("owner") == owner:
            path.unlink()


def _response_errors(record, protocol):
    try:
        return _response_errors_impl(record, protocol)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        return ["原生响应结构不完整或字段类型非法"], None


def _response_errors_impl(record, protocol):
    """Cross-check every acceptance field against the untouched SDK snapshot."""
    errors = []
    meta, native = record.get("response_metadata") or {}, record.get("response_payload") or {}
    if not isinstance(meta, dict) or not isinstance(native, dict):
        return ["缺原生响应或元数据"], None
    usage = native.get("usage") or {}
    known = True
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        left, right = meta.get(key), usage.get(key)
        if type(left) is not int or left < 0 or type(right) is not int or right != left:
            errors.append("原生/metadata用量不全或不一致：" + key)
            known = False
    if known and meta["prompt_tokens"] + meta["completion_tokens"] != meta["total_tokens"]:
        errors.append("用量总数不等于输入加输出")
        known = False
    choices = native.get("choices")
    first = choices[0] if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) else {}
    if not first or meta.get("finish_reason") not in ("stop", "tool_calls") or first.get("finish_reason") != meta.get("finish_reason"):
        errors.append("响应结束不明确或被截断")
    role = record["role"]
    expected = protocol[role]["model"]
    if (not isinstance(meta.get("response_model"), str) or not isinstance(native.get("model"), str)
            or meta["response_model"] != native["model"]
            or not _response_model_matches(role, expected, native["model"])):
        errors.append("实际模型与冻结角色不符")
    if meta.get("requested_model") != expected or meta.get("provider") != protocol[role]["provider"] or meta.get("role") != role:
        errors.append("请求角色/供应商/型号元数据不符")
    if not native.get("id") or meta.get("response_id") != native.get("id"):
        errors.append("响应ID不符")
    message = first.get("message") or {}
    tools = message.get("tool_calls") or []
    if role == "writer":
        if (len(tools) != 1 or tools[0].get("type") != "function"
                or tools[0].get("function", {}).get("name") != "submit_creative_json"
                or meta.get("output_mode") != "tool_call"):
            errors.append("缺少唯一submit_creative_json原生工具")
            native_text = None
        else:
            native_text = tools[0]["function"].get("arguments")
    else:
        native_text = message.get("content")
        if tools or meta.get("output_mode") != "content":
            errors.append("全文审查不是原生正文输出")
    if not isinstance(native_text, str) or not native_text.strip() or record.get("response_text") != native_text:
        errors.append("解析正文与原生响应载荷不一致或为空")
    if meta.get("response_fault_code") or record.get("error"):
        errors.append("原客户端拒绝/未知异常")
    return errors, meta.get("total_tokens") if known else None


def _parse(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("重复JSON键：" + key)
            value[key] = item
        return value
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("原生完整结果不是JSON对象")
    return value


def _verify(run):
    run = Path(run).resolve()
    binding, state = _read(run / "BINDING.json"), _read(run / "state.json")
    if (binding.get("schema") != VERSION or binding.get("run_dir") != str(run)
            or _read(run / "BINDING_ANCHOR.json").get("sha256") != _digest(binding)):
        raise ValueError("任务冻结身份变化")
    snapshots = sorted(run.glob("STATE_*.json"))
    if not snapshots or _read(snapshots[-1]) != state:
        raise ValueError("运行state与不可变检查点不符")
    if binding["protocol"] != _protocol():
        raise ValueError("实际服务协议变化")
    if binding["source"] != _read(run / "SOURCE.json"):
        raise ValueError("来源envelope变化")
    for row in [*binding["source_evidence"], binding["source_file"], *binding["code_bindings"], *binding["registry"]]:
        _verify_file(row)
    for block in binding["legacy_blockers"]:
        _verify_file(block["checkpoint"])
    responses = sorted(run.glob("RESPONSE_*.json"))
    requests = sorted(run.glob("REQUEST_*.json"))
    known = 0
    if state["calls_started"] != len(requests):
        raise RuntimeError("调用账本与原始请求不符")
    for number, path in enumerate(requests, 1):
        request = _read(path)
        if request.get("ordinal") != number or request.get("source_binding_id") != binding["source"]["binding_id"]:
            raise ValueError("调用序列或来源身份变化")
        response_path = run / f"RESPONSE_{number:03}.json"
        if response_path.exists():
            response = _read(response_path)
            if response.get("request_binding") != _binding(path):
                raise ValueError("原生响应未绑定对应原请求")
            _, tokens = _response_errors(response, binding["protocol"])
            if tokens is not None:
                known += tokens
    for row in state["call_bindings"]:
        _verify_file(row)
    if state["known_reported_tokens"] != known or len(responses) > len(requests):
        raise ValueError("已知用量与原生回执不符")
    if state["pending_call"] is None and (len(responses) != len(requests) or len(state["call_bindings"]) != 2 * len(requests)):
        raise RuntimeError("已有未知请求或缺不可变证据，不能派发")
    if state["reported_tokens"] is not None and state["reported_tokens"] != known:
        raise ValueError("累计用量不符")
    if not 0 <= state["revisions_used"] <= binding["budget"]["max_revisions"]:
        raise ValueError("内容返修账本异常")
    for stage, row in state["active"].items():
        _verify_file(row["file"])
        _verify_file(row["receipt"])
        if row["stage"] != stage:
            raise ValueError("阶段产物身份不符")
    return binding, state


def _context(binding, state):
    value = {"source": binding["source"]}
    value.update({stage: _read(row["file"]["path"]) for stage, row in state["active"].items()})
    return value


def _dispatch(run, binding, state, stage, payload, clients):
    _verify(run)
    if state["pending_call"] is not None or state["status"] in TERMINAL:
        raise RuntimeError("任务已停止/存在未决请求，不重新派发")
    stage_key = _digest({"stage": stage, "revision_epoch": state["revisions_used"], "payload": payload})
    for path in sorted(run.glob("REQUEST_*.json")):
        prior = _read(path)
        if prior.get("stage_key") != stage_key:
            continue
        response_path = run / f"RESPONSE_{prior['ordinal']:03}.json"
        response = _read(response_path)
        errors, _ = _response_errors(response, binding["protocol"])
        if errors or response.get("status") != "response_received" or response["request_binding"] != _binding(path):
            raise RuntimeError("原同阶段请求不明确，不能重派")
        return response["response_text"], _binding(response_path)
    if state["calls_started"] >= binding["budget"]["max_calls"]:
        raise RuntimeError("累计调用预算已满")
    role = "director" if stage == "review" else "writer"
    schema = binding["contracts"]["review_schema"] if stage == "review" else binding["contracts"]["schemas"][stage]
    prompt = binding["contracts"]["review_prompt"] if stage == "review" else binding["contracts"]["prompts"][stage]
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]
    max_tokens = 12000 if stage == "review" else 20000
    parameters = {"max_tokens": max_tokens, "temperature": 0.1 if stage == "review" else 0.4,
                  "thinking": "disabled", "structured_schema": schema if role == "writer" else None}
    request_bytes = len(json.dumps({"messages": messages, "parameters": parameters}, ensure_ascii=False).encode("utf-8"))
    reservation = request_bytes + max_tokens + 4096
    if request_bytes > MAX_REQUEST_BYTES:
        raise RuntimeError("完整输入超过本路线保守上下文上限，未截文、未派发")
    if state["known_reported_tokens"] + reservation > binding["budget"]["max_total_tokens"]:
        raise RuntimeError("累计token预算不足以预留完整请求，未派发")
    # A newly appeared legacy stop also blocks an already prepared directory.
    if _legacy_blocks(binding["source"], [Path(p) for p in binding["original_source_paths"]]):
        raise RuntimeError("检测到同故事历史停止证据，禁止新派发")
    number = state["calls_started"] + 1
    request_path = run / f"REQUEST_{number:03}.json"
    request = {"schema": VERSION, "ordinal": number, "stage": stage, "stage_key": stage_key, "role": role,
               "source_binding_id": binding["source"]["binding_id"], "messages": messages,
               "parameters": parameters, "context_sha256": _digest(payload),
               "input_bindings": deepcopy(state["active"]), "reservation_tokens": reservation}
    _write(request_path, request)
    state.update(calls_started=number, pending_call=number, status="running")
    _save_state(run, state)
    response = {"schema": VERSION, "ordinal": number, "stage": stage, "role": role,
                "request_binding": _binding(request_path)}
    try:
        result = clients.call(role, messages, **parameters)
        response.update(response_text=result.text, response_metadata=result.metadata,
                        response_payload=result.response_payload)
    except Exception as exc:
        response.update(error=str(exc), response_text=getattr(exc, "response_text", None),
                        response_metadata=getattr(exc, "response_metadata", {}),
                        response_payload=getattr(exc, "response_payload", None))
    errors, tokens = _response_errors(response, binding["protocol"])
    response.update(status="response_rejected" if errors else "response_received", response_errors=errors)
    response_path = run / f"RESPONSE_{number:03}.json"
    _write(response_path, response)
    state["call_bindings"] += [_binding(request_path), _binding(response_path)]
    if tokens is not None:
        state["known_reported_tokens"] += tokens
    state["reported_tokens"] = state["known_reported_tokens"] if tokens is not None else None
    if errors:
        state.update(status="needs_attention", halt_reason="；".join(errors))
        _save_state(run, state)
        raise RuntimeError(state["halt_reason"])
    state["pending_call"] = None
    _save_state(run, state)
    return response["response_text"], _binding(response_path)


def _repair(run, binding, state, stage, issues, previous):
    """One global repair round; downstream products are invalidated together."""
    state["issues"] = issues
    if state["revisions_used"] >= binding["budget"]["max_revisions"]:
        state.update(status="content_revision_exhausted", halt_reason="全运行完整内容返修额度已耗尽")
        _save_state(run, state)
        return False
    targets = [row.get("responsible_stage", stage) for row in issues
               if row.get("severity") in ("blocking", "major")]
    responsible = min((target for target in targets if target in contracts.STAGES),
                      key=contracts.STAGES.index, default=stage)
    old = state["active"].get(responsible)
    state["previous"] = _read(old["file"]["path"]) if old else previous
    for target in (*contracts.STAGES, "review"):
        if target == "review" or contracts.STAGES.index(target) >= contracts.STAGES.index(responsible):
            state["active"].pop(target, None)
    state.update(stage=responsible, revisions_used=state["revisions_used"] + 1, status="needs_full_revision")
    _save_state(run, state)
    return True


def _complete(run, binding, state):
    context = _context(binding, state)
    for stage, filename in (("analysis", "ANALYSIS.json"), ("adaptation_plan", "ADAPTATION_PLAN.json"),
                            ("screenplay", "SCREENPLAY.json"), ("review", "FULL_TEXT_REVIEW.json")):
        _ensure(run / filename, context[stage])
    reading_bytes = contracts.render_screenplay(context["screenplay"]).encode("utf-8")
    reading_path = run / "SCREENPLAY.md"
    if reading_path.exists():
        if reading_path.read_bytes() != reading_bytes:
            raise ValueError("既有阅读稿不符，不覆盖")
    else:
        with reading_path.open("xb") as stream:
            stream.write(reading_bytes)
    handoff = {"schema": VERSION, "status": "text_ready_for_director", "source": binding["source"],
               "analysis": _binding(run / "ANALYSIS.json"), "adaptation_plan": _binding(run / "ADAPTATION_PLAN.json"),
               "screenplay": _binding(run / "SCREENPLAY.json"), "reading_copy": _binding(run / "SCREENPLAY.md"),
               "review": _binding(run / "FULL_TEXT_REVIEW.json"), "stages": deepcopy(state["active"]),
               "human_approved": False, "automatic_media_submit": False,
               "next_stage": "director_planning_not_yet_generated"}
    _ensure(run / "DIRECTOR_HANDOFF.json", handoff)
    files = [_binding(run / name) for name in ("ANALYSIS.json", "ADAPTATION_PLAN.json", "SCREENPLAY.json",
                                              "SCREENPLAY.md", "FULL_TEXT_REVIEW.json", "DIRECTOR_HANDOFF.json")]
    manifest = {"schema": VERSION, "source_binding_id": binding["source"]["binding_id"],
                "files": files, "stages": deepcopy(state["active"]), "human_approved": False}
    _ensure(run / "OUTPUT_MANIFEST.json", manifest)
    state.update(status="text_ready_for_director", stage="complete", output_manifest=_binding(run / "OUTPUT_MANIFEST.json"),
                 previous=None, issues=[])
    _save_state(run, state)


def execute(run_dir, *, clients=None):
    """Run the independent text route. All network access is in clients.call."""
    run = Path(run_dir).resolve()
    with _lock(run / ".execution.lock") as owner:
        binding, state = _verify(run)
        if state["status"] in TERMINAL or state["pending_call"] is not None:
            return inspect(run, _lock_owner=owner)
        clients = clients or CreativeRoleClients()
        try:
            while True:
                if all(stage in state["active"] for stage in (*contracts.STAGES, "review")):
                    context = _context(binding, state)
                    if (contracts.validate_review(context["review"], context)
                            or any(row["severity"] in ("major", "blocking") for row in context["review"]["issues"])):
                        raise RuntimeError("已保存全文审查不合格，不能恢复交付")
                    _complete(run, binding, state)
                    return inspect(run, _lock_owner=owner)
                stage = state["stage"]
                context = _context(binding, state)
                payload = {**context, "output_schema": binding["contracts"]["review_schema"] if stage == "review"
                           else binding["contracts"]["schemas"][stage]}
                if stage != "review" and state.get("previous") is not None:
                    payload.update(previous_value=state["previous"], issues=state["issues"])
                native_text, receipt = _dispatch(run, binding, state, stage, payload, clients)
                try:
                    value = _parse(native_text)
                    issues = contracts.validate_review(value, context) if stage == "review" else contracts.validate_stage(stage, value, context)
                except (ValueError, TypeError) as exc:
                    value = None
                    issues = [{"code": "INVALID_COMPLETE_JSON", "path": "$", "message": str(exc),
                               "severity": "major", "responsible_stage": stage}]
                output = run / f"{stage.upper()}_{state['calls_started']:03}.json"
                if value is not None:
                    _ensure(output, value)
                _ensure(run / f"VALIDATION_{state['calls_started']:03}.json", {
                    "stage": stage, "issues": issues, "receipt": receipt,
                    "draft": _binding(output) if value is not None else None})
                major = [row for row in issues if row.get("severity") in ("blocking", "major")]
                if major:
                    if stage == "review":
                        # An invalid audit is not authority to rewrite the story.
                        raise RuntimeError("全文审查合同无效，保存原证据停止，不代写审查或重派")
                    if not _repair(run, binding, state, stage, issues, value if value is not None else native_text):
                        return inspect(run, _lock_owner=owner)
                    continue
                state["active"][stage] = {"stage": stage, "file": _binding(output), "receipt": receipt}
                state["previous"] = None
                state["issues"] = []
                if stage == "review":
                    findings = [row for row in value["issues"] if row["severity"] in ("blocking", "major")]
                    if findings:
                        if not _repair(run, binding, state, "screenplay", value["issues"], context["screenplay"]):
                            return inspect(run, _lock_owner=owner)
                        continue
                    _save_state(run, state)
                    _complete(run, binding, state)
                    return inspect(run, _lock_owner=owner)
                next_index = contracts.STAGES.index(stage) + 1
                state.update(stage=contracts.STAGES[next_index] if next_index < len(contracts.STAGES) else "review", status="running")
                _save_state(run, state)
        except Exception as exc:
            # Do not create a misleading checkpoint after evidence write failure.
            if (run / "state.json").exists():
                saved = _read(run / "state.json")
                if saved == state:
                    state.update(status="needs_attention", halt_reason=str(exc))
                    _save_state(run, state)
            raise


def _verify_complete(run, binding, state):
    _verify_file(state["output_manifest"])
    manifest = _read(run / "OUTPUT_MANIFEST.json")
    if manifest["source_binding_id"] != binding["source"]["binding_id"] or manifest["stages"] != state["active"]:
        raise ValueError("交付清单来源/稿件绑定不符")
    for row in manifest["files"]:
        _verify_file(row)
    context = _context(binding, state)
    for stage in contracts.STAGES:
        if contracts.validate_stage(stage, context[stage], context):
            raise ValueError("已完成稿件内容合同失效：" + stage)
    if contracts.validate_review(context["review"], context):
        raise ValueError("全文审查合同失效")
    if any(row["severity"] in ("blocking", "major") for row in context["review"]["issues"]):
        raise ValueError("全文审查仍有必修问题")
    for stage in (*contracts.STAGES, "review"):
        row = state["active"][stage]
        receipt = _read(row["receipt"]["path"])
        request = _read(receipt["request_binding"]["path"])
        payload = json.loads(request["messages"][-1]["content"])
        errors, _ = _response_errors(receipt, binding["protocol"])
        if (errors or _parse(receipt["response_text"]) != context[stage]
                or payload["source"] != binding["source"] or receipt["stage"] != stage):
            raise ValueError("输出不对应已验收原生完整响应")
        if stage == "review" and any(payload.get(key) != context[key] for key in contracts.STAGES):
            raise ValueError("全文审查未读取同一来源/完整当前稿")
        if stage != "review":
            for upstream in contracts.STAGES[:contracts.STAGES.index(stage)]:
                if payload.get(upstream) != context[upstream]:
                    raise ValueError("下游稿未绑定当前上游")
    if (run / "SCREENPLAY.md").read_bytes() != contracts.render_screenplay(context["screenplay"]).encode("utf-8"):
        raise ValueError("阅读稿不是完整原生稿确定性投影")
    for stage, name in (("analysis", "ANALYSIS.json"), ("adaptation_plan", "ADAPTATION_PLAN.json"),
                        ("screenplay", "SCREENPLAY.json"), ("review", "FULL_TEXT_REVIEW.json")):
        if _read(run / name) != context[stage]:
            raise ValueError("交付正文与原生阶段产物不一致")
    return manifest


def inspect(run_dir, *, _lock_owner=None):
    """Read-only inspection; completed status is earned again from evidence."""
    run = Path(run_dir).resolve()
    if not (run / "BINDING.json").exists():
        return {"schema": VERSION, "run_dir": str(run), "status": "unprepared", "artifacts": {},
                "dispatch_blocked": True, "blockers": ["任务未准备"], "human_approved": False}
    binding, state = _read(run / "BINDING.json"), _read(run / "state.json")
    status, blockers, manifest = state["status"], [], None
    try:
        _verify(run)
        if status == "text_ready_for_director":
            manifest = _verify_complete(run, binding, state)
    except Exception as exc:
        status = "incomplete_artifacts" if state["status"] == "text_ready_for_director" else "evidence_invalid"
        blockers.append(str(exc))
    blockers += [row["reason"] for row in binding.get("legacy_blockers", [])]
    if state.get("pending_call") is not None:
        blockers.append("保留未决/截断派发门，不自动重派")
    if state.get("halt_reason"):
        blockers.append(state["halt_reason"])
    if (run / ".execution.lock").exists() and _read(run / ".execution.lock").get("owner") != _lock_owner:
        blockers.append("运行锁存在；不自动解除")
    return {"schema": VERSION, "run_dir": str(run), "status": status, "stage": state.get("stage"),
            "source": binding["source"], "calls_started": state["calls_started"],
            "reported_tokens": state["reported_tokens"], "known_reported_tokens": state["known_reported_tokens"],
            "revisions_used": state["revisions_used"], "state": state, "blockers": blockers,
            "dispatch_blocked": bool(blockers) or status in TERMINAL,
            "artifacts": {Path(row["path"]).name: row for row in manifest["files"]} if manifest else {},
            "human_approved": False, "automatic_media_submit": False}


def preview(run_dir):
    view = inspect(run_dir)
    if view["status"] == "unprepared":
        return view
    binding = _read(Path(run_dir) / "BINDING.json")
    return {**view, "budget": binding["budget"], "provider_protocol": binding["protocol"],
            "remaining_calls": max(0, binding["budget"]["max_calls"] - view["calls_started"]),
            "remaining_known_tokens": max(0, binding["budget"]["max_total_tokens"] - view["known_reported_tokens"]),
            "stages": [*contracts.STAGES, "review"], "legacy_consumption": binding["legacy_blockers"]}
