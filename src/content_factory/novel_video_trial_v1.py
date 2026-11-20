"""One source-bound native Seedance trial, then explicit user media review."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from . import novel_adaptation_pipeline_v1 as core
from . import novel_agent_pipeline_v7 as runtime
from . import seedance_client as seedance
from . import seedance_models
from . import media_review_policy
from . import assistant_seedance_trial
from .assistant_seedance_trial import last_frame_integrity

VERSION = "novel_video_trial/v1"
REGISTRY = core.ROOT / "data/novel_video_trial_registry_v1"
SOURCE_BINDING = "35b2a809bf62b7b7021c3005193690cd09902eee38eea602d3cb0691588c9ca7"
DRAFT_BINDING = "1bdaf8b9308d43c385aab4b6cf2fe97afa4837627dff653c5ca7f3d88e0108be"
SEGMENT_ID = "S1-A"
AUTHORIZATION = {"user_statement": "先生成一段我先审核", "max_new_submissions": 1,
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


def compile_prompt(handoff):
    """Compile the precise approved opening; do not accept a free-form prompt."""
    director = handoff["director"]
    segment = director["segments"][0]
    selected = segment["performance"][0]
    if (segment["segment_id"] != "S1" or selected["actor_id"] != "周禾"
            or segment["present_characters"] != ["周禾", "周明"]
            or not isinstance(selected.get("dialogue"), str) or not selected["dialogue"].strip()):
        raise ValueError("当前S1-A固定分段方案与原生导演首段不一致")
    recipe = {"schema": "novel_video_segment_recipe/v1", "segment_id": SEGMENT_ID,
              "parent_segment_id": "S1", "parent_duration_seconds": segment["estimated_duration_seconds"],
              "performance_indices": [0], "world_framework": director["world_framework"],
              "location": segment["location"], "environment": segment["environment"],
              "start_state": segment["start_state"], "selected_performance": selected,
              "other_actor": {"actor_id": "周明", "action": "始终坐在木桌另一边，拇指挡住无帽红笔的笔尖，安静听女儿说完，不放笔，不说话"},
              "boundary": "只生成S1第一条表演及女儿握杆反应；下一条父亲台词、放笔、广播、取票均未发生",
              "duration_seconds": 15, "cast_approval": None, "reference_assets": []}
    prompt = "\n\n".join([
        "生成15秒、9:16竖屏、720p写实生活剧情片，中文普通话原生同期对白。一个连续时刻，表演自然，不加字幕、文字贴片、片头、背景音乐或旁白。仅两位成年人物，无其他说话人。",
        "世界框架（供人物关系和空间理解，里面标为后续的情节不在本段发生）：\n" + director["world_framework"],
        "本段地点：" + segment["location"] + "。本段环境：" + segment["environment"],
        "本段起态必须保持：\n" + json.dumps(segment["start_state"], ensure_ascii=False),
        "本次只拍S1-A（原S1的前半段），不把28秒全段压缩成15秒。女儿周禾26岁，站在桌边，右手握箱杆，箱子贴右腿；父亲周明约50岁，坐在桌子另一边，非制服日常衣服，外套搭椅背。父亲的拇指挡着无帽红笔笔尖，安静听；本段始终坐着，不放笔，不抢话。",
        "0—1秒：中近景建立父女隔桌的位置与女儿箱杆，女儿目光从录取通知移到父亲脸上，轻吸气，准备抢先开口。1—11秒：女儿带着紧绷的防备，连贯、日常语速完整说唯一一句对白，嘴型与声音对应；可在同一空间缓慢推进到女儿近景，父亲在对侧安静听。",
        "女儿周禾唯一对白，必须完整照说：\n“" + selected["dialogue"] + "”",
        "女儿原动作：" + selected["action"] + "。女儿表演：" + selected["expression"] + "。视线：" + selected["gaze"] + "。反应：" + selected["reaction"] + "。11—15秒：对白收住，她五指继续收紧箱杆，骨节泛白，喉咙里还压着没说完的话，留出能看清表情与手指的反应窗口，父亲仍坐着静听。",
        "段尾：女儿说完这句话并紧握箱杆，父亲尚未开口、尚未放笔；红笔仍由父亲拇指挡着笔尖。下一段才发生父亲的回应。本段禁止提前加入父亲台词、广播、船笛、取票或推票、起身、上船；纸票尚未出现，不能在桌上摆票。无母亲镜头、照片、回忆或其他人物。只有轻微江风和候船室环境底噪。人物服装、道具、坐站位置与视线连续。",
    ])
    return recipe, prompt + "\n"


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
            (core, runtime, seedance, seedance_models, media_review_policy, assistant_seedance_trial)] + [core._binding(__file__), core._binding(seedance_models.CATALOG)]


def prepare(run_dir, *, source_run):
    run = Path(run_dir).resolve()
    if run.exists() and any(run.iterdir()):
        raise ValueError("视频准备目录非空，不覆盖已有证据")
    handoff = _source(source_run)
    source_run = Path(source_run).resolve()
    recipe, prompt = compile_prompt(handoff)
    identity = {"source_binding": SOURCE_BINDING, "draft_binding": DRAFT_BINDING, "segment_id": SEGMENT_ID}
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
            core._write(story_counter, {"schema": VERSION, "source_binding": SOURCE_BINDING,
                                      "failure_limit": 10, "failures_used": 0, "failed_task_ids": []})
        counter = core._read(story_counter)
        if counter["source_binding"] != SOURCE_BINDING or counter["failure_limit"] != 10 or counter["failures_used"] >= 10:
            raise ValueError("同故事失败记录不符或已耗尽")
    (run / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    core._write(run / "RECIPE.json", recipe)
    payload = _payload(prompt, _config())
    core._write(run / "REQUEST.json", payload)
    core._write(run / "PLAN.json", {"schema": VERSION, "identity": identity, "created_at": _now(),
        "source_run": str(source_run), "source_files": [core._binding(source_run / name) for name in
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
    expected_identity = {"source_binding": SOURCE_BINDING, "draft_binding": DRAFT_BINDING, "segment_id": SEGMENT_ID}
    if plan["identity"] != expected_identity:
        raise ValueError("来源或分段身份变化")
    expected_registry = Path(REGISTRY).resolve()
    if (Path(plan["canonical_claim"]).resolve() != expected_registry / (core._digest(expected_identity) + ".json")
            or Path(plan["story_counter"]).resolve() != expected_registry / ("story_" + SOURCE_BINDING + ".json")):
        raise ValueError("永久提交或失败登记位置变化")
    for row in plan["source_files"] + plan["code_bindings"] + [plan["recipe"], plan["prompt"], plan["request"]]:
        core._verify_file(row)
    recipe, prompt = compile_prompt(_source(plan["source_run"]))
    if core._read(plan["recipe"]["path"]) != recipe or Path(plan["prompt"]["path"]).read_text(encoding="utf-8") != prompt:
        raise ValueError("prompt与已审核导演机械编译结果不一致")
    request = core._read(plan["request"]["path"])
    if request != _payload(prompt, _config()):
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
