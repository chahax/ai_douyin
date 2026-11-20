"""One explicit compact-ferry video trial; no text-model or media retry path."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from . import novel_adaptation_pipeline_v1 as core
from . import seedance_client as seedance
from . import seedance_models, media_review_policy, assistant_seedance_trial
from .assistant_seedance_trial import last_frame_integrity

VERSION = "compact_ferry_video_trial/v1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = ROOT / "data/video_generation/novel_ferry_compact_trial_20261018/S01"
SOURCE_ROOT = ROOT / "data/narrative_pacing_revision/20261018_compact_v1"
REGISTRY = ROOT / "data/novel_video_trial_registry_v1"
SCOPE_ID = "compact_ferry_20261018_S01"
SOURCE_BINDING = "35b2a809bf62b7b7021c3005193690cd09902eee38eea602d3cb0691588c9ca7"
INHERITED_FAILURES = 2
AUTHORIZATION = dict(user_statement="试试第一段", max_new_submissions=1,
                     automatic_retry=False, continuation_authorized=False,
                     publishing_authorized=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _durable(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _paths():
    registry = Path(REGISTRY).resolve()
    scope = registry / SCOPE_ID
    return registry, scope, scope / "SUBMISSION_CLAIM.json", scope / "MEDIA_EVENTS.json", registry / ("story_" + SOURCE_BINDING + ".json")


def _config(*, require_key=False):
    config = seedance.SeedanceConfig.from_env("ark_api", require_key=require_key)
    _client_config(config)
    return config


def _client_config(config):
    if (config.provider != "ark_api" or config.model != seedance.ARK_MINI_MODEL
            or config.base_url != seedance.ARK_BASE_URL):
        raise ValueError("本次固定官方Ark Seedance 2.0 Mini协议")


def _payload(prompt):
    with seedance.SeedanceClient(_config(), record_calls=False) as client:
        return client.build_task_payload(prompt, duration=10, ratio="9:16", resolution="720p",
            generate_audio=True, return_last_frame=True, references=[], task_type="text")


def _code_bindings():
    paths = [Path(module.__file__) for module in
             (core, seedance, seedance_models, media_review_policy, assistant_seedance_trial)]
    paths += [Path(__file__), seedance_models.CATALOG, ROOT / "scripts/run_compact_ferry_video_trial_v1.py"]
    return [core._binding(path) for path in paths]


def _source_files(run):
    source = Path(SOURCE_ROOT).resolve()
    return [source / "COMPACT_PACING_DRAFT.md", source / "PROPOSAL.json",
            run / "FIRST_SEGMENT.json", run / "AUTHORIZATION.json", run / "PROMPT.txt"]


def _validate_inputs(run):
    paths = _source_files(run)
    if not paths[0].read_text(encoding="utf-8").strip():
        raise ValueError("缺少完整压缩候选文本")
    proposal = core._read(paths[1])
    if not isinstance(proposal, dict):
        raise ValueError("PROPOSAL必须是对象")
    segment, auth = core._read(paths[2]), core._read(paths[3])
    if any(value.get("source_binding") != SOURCE_BINDING for value in (proposal, segment, auth)):
        raise ValueError("候选、首段或授权与渡口原故事身份不符")
    if (segment.get("authored_by") != "primary_assistant"
            or segment.get("segment", {}).get("id") != "S01"
            or type(segment.get("segment", {}).get("duration_seconds")) is not int
            or segment["segment"]["duration_seconds"] != 10):
        raise ValueError("本次仅覆盖助手编辑候选S01的10秒首段")
    if any(auth.get(key) != value or type(auth.get(key)) is not type(value)
           for key, value in AUTHORIZATION.items()):
        raise ValueError("首段单次授权不符")
    prompt = paths[4].read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("提示词为空")
    return paths, prompt


def _ledger(plan):
    core._verify_file(plan["historical_counter"])
    counter = core._read(plan["historical_counter"]["path"])
    if (counter.get("source_binding") != SOURCE_BINDING or counter.get("failure_limit") != 10
            or type(counter.get("failures_used")) is not int or counter["failures_used"] != INHERITED_FAILURES):
        raise ValueError("原同故事失败计数发生变化或被重置")
    events = core._read(plan["media_events"])
    if (events.get("schema") != VERSION or events.get("scope_id") != SCOPE_ID
            or events.get("historical_counter") != plan["historical_counter"]
            or events.get("inherited_failures") != INHERITED_FAILURES or events.get("failure_limit") != 10):
        raise ValueError("新增媒体账本来源绑定不符")
    rows = events.get("events")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("新增媒体账本事件不完整")
    keys = [row.get("event_id") for row in rows]
    failed = [row for row in rows if row.get("failure") is True]
    if (any(not isinstance(key, str) or not key for key in keys) or len(keys) != len(set(keys))
            or events.get("new_failures") != len(failed)
            or events.get("combined_known_failures") != INHERITED_FAILURES + len(failed)):
        raise ValueError("新增媒体账本失败累计不符")
    return events


def _event(plan, event_id, *, failure=False, **details):
    """Caller holds the shared story registry lock; historical ledger is read-only."""
    events = _ledger(plan)
    old = next((row for row in events["events"] if row["event_id"] == event_id), None)
    if old is not None:
        if old.get("failure") != failure or any(old.get(key) != value for key, value in details.items()):
            raise ValueError("已有媒体事件身份不符")
        return
    events["events"].append(dict(event_id=event_id, at=_now(), failure=failure, **details))
    events["new_failures"] = sum(row["failure"] is True for row in events["events"])
    events["combined_known_failures"] = INHERITED_FAILURES + events["new_failures"]
    _save(plan["media_events"], events)


def prepare(run_dir=DEFAULT_RUN):
    run = Path(run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    with core._lock(run / ".execution.lock"):
        if any((run / name).exists() for name in ("PLAN.json", "REQUEST.json", "state.json", "SUBMISSION_CLAIM.json")):
            raise ValueError("已有准备或派发证据，禁止覆盖")
        paths, prompt = _validate_inputs(run)
        registry, scope, claim, events, counter_path = _paths()
        registry.mkdir(parents=True, exist_ok=True)
        scope.mkdir(parents=True, exist_ok=True)
        counter = core._read(counter_path)
        if (counter.get("source_binding") != SOURCE_BINDING or counter.get("failure_limit") != 10
                or type(counter.get("failures_used")) is not int or counter["failures_used"] != INHERITED_FAILURES):
            raise ValueError("必须承接原同故事2/10，不得创建或重置旧账本")
        historical = core._binding(counter_path)
        plan = dict(schema=VERSION, scope_id=SCOPE_ID, source_binding=SOURCE_BINDING,
            segment_id="S01", duration_seconds=10, provider="ark_api", model=seedance.ARK_MINI_MODEL,
            asset_mode="text_only_no_cast_approval", created_at=_now(),
            source_files=[core._binding(path) for path in paths], code_bindings=_code_bindings(),
            historical_counter=historical, canonical_claim=str(claim), media_events=str(events),
            authorization=AUTHORIZATION, text_status="assistant_edited_candidate_not_new_minimax_or_deepseek_pass",
            media_review="user_manual_only", source_root=str(Path(SOURCE_ROOT).resolve()))
        with core._lock(registry / ".registry.lock"):
            if claim.exists():
                raise ValueError("本次首段永久claim已存在，只可查询原ID")
            if not events.exists():
                _durable(events, dict(schema=VERSION, scope_id=SCOPE_ID, historical_counter=historical,
                    inherited_failures=INHERITED_FAILURES, failure_limit=10, new_failures=0,
                    combined_known_failures=INHERITED_FAILURES, events=[]))
            if _ledger(plan)["combined_known_failures"] >= 10:
                raise ValueError("同故事失败上限已达")
        request = _payload(prompt)
        _durable(run / "REQUEST.json", request)
        plan["request"] = core._binding(run / "REQUEST.json")
        _durable(run / "PLAN.json", plan)
        _save(run / "state.json", dict(schema=VERSION, status="prepared_not_submitted", task_id=None,
            submissions_started=0, content_status="not_generated"))
    return inspect(run)


def _verify(run):
    plan = core._read(run / "PLAN.json")
    registry, scope, claim, events, counter = _paths()
    if (plan.get("schema") != VERSION or plan.get("scope_id") != SCOPE_ID
            or plan.get("source_binding") != SOURCE_BINDING or plan.get("segment_id") != "S01"
            or plan.get("duration_seconds") != 10 or plan.get("authorization") != AUTHORIZATION
            or plan.get("canonical_claim") != str(claim) or plan.get("media_events") != str(events)
            or Path(plan.get("historical_counter", {}).get("path", "")).resolve() != counter
            or plan.get("source_root") != str(Path(SOURCE_ROOT).resolve())):
        raise ValueError("首段固定范围或账本绑定不符")
    paths, prompt = _validate_inputs(run)
    if plan.get("source_files") != [core._binding(path) for path in paths]:
        raise ValueError("冻结源文件变化")
    if plan.get("code_bindings") != _code_bindings():
        raise ValueError("冻结执行代码变化")
    core._verify_file(plan["request"])
    if Path(plan["request"]["path"]).resolve() != run / "REQUEST.json":
        raise ValueError("请求位置变化")
    payload = core._read(run / "REQUEST.json")
    if payload != _payload(prompt):
        raise ValueError("请求与冻结10秒无参考图参数不符")
    _ledger(plan)
    return plan, payload


def _claim(run, plan):
    canonical, local = core._read(plan["canonical_claim"]), core._read(run / "SUBMISSION_CLAIM.json")
    if (canonical != local or canonical.get("run_dir") != str(run) or canonical.get("scope_id") != SCOPE_ID
            or canonical.get("max_submissions") != 1 or canonical.get("request") != core._binding(run / "REQUEST.json")
            or canonical.get("plan") != core._binding(run / "PLAN.json")):
        raise ValueError("原永久派发claim不匹配")
    return canonical


def inspect(run_dir=DEFAULT_RUN):
    run = Path(run_dir).resolve()
    if not (run / "PLAN.json").exists():
        return dict(schema=VERSION, status="unprepared", run_dir=str(run))
    try:
        plan, payload = _verify(run)
        state = core._read(run / "state.json")
        result = dict(schema=VERSION, run_dir=str(run), **{key: state.get(key) for key in
            ("status", "task_id", "submissions_started", "technical_status", "content_status")},
            failures=_ledger(plan)["combined_known_failures"], failure_limit=10,
            claim_exists=Path(plan["canonical_claim"]).exists(), human_approved=False,
            continuation_authorized=False, text_status=plan["text_status"])
        if result["claim_exists"]:
            _claim(run, plan)
        if (run / "receipt.json").exists():
            receipt = core._read(run / "receipt.json")
            native = core._read(run / "NATIVE_SUBMIT_RESPONSE.json")
            expected_sources = {Path(row["path"]).name: row for row in plan["source_files"]}
            if (receipt.get("schema") != VERSION or receipt.get("scope_id") != SCOPE_ID
                    or receipt.get("segment_id") != "S01" or receipt.get("source_binding") != SOURCE_BINDING
                    or receipt.get("provider") != "ark_api" or receipt.get("model") != seedance.ARK_MINI_MODEL
                    or receipt.get("task_id") != native.get("id") or receipt.get("task_id") != state.get("task_id")
                    or receipt.get("plan_sha256") != core._binding(run / "PLAN.json")["sha256"]
                    or receipt.get("plan") != str(run / "PLAN.json") or receipt.get("request") != payload
                    or receipt.get("request_sha256") != core._digest(payload)
                    or receipt.get("request_file_binding") != plan["request"]
                    or receipt.get("source_bindings") != expected_sources
                    or receipt.get("status") != "succeeded_awaiting_human_review"
                    or receipt.get("technical_status") != "succeeded"
                    or receipt.get("content_status") != "awaiting_human_review"
                    or any(receipt.get(key) is not False for key in ("human_approved", "content_inspection_performed",
                        "posthoc_frame_extraction", "audio_or_asr_review_performed", "continuation_authorized",
                        "publishing_authorized", "automatic_retry"))):
                raise ValueError("视频回执与原生ID、计划、来源、实际请求或人工待审状态不符")
            for key in ("video", "native_tail", "metadata", "tail_integrity"):
                core._verify_file(receipt[key])
            if (receipt.get("video_path") != receipt["video"]["path"]
                    or receipt.get("video_sha256") != receipt["video"]["sha256"]
                    or receipt.get("last_frame") != receipt["native_tail"]["path"]
                    or receipt.get("last_frame_sha256") != receipt["native_tail"]["sha256"]):
                raise ValueError("视频或原生尾帧回执身份不符")
            result.update(video_path=receipt["video_path"], native_tail=receipt["last_frame"],
                          content_status=receipt["content_status"], status=receipt["status"])
        return result
    except Exception as exc:
        return dict(schema=VERSION, run_dir=str(run), status="evidence_invalid", error=str(exc))


def submit(run_dir=DEFAULT_RUN, *, client=None):
    run = Path(run_dir).resolve()
    with core._lock(run / ".execution.lock"):
        plan, payload = _verify(run)
        state = core._read(run / "state.json")
        if state.get("submissions_started") or state.get("task_id") or (run / "SUBMISSION_CLAIM.json").exists():
            raise ValueError("仅允许一次POST；此后只可query原ID")
        own = client is None
        client = client or seedance.SeedanceClient(_config(require_key=True))
        try:
            _client_config(client.config)
            registry = _paths()[0]
            with core._lock(registry / ".registry.lock"):
                if Path(plan["canonical_claim"]).exists():
                    raise ValueError("永久claim已存在，不得换目录重派")
                if _ledger(plan)["combined_known_failures"] >= 10:
                    raise ValueError("同故事失败上限已达")
                claim = dict(schema=VERSION, scope_id=SCOPE_ID, run_dir=str(run), created_at=_now(),
                    max_submissions=1, plan=core._binding(run / "PLAN.json"), request=core._binding(run / "REQUEST.json"))
                _durable(plan["canonical_claim"], claim)
                _durable(run / "SUBMISSION_CLAIM.json", claim)
                _event(plan, "dispatch_reserved", request_sha256=claim["request"]["sha256"])
            state.update(status="submit_outcome_unknown", submissions_started=1, technical_status="unknown")
            _save(run / "state.json", state)
            try:
                response = client.create_task(payload)
                _durable(run / "NATIVE_SUBMIT_RESPONSE.json", response)
                if not isinstance(response.get("id"), str) or not response["id"]:
                    raise ValueError("提交缺原生任务ID，禁止重派")
                state.update(status="submitted", task_id=response["id"], technical_status="running")
                _save(run / "state.json", state)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                rejected = type(status) is int and 400 <= status < 500
                _save(run / "SUBMIT_ERROR.json", dict(at=_now(), error_type=type(exc).__name__,
                    http_status=status, error_code=getattr(exc, "error_code", None), automatic_retry=False,
                    message=str(exc).replace(client.config.api_key, "[redacted]")
                        if isinstance(exc, seedance.SeedanceAPIError) else None,
                    usage=None, usage_known=False))
                cause_response = getattr(getattr(exc, "__cause__", None), "response", None)
                if cause_response is not None:
                    _save(run / "NATIVE_SUBMIT_ERROR_RESPONSE.json", dict(at=_now(),
                        http_status=getattr(cause_response, "status_code", status),
                        body=cause_response.text.replace(client.config.api_key, "[redacted]"),
                        headers_saved=False, credentials_saved=False))
                if rejected:
                    state.update(status="request_rejected", technical_status="failed")
                    _save(run / "state.json", state)
                    with core._lock(registry / ".registry.lock"):
                        _event(plan, "request_rejected", failure=True, http_status=status)
                raise
        finally:
            if own:
                client.close()
    return inspect(run)


def _metadata(path):
    command = ["ffprobe", "-v", "error", "-count_packets", "-show_entries",
        "format=duration,format_name,size:stream=index,codec_type,codec_name,width,height,nb_read_packets,duration",
        "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode:
        raise ValueError("ffprobe容器与包完整性核验失败")
    metadata = json.loads(result.stdout)
    video = [row for row in metadata.get("streams", []) if row.get("codec_type") == "video"]
    audio = [row for row in metadata.get("streams", []) if row.get("codec_type") == "audio"]
    if (len(video) != 1 or not audio or (video[0].get("width"), video[0].get("height")) != (720, 1280)
            or not 9 <= float(metadata["format"]["duration"]) <= 11
            or any(int(row.get("nb_read_packets", 0)) <= 0 for row in video + audio)):
        raise ValueError("输出须为720×1280、9–11秒且有完整原生音频包")
    return metadata


def query(run_dir=DEFAULT_RUN, *, client=None):
    """GET the recorded original ID; interrupted downloads can resume without POST."""
    run = Path(run_dir).resolve()
    with core._lock(run / ".execution.lock"):
        plan, payload = _verify(run)
        _claim(run, plan)
        state = core._read(run / "state.json")
        native = core._read(run / "NATIVE_SUBMIT_RESPONSE.json")
        task_id = native.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("没有可核验原生任务ID，只能停住对账")
        if state.get("task_id") is None and state.get("status") == "submit_outcome_unknown" and state.get("submissions_started") == 1:
            state.update(task_id=task_id, status="submitted", technical_status="running")
            _save(run / "state.json", state)
        if state.get("task_id") != task_id or state.get("submissions_started") != 1:
            raise ValueError("原始任务ID或派发次数不符")
        if (run / "receipt.json").exists():
            return inspect(run)
        own = client is None
        client = client or seedance.SeedanceClient(_config(require_key=True))
        try:
            _client_config(client.config)
            task = client.get_task(task_id)
            if task.get("id", task_id) != task_id:
                raise ValueError("GET返回其他任务ID")
            index = len(list(run.glob("NATIVE_QUERY_*.json"))) + 1
            _durable(run / f"NATIVE_QUERY_{index:03}.json", task)
            status = task.get("status")
            if status not in {"queued", "running", "succeeded", "failed", "cancelled", "expired"}:
                raise ValueError("未知原生任务状态，保留证据并停止")
            state.update(status=status)
            _save(run / "state.json", state)
            if status in {"failed", "cancelled", "expired"}:
                with core._lock(_paths()[0] / ".registry.lock"):
                    _event(plan, "terminal_failure:" + task_id, failure=True, task_id=task_id, status=status)
                state.update(technical_status="failed", content_status="not_available")
                _save(run / "state.json", state)
            if status != "succeeded":
                return inspect(run)
            video, tail = run / "S01.mp4", run / "S01.native-tail.jpg"
            if not video.exists():
                client.download_video(task, video)
            if not tail.exists():
                client.download_last_frame(task, tail)
            metadata, integrity = _metadata(video), last_frame_integrity(tail)
            core._ensure(run / "VIDEO_METADATA.json", metadata)
            core._ensure(run / "NATIVE_TAIL_INTEGRITY.json", integrity)
            receipt = dict(schema=VERSION, scope_id=SCOPE_ID, segment_id="S01", provider="ark_api",
                model=seedance.ARK_MINI_MODEL, task_id=task_id, plan=str(run / "PLAN.json"),
                plan_sha256=core._binding(run / "PLAN.json")["sha256"],
                request=payload, request_sha256=core._digest(payload), request_file_binding=plan["request"],
                source_bindings={Path(row["path"]).name: row for row in plan["source_files"]},
                source_binding=SOURCE_BINDING, text_status=plan["text_status"],
                video=core._binding(video), native_tail=core._binding(tail),
                video_path=str(video), video_sha256=core._binding(video)["sha256"],
                last_frame=str(tail), last_frame_sha256=core._binding(tail)["sha256"],
                native_tail_source="provider_returned_original_last_frame_url",
                metadata=core._binding(run / "VIDEO_METADATA.json"),
                tail_integrity=core._binding(run / "NATIVE_TAIL_INTEGRITY.json"),
                native_usage=task.get("usage"), cost=task.get("cost"), usage_known=task.get("usage") is not None,
                human_approved=False, content_inspection_performed=False, posthoc_frame_extraction=False,
                audio_or_asr_review_performed=False, continuation_authorized=False,
                publishing_authorized=False, automatic_retry=False, saved_at=_now())
            media_review_policy.mark_saved_candidate(receipt)
            _durable(run / "receipt.json", receipt)
            with core._lock(_paths()[0] / ".registry.lock"):
                _event(plan, "saved:" + task_id, task_id=task_id, receipt=core._binding(run / "receipt.json"))
            state.update(status=receipt["status"], technical_status="succeeded", content_status="awaiting_human_review")
            _save(run / "state.json", state)
        finally:
            if own:
                client.close()
    return inspect(run)
