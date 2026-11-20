"""Explicitly authorized production continuation; frozen v1 remains unchanged.

Each run owns an isolated engine namespace. The authorization exempts exactly
one audited legacy checkpoint, never an unknown response or another story stop.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import FunctionType, SimpleNamespace

from . import novel_adaptation_pipeline_v1 as core

VERSION = "novel_adaptation_production/v2"
AUTH_SCHEMA = "novel_adaptation_production_authorization/v2"
ROOT = core.ROOT
CANONICAL_REGISTRY = core.CANONICAL_REGISTRY


def _audit_authorization(path, run):
    path, run = Path(path).resolve(), Path(run).resolve()
    auth = core._read(path)
    if (auth.get("schema") != AUTH_SCHEMA or auth.get("user_instruction") != "生成环境真实生成验收"
            or Path(auth["run_dir"]).resolve() != run or not auth.get("book_id")
            or auth.get("automatic_media_submit") is not False
            or auth.get("allowed_stages") != [*core.contracts.STAGES, "review"]):
        raise ValueError("生产授权身份、精确范围或媒体边界不符")
    checkpoint_binding = auth["legacy_checkpoint"]
    core._verify_file(checkpoint_binding)
    checkpoint = core._read(checkpoint_binding["path"])
    old, original, new = auth["legacy_totals"], auth["original_budget"], auth["new_budget"]
    if (str(checkpoint.get("book_id")) != str(auth["book_id"])
            or checkpoint.get("status") != "stopped_response_truncated"
            or checkpoint.get("calls_started") != old.get("calls_started")
            or checkpoint.get("known_reported_tokens") != old.get("reported_tokens")):
        raise ValueError("历史停点身份或消耗不符")
    if (original != {"max_calls": 20, "max_total_tokens": 500000}
            or old != {"calls_started": 11, "reported_tokens": 180079}
            or new != {"max_calls": 9, "max_total_tokens": 319921, "max_revisions": 2}):
        raise ValueError("本次授权不得重领旧调用、用量或扩大预算")
    records = checkpoint.get("records")
    responses = auth.get("legacy_responses")
    if not isinstance(records, list) or len(records) != 11 or not isinstance(responses, list) or len(responses) != 11:
        raise ValueError("缺完整历史11份原生回执")
    total = 0
    for ordinal, (record, binding) in enumerate(zip(records, responses, strict=True), 1):
        core._verify_file(binding)
        if (record.get("ordinal") != ordinal or record.get("path") != binding["path"]
                or record.get("sha256") != binding["sha256"]):
            raise ValueError("历史回执顺序或SHA绑定不符")
        response = core._read(binding["path"])
        meta, native = response.get("response_metadata"), response.get("response_payload")
        if not isinstance(meta, dict) or not isinstance(native, dict):
            raise ValueError("历史原生结果未知")
        usage = native.get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if type(meta.get(key)) is not int or meta[key] < 0 or usage.get(key) != meta[key] or type(usage.get(key)) is not int:
                raise ValueError("历史原生用量未知或不一致")
        choices = native.get("choices")
        reason = meta.get("finish_reason")
        if (meta["prompt_tokens"] + meta["completion_tokens"] != meta["total_tokens"]
                or not isinstance(choices, list) or len(choices) != 1
                or choices[0].get("finish_reason") != reason
                or reason not in (("length",) if ordinal == 11 else ("stop", "tool_calls"))
                or record.get("finish_reason") != reason or record.get("reported_tokens") != meta["total_tokens"]
                or native.get("id") != meta.get("response_id") or not native.get("id")
                or native.get("model") != meta.get("response_model") or not native.get("model")):
            raise ValueError("历史响应未明确终止或原生身份不符")
        if ordinal == 11 and meta.get("response_fault_code") != "RESPONSE_TRUNCATED":
            raise ValueError("第11次必须是已收到的明确截断停点")
        total += meta["total_tokens"]
    if total != old["reported_tokens"]:
        raise ValueError("历史累计用量不符")
    return auth


def _engine(auth_path, run):
    """Clone only core-owned functions; never mutate core globals or wrappers."""
    namespace = dict(core.__dict__)
    for name, value in core.__dict__.items():
        if isinstance(value, FunctionType) and value.__globals__ is core.__dict__:
            cloned = FunctionType(value.__code__, namespace, value.__name__, value.__defaults__, value.__closure__)
            cloned.__kwdefaults__ = value.__kwdefaults__
            namespace[name] = cloned
    raw_lock = core._lock.__wrapped__
    namespace["_lock"] = contextmanager(FunctionType(raw_lock.__code__, namespace, raw_lock.__name__,
                                                   raw_lock.__defaults__, raw_lock.__closure__))
    namespace.update(VERSION=VERSION, ROOT=ROOT, CANONICAL_REGISTRY=CANONICAL_REGISTRY)
    original_verify = namespace["_verify"]

    def legacy_blocks(source, paths, legacy_parent=None):
        auth = _audit_authorization(auth_path, run)
        blocks = core._legacy_blocks(source, paths, legacy_parent)
        allowed = auth["legacy_checkpoint"]
        return [row for row in blocks if row["checkpoint"] != allowed]

    def verify(directory):
        binding, state = original_verify(directory)
        core._verify_file(binding["production_authorization"])
        auth = _audit_authorization(binding["production_authorization"]["path"], directory)
        _verify_source(auth, binding["source"])
        if binding["budget"] != auth["new_budget"] or binding["legacy_consumption"] != auth["legacy_totals"]:
            raise ValueError("生产剩余额度或历史累计绑定不符")
        return binding, state

    namespace.update(_verify=verify, _legacy_blocks=legacy_blocks)
    return SimpleNamespace(**namespace)


def _verify_source(auth, source):
    if str(source["book_id"]) != str(auth["book_id"]):
        raise ValueError("生产来源book_id与授权不符")
    if any(source[key] != auth["source_identity"].get(key) for key in
           ("full_source_sha256", "excerpt_sha256", "binding_id")):
        raise ValueError("生产完整源或选段身份与授权不符")


def prepare(run_dir, *, authorization):
    """Freeze the new scope, inherit old consumption, and register one story."""
    run, authorization = Path(run_dir).resolve(), Path(authorization).resolve()
    auth = _audit_authorization(authorization, run)
    engine = _engine(authorization, run)
    if (run / "BINDING.json").exists():
        engine._verify(run)
        return inspect(run)
    if run.exists() and any(run.iterdir()):
        raise ValueError("新生产目录必须为空")
    protocol = core._protocol()
    if protocol["writer"]["model"] != "MiniMax-M3" or protocol["director"]["model"] != "deepseek-flash":
        raise ValueError("本次生产仅已确认的MiniMax/DeepSeek协议")
    source, evidence, paths = core._source(None, auth["acquisition_receipt"], auth.get("title"),
                                         auth["book_id"], auth.get("scope"))
    _verify_source(auth, source)
    blockers = engine._legacy_blocks(source, paths)
    canonical = CANONICAL_REGISTRY.resolve()
    canonical.mkdir(parents=True, exist_ok=True)
    aliases = ["source_" + source["full_source_sha256"], "book_" + core._digest(source["book_id"]),
               "title_" + core._digest(source["title"].strip())]
    registry_paths = [canonical / (alias + ".json") for alias in aliases]
    with engine._lock(canonical / ".registration.lock"):
        _audit_authorization(authorization, run)
        claim = {"schema": VERSION, "run_dir": str(run), "source_binding_id": source["binding_id"],
                 "story_id": aliases[0], "production_authorization": core._binding(authorization)}
        for path in registry_paths:
            if path.exists() and core._read(path) != claim:
                raise RuntimeError("同故事已有登记，不得改目录重领额度")
        for path in registry_paths:
            if not path.exists():
                core._write(path, claim)
        run.mkdir(parents=True, exist_ok=True)
        core._write(run / "SOURCE.json", source)
        code = core._code_bindings() + [core._binding(__file__), core._binding(ROOT / "scripts/run_novel_adaptation_production_v2.py")]
        binding = {"schema": VERSION, "run_dir": str(run), "source": source,
                   "source_evidence": evidence, "original_source_paths": [str(p) for p in paths],
                   "source_file": core._binding(run / "SOURCE.json"), "code_bindings": code,
                   "protocol": protocol, "contracts": {"version": core.contracts.VERSION,
                       "schemas": core.contracts.SCHEMAS, "prompts": core.contracts.PROMPTS,
                       "review_schema": core.contracts.REVIEW_SCHEMA, "review_prompt": core.contracts.REVIEW_PROMPT},
                   "registry": [core._binding(p) for p in registry_paths], "story_id": aliases[0],
                   "budget": auth["new_budget"], "legacy_blockers": blockers,
                   "production_authorization": core._binding(authorization),
                   "legacy_consumption": auth["legacy_totals"], "automatic_media_submit": False}
        core._write(run / "BINDING.json", binding)
        core._write(run / "BINDING_ANCHOR.json", {"sha256": core._digest(binding)})
        core._save_state(run, {"schema": VERSION, "status": "legacy_dispatch_blocked" if blockers else "prepared",
                              "stage": "analysis", "calls_started": 0, "reported_tokens": 0,
                              "known_reported_tokens": 0, "revisions_used": 0, "pending_call": None,
                              "active": {}, "previous": None, "issues": [], "call_bindings": [],
                              "legacy_calls_started": 11, "legacy_reported_tokens": 180079})
    return inspect(run)


def _for_run(run_dir):
    run = Path(run_dir).resolve()
    binding = core._read(run / "BINDING.json")
    return _engine(binding["production_authorization"]["path"], run)


def inspect(run_dir, *, _lock_owner=None):
    view = _for_run(run_dir).inspect(run_dir, _lock_owner=_lock_owner)
    view["legacy_consumption"] = {"calls_started": 11, "reported_tokens": 180079}
    view["combined_calls_started"] = 11 + view["calls_started"]
    view["combined_known_reported_tokens"] = 180079 + view["known_reported_tokens"]
    return view


def preview(run_dir):
    view = _for_run(run_dir).preview(run_dir)
    return {**view, **{k: v for k, v in inspect(run_dir).items() if k.startswith("combined_")},
            "legacy_consumption": {"calls_started": 11, "reported_tokens": 180079}}


def execute(run_dir, *, clients=None):
    _for_run(run_dir).execute(run_dir, clients=clients)
    return inspect(run_dir)
