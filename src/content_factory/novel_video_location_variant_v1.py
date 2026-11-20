"""One explicitly authorized location-only variant after a known failed parent task."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

from . import novel_adaptation_pipeline_v1 as core
from . import novel_agent_pipeline_v7 as runtime
from . import novel_video_trial_v1 as parent_trial
from . import seedance_client as seedance
from . import seedance_models
from . import media_review_policy
from . import assistant_seedance_trial
from .assistant_seedance_trial import last_frame_integrity

VERSION = "novel_video_location_variant/v1"
VARIANT_ID = "20261018_S1A_changjiang_to_qinglanhe_once"
PARENT_RUN = core.ROOT / "data/video_generation/novel_ferry_first_trial_20261018/S1A"
PARENT_TASK_ID = "cgt-20261018024437-nlsvb"
OLD_LOCATION = "长江中下游一带"
NEW_LOCATION = "青岚河中下游一带"
REGISTRY = core.ROOT / "data/novel_video_trial_registry_v1"
SOURCE_BINDING = "35b2a809bf62b7b7021c3005193690cd09902eee38eea602d3cb0691588c9ca7"
DRAFT_BINDING = "1bdaf8b9308d43c385aab4b6cf2fe97afa4837627dff653c5ca7f3d88e0108be"
SEGMENT_ID = "S1-A"
AUTHORIZATION = {"user_statement": "地名换下试试“长江”换下看下可以随便取一个意思到了就行",
                 "variant_id": VARIANT_ID, "location_only_adaptation": True, "max_new_submissions": 1,
                 "automatic_retry": False, "continuation_authorized": False,
                 "publishing_authorized": False, "human_review_required": True}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _durable(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _source(source_run):
    run = Path(source_run).resolve()
    view = runtime.inspect(run)
    if view["status"] != "text_ready_for_production" or view["blockers"]:
        raise ValueError("完整小说文本、同稿审查和导演原生证据尚未通过完整核验")
    handoff = core._read(run / "PRODUCTION_HANDOFF.json")
    header = handoff["header"]
    if header["source_binding"] != SOURCE_BINDING or header["draft_binding"] != DRAFT_BINDING:
        raise ValueError("本轮一次视频授权只覆盖已验收的渡口剧本")
    return handoff


def _identity():
    return {"source_binding": SOURCE_BINDING, "draft_binding": DRAFT_BINDING,
            "segment_id": SEGMENT_ID, "variant_id": VARIANT_ID}


def _parent():
    """Verify original source/code/claim and the fixed known terminal failure."""
    run = Path(PARENT_RUN).resolve()
    plan, request = parent_trial._verify(run)
    if Path(plan["story_counter"]).resolve() != Path(REGISTRY).resolve() / ("story_" + SOURCE_BINDING + ".json"):
        raise ValueError("父任务与变体必须沿用同故事失败登记")
    state = core._read(run / "state.json")
    if (state.get("status") != "failed" or state.get("task_id") != PARENT_TASK_ID
            or state.get("submissions_started") != 1):
        raise ValueError("父任务不是已核验的固定终态failed；禁止新派发")
    claim = core._read(plan["canonical_claim"])
    local = core._read(run / "SUBMISSION_CLAIM.json")
    if (claim != local or claim.get("run_dir") != str(run) or claim.get("identity") != plan["identity"]
            or claim.get("max_submissions") != 1
            or Path(claim["request"]["path"]).resolve() != run / "REQUEST.json"
            or Path(claim["plan"]["path"]).resolve() != run / "PLAN.json"):
        raise ValueError("父原永久claim或请求身份不符")
    core._verify_file(claim["request"])
    core._verify_file(claim["plan"])
    native = core._read(run / "NATIVE_SUBMIT_RESPONSE.json")
    queries = sorted(run.glob("NATIVE_QUERY_*.json"))
    if not queries:
        raise ValueError("父任务缺原生终态查询")
    terminal = core._read(queries[-1])
    if (native.get("id") != PARENT_TASK_ID or terminal.get("id") != PARENT_TASK_ID
            or terminal.get("status") != "failed"):
        raise ValueError("父原生任务ID或终态不符")
    counter = core._read(plan["story_counter"])
    if (PARENT_TASK_ID not in counter.get("failed_task_ids", [])
            or not isinstance(counter.get("failures_used"), int) or counter["failures_used"] < 1):
        raise ValueError("父失败未进入同故事累计，禁止重置计数")
    paths = [run / name for name in ("PLAN.json", "REQUEST.json", "PROMPT.txt", "RECIPE.json",
             "state.json", "SUBMISSION_CLAIM.json", "NATIVE_SUBMIT_RESPONSE.json")]
    paths += [Path(plan["canonical_claim"]), queries[-1]]
    return plan, request, [core._binding(path) for path in paths]


def compile_prompt(handoff):
    """Preserve parent native text verbatim except one authorized location phrase."""
    old_recipe, old_prompt = parent_trial.compile_prompt(handoff)
    if old_prompt.count(OLD_LOCATION) != 1 or NEW_LOCATION in old_prompt:
        raise ValueError("原提示词地点必须精确命中一次，禁止额外替换")
    prompt = old_prompt.replace(OLD_LOCATION, NEW_LOCATION, 1)
    recipe = deepcopy(old_recipe)
    recipe.update(schema="novel_video_location_variant_recipe/v1", variant_id=VARIANT_ID,
        parent_recipe=old_recipe, source_world_framework=old_recipe["world_framework"],
        display_world_framework=old_recipe["world_framework"].replace(OLD_LOCATION, NEW_LOCATION, 1),
        location_variant={"old": OLD_LOCATION, "new": NEW_LOCATION, "replacement_count": 1,
                          "user_approved_location_only_adaptation": True,
                          "source_text_modified": False})
    return recipe, prompt


def _expected_request(parent_request):
    request = deepcopy(parent_request)
    content = request.get("content")
    if (not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "text"
            or not isinstance(content[0].get("text"), str)
            or content[0]["text"].count(OLD_LOCATION) != 1 or NEW_LOCATION in content[0]["text"]):
        raise ValueError("父原请求必须是单条文本且地点精确命中一次")
    content[0]["text"] = content[0]["text"].replace(OLD_LOCATION, NEW_LOCATION, 1)
    return request


def _config(*, require_key=False):
    config = seedance.SeedanceConfig.from_env("ark_api", require_key=require_key)
    if (config.provider != "ark_api" or config.base_url != seedance.ARK_BASE_URL
            or config.model != seedance.ARK_MINI_MODEL):
        raise ValueError("本次只使用已核实的官方Seedance 2.0 mini协议")
    return config


def _payload(prompt, config):
    with seedance.SeedanceClient(config, record_calls=False) as client:
        return client.build_task_payload(prompt, duration=15, ratio="9:16", resolution="720p",
                                         generate_audio=True, return_last_frame=True,
                                         references=[], task_type="text")


def _code_bindings():
    return [core._binding(module.__file__) for module in
            (core, runtime, parent_trial, seedance, seedance_models, media_review_policy, assistant_seedance_trial)] + [core._binding(__file__), core._binding(seedance_models.CATALOG)]


def prepare(run_dir, *, source_run):
    run = Path(run_dir).resolve()
    if run.exists() and any(run.iterdir()):
        raise ValueError("视频准备目录非空，不覆盖已有证据")
    parent_plan, parent_request, parent_files = _parent()
    source_run = Path(source_run).resolve()
    if source_run != Path(parent_plan["source_run"]).resolve():
        raise ValueError("变体必须沿用父任务冻结来源")
    handoff = _source(source_run)
    recipe, prompt = compile_prompt(handoff)
    identity = _identity()
    key = core._digest(identity)
    registry = Path(REGISTRY).resolve()
    registry.mkdir(parents=True, exist_ok=True)
    run.mkdir(parents=True, exist_ok=True)
    claim = registry / (key + ".json")
    story_counter = registry / ("story_" + SOURCE_BINDING + ".json")
    with core._lock(registry / ".registry.lock"):
        if claim.exists():
            raise ValueError("同源同稿同段已有永久派发claim，只能查询原ID，不得改目录重新提交")
        if not story_counter.exists():
            raise ValueError("同故事原失败登记缺失，禁止创建新计数")
        counter = core._read(story_counter)
        if counter["source_binding"] != SOURCE_BINDING or counter["failure_limit"] != 10 or counter["failures_used"] >= 10:
            raise ValueError("同故事失败记录不符或已耗尽")
    (run / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    core._write(run / "RECIPE.json", recipe)
    payload = _payload(prompt, _config())
    if payload != _expected_request(parent_request):
        raise ValueError("地点变体只能修改原请求的一处地名，其余参数必须相同")
    core._write(run / "REQUEST.json", payload)
    core._write(run / "PLAN.json", {"schema": VERSION, "identity": identity, "created_at": _now(),
        "parent_run": str(Path(PARENT_RUN).resolve()), "parent_task_id": PARENT_TASK_ID,
        "parent_files": parent_files, "source_run": str(source_run), "source_files": [core._binding(source_run / name) for name in
                ("BINDING.json", "PRODUCTION_HANDOFF.json", "SCREENPLAY.md", "OUTPUT_MANIFEST.json")],
        "recipe": core._binding(run / "RECIPE.json"), "prompt": core._binding(run / "PROMPT.txt"),
        "request": core._binding(run / "REQUEST.json"), "authorization": AUTHORIZATION,
        "canonical_claim": str(claim), "story_counter": str(story_counter),
        "code_bindings": _code_bindings(), "provider": "ark_api", "model": seedance.ARK_MINI_MODEL,
        "asset_mode": "text_only_no_cast_approval", "media_review": "user_manual_only"})
    _save(run / "state.json", {"schema": VERSION, "status": "prepared_not_submitted", "task_id": None,
                               "submissions_started": 0, "content_status": "not_generated"})
    return inspect(run)


def _verify(run):
    plan = core._read(run / "PLAN.json")
    if plan["schema"] != VERSION or plan["authorization"] != AUTHORIZATION:
        raise ValueError("本次单段人工审核授权被修改")
    expected_identity = _identity()
    parent_plan, parent_request, parent_files = _parent()
    if (plan.get("parent_run") != str(Path(PARENT_RUN).resolve()) or plan.get("parent_task_id") != PARENT_TASK_ID
            or plan.get("parent_files") != parent_files
            or Path(plan["source_run"]).resolve() != Path(parent_plan["source_run"]).resolve()):
        raise ValueError("父失败/原请求/来源冻结绑定变化")
    if plan["identity"] != expected_identity:
        raise ValueError("来源或分段身份变化")
    expected_registry = Path(REGISTRY).resolve()
    if (Path(plan["canonical_claim"]).resolve() != expected_registry / (core._digest(expected_identity) + ".json")
            or Path(plan["story_counter"]).resolve() != expected_registry / ("story_" + SOURCE_BINDING + ".json")):
        raise ValueError("永久提交或失败登记位置变化")
    for row in plan["parent_files"] + plan["source_files"] + plan["code_bindings"] + [plan["recipe"], plan["prompt"], plan["request"]]:
        core._verify_file(row)
    recipe, prompt = compile_prompt(_source(plan["source_run"]))
    if core._read(plan["recipe"]["path"]) != recipe or Path(plan["prompt"]["path"]).read_text(encoding="utf-8") != prompt:
        raise ValueError("prompt与已审核导演机械编译结果不一致")
    request = core._read(plan["request"]["path"])
    if request != _payload(prompt, _config()) or request != _expected_request(parent_request):
        raise ValueError("请求与冻结单段参数不一致")
    counter = core._read(plan["story_counter"])
    if counter["source_binding"] != SOURCE_BINDING or counter["failure_limit"] != 10:
        raise ValueError("故事失败登记身份变化")
    return plan, request


def inspect(run_dir):
    run = Path(run_dir).resolve()
    if not (run / "PLAN.json").is_file():
        return {"schema": VERSION, "status": "unprepared", "run_dir": str(run)}
    try:
        plan, _ = _verify(run)
        state = core._read(run / "state.json")
        if (run / "receipt.json").exists():
            receipt = core._read(run / "receipt.json")
            for key in ("video", "native_tail"):
                core._verify_file(receipt[key])
            if receipt["content_status"] != "awaiting_human_review":
                raise ValueError("本试运行尚未获得人工内容批准")
        claim = Path(plan["canonical_claim"])
        return {"schema": VERSION, "run_dir": str(run), **state, "claim_exists": claim.exists(),
                "human_approved": False, "continuation_authorized": False,
                "source_binding": SOURCE_BINDING, "draft_binding": DRAFT_BINDING,
                "failure_counter": core._read(plan["story_counter"])}
    except Exception as exc:
        return {"schema": VERSION, "run_dir": str(run), "status": "evidence_invalid", "error": str(exc)}


def submit(run_dir, *, client=None):
    run = Path(run_dir).resolve()
    with core._lock(run / ".execution.lock"):
        plan, payload = _verify(run)
        state = core._read(run / "state.json")
        if state["submissions_started"] or state["task_id"] or (run / "SUBMISSION_CLAIM.json").exists():
            raise ValueError("仅允许一次提交；只可query原ID")
        registry = Path(REGISTRY).resolve()
        with core._lock(registry / ".registry.lock"):
            if Path(plan["canonical_claim"]).exists():
                raise ValueError("跨目录单次派发claim已存在；不可再POST")
            if core._read(plan["story_counter"])["failures_used"] >= 10:
                raise ValueError("同故事失败上限已达")
            claim = {"schema": VERSION, "run_dir": str(run), "identity": plan["identity"],
                     "request": core._binding(run / "REQUEST.json"), "plan": core._binding(run / "PLAN.json"),
                     "created_at": _now(), "max_submissions": 1}
            _durable(plan["canonical_claim"], claim)
            _durable(run / "SUBMISSION_CLAIM.json", claim)
        state.update(status="submit_outcome_unknown", submissions_started=1, content_status="not_generated")
        _save(run / "state.json", state)
        own = client is None
        client = client or seedance.SeedanceClient(_config(require_key=True))
        try:
            if client.config.provider != "ark_api" or client.config.model != seedance.ARK_MINI_MODEL or client.config.base_url != seedance.ARK_BASE_URL:
                raise ValueError("实际客户端协议与冻结不符")
            response = client.create_task(payload)
            _durable(run / "NATIVE_SUBMIT_RESPONSE.json", response)
            if not isinstance(response.get("id"), str) or not response["id"]:
                raise ValueError("原生提交未返回任务ID；停止，禁止重派")
            state.update(status="submitted", task_id=response["id"])
            _save(run / "state.json", state)
        except Exception as exc:
            code = getattr(exc, "status_code", None)
            core._write(run / "SUBMIT_ERROR.json", {"error": str(exc), "at": _now(), "automatic_retry": False,
                                                    "http_status": code, "error_code": getattr(exc, "error_code", None)})
            if isinstance(code, int) and 400 <= code < 500:
                state.update(status="request_rejected", technical_status="failed")
                _save(run / "state.json", state)
                _failed(plan, "rejected:" + core._binding(run / "SUBMISSION_CLAIM.json")["sha256"])
            raise
        finally:
            if own:
                client.close()
    return inspect(run)


def _metadata(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
        "format=duration,format_name,size:stream=index,codec_type,codec_name,width,height,nb_read_packets,duration",
        "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode:
        raise ValueError("ffprobe容器元数据/包完整性核验失败")
    metadata = json.loads(result.stdout)
    video = [r for r in metadata.get("streams", []) if r.get("codec_type") == "video"]
    audio = [r for r in metadata.get("streams", []) if r.get("codec_type") == "audio"]
    if (len(video) != 1 or not audio or (video[0].get("width"), video[0].get("height")) != (720, 1280)
            or not 14 <= float(metadata["format"]["duration"]) <= 16
            or any(int(r.get("nb_read_packets", 0)) <= 0 for r in video + audio)):
        raise ValueError("输出须为720×1280、约15秒且含视频和原生音频流完整包")
    return metadata


def _failed(plan, task_id):
    with core._lock(Path(REGISTRY).resolve() / ".registry.lock"):
        counter = core._read(plan["story_counter"])
        if task_id not in counter["failed_task_ids"]:
            counter["failed_task_ids"].append(task_id)
            counter["failures_used"] += 1
            _save(plan["story_counter"], counter)


def query(run_dir, *, client=None):
    """One GET of the original ID; repeated GET/download never creates a task."""
    run = Path(run_dir).resolve()
    with core._lock(run / ".execution.lock"):
        plan, _ = _verify(run)
        state = core._read(run / "state.json")
        claim = core._read(plan["canonical_claim"])
        local = core._read(run / "SUBMISSION_CLAIM.json")
        if claim != local or claim["run_dir"] != str(run):
            raise ValueError("原派发claim不匹配")
        core._verify_file(claim["request"])
        core._verify_file(claim["plan"])
        response = core._read(run / "NATIVE_SUBMIT_RESPONSE.json")
        task_id = response.get("id")
        if (isinstance(task_id, str) and task_id and state.get("task_id") is None
                and state.get("status") == "submit_outcome_unknown" and state.get("submissions_started") == 1):
            state.update(task_id=task_id, status="submitted")
            _save(run / "state.json", state)
        if not task_id or task_id != state.get("task_id") or state["submissions_started"] != 1:
            raise ValueError("未取得可核验原始任务ID；不能猜测或重派")
        if (run / "receipt.json").exists():
            return inspect(run)
        own = client is None
        client = client or seedance.SeedanceClient(_config(require_key=True))
        try:
            if client.config.provider != "ark_api" or client.config.model != seedance.ARK_MINI_MODEL or client.config.base_url != seedance.ARK_BASE_URL:
                raise ValueError("实际查询客户端协议与冻结不符")
            task = client.get_task(task_id)
            if task.get("id", task_id) != task_id:
                raise ValueError("GET返回其他任务ID")
            index = len(list(run.glob("NATIVE_QUERY_*.json"))) + 1
            core._write(run / f"NATIVE_QUERY_{index:03}.json", task)
            state.update(status=task["status"])
            _save(run / "state.json", state)
            if task["status"] in {"failed", "cancelled", "expired"}:
                _failed(plan, task_id)
            if task["status"] != "succeeded":
                return inspect(run)
            video = run / "S1-A.mp4"
            tail = run / "S1-A.native-tail.jpg"
            if not video.exists():
                client.download_video(task, video)
            if not tail.exists():
                client.download_last_frame(task, tail)
            metadata, integrity = _metadata(video), last_frame_integrity(tail)
            core._ensure(run / "VIDEO_METADATA.json", metadata)
            core._ensure(run / "NATIVE_TAIL_INTEGRITY.json", integrity)
            actual_request = core._read(run / "REQUEST.json")
            receipt = {"schema": VERSION, "segment_id": SEGMENT_ID, "provider": "ark_api", "model": seedance.ARK_MINI_MODEL,
                       "task_id": task_id, "plan_sha256": core._binding(run / "PLAN.json")["sha256"],
                       "plan": str(run / "PLAN.json"), "plan_snapshot": plan,
                       "request": actual_request, "request_sha256": core._digest(actual_request),
                       "request_file_binding": core._binding(run / "REQUEST.json"), "source_identity": plan["identity"],
                       "source_bindings": {Path(row["path"]).name: row for row in plan["source_files"]},
                       "video": core._binding(video), "native_tail": core._binding(tail),
                       "video_path": str(video), "video_sha256": core._binding(video)["sha256"],
                       "last_frame": str(tail), "last_frame_sha256": core._binding(tail)["sha256"],
                       "native_tail_source": "provider_returned_original_last_frame_url",
                       "metadata": core._binding(run / "VIDEO_METADATA.json"), "human_approved": False,
                       "content_inspection_performed": False, "posthoc_frame_extraction": False,
                       "audio_or_asr_review_performed": False, "continuation_authorized": False,
                       "publishing_authorized": False, "saved_at": _now()}
            media_review_policy.mark_saved_candidate(receipt)
            core._write(run / "receipt.json", receipt)
            state.update(status=receipt["status"], technical_status="succeeded", content_status="awaiting_human_review")
            _save(run / "state.json", state)
        finally:
            if own:
                client.close()
    return inspect(run)
