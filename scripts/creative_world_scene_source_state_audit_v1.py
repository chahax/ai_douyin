"""Pure complete-source state/action audit request and native report contract.

Quoted source identity and report consistency are deterministic checks.
Resource/state/action/emotion interpretation belongs to the native reviewer;
this module does not infer semantic conflicts from keywords or count text.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from scripts.creative_call_evidence_v1 import digest
from scripts import creative_m31_flash_role_clients_v1 as clients
from src.content_factory import creative_goal_context_workflow_v28 as workflow

VERSION = "creative_world_scene_source_state_audit/v1"
CHECKS = ("resource_quantity", "prop_custody", "spatial_presence", "action_purpose", "emotional_causality")
ASPECT_CHECK = {"quantity": "resource_quantity", "holder": "prop_custody", "location": "spatial_presence",
    "presence": "spatial_presence", "action_function": "action_purpose", "emotional_cause": "emotional_causality"}
STATUSES = ("pass", "fail", "unknown")
RULE = (
    "审查完整原生规划与原生开场的跨拍状态和动作作用，不写新剧本，不修原稿，不查看或听取视频。"
    "authority_inputs是原inputs的既有阶段权威投影，其中已确认来源/用户要求仍是权威；goal是待审规划，setup是本次明确首态。"
    "逐拍按原ID和原序覆盖，不遗漏沉默者；每拍source_evidence至少引用该拍自身原文字段。"
    "观察记录只记录有来源的相关信息，没有状态操作时允许observations为空。"
    "reading=intent表示打算、要求或尚未完成的承诺，occurred仅表示源剧情内部明确写出发生，"
    "initial表示原生setup首态，unknown表示源读法真正未决；这些都不证明已经生成实拍视频。"
    "明确开放的未来结果本身不等于读不懂，不应仅因尚未兑现就报unknown。"
    "资源数量须对照具体对象、时间和计数口径；不能把愿望或重复描述再计作一次完成。"
    "静态owner/岗位/资产绑定不等于当前holder或location；首态以setup为据，"
    "后续持有/位置变化须有实际源动作，不能从邀请、台词承诺或动作意图推成完成。"
    "核在场者、进出和空间可达；动作是否带来新信息、策略、情绪或必要连续，"
    "重复动作可作有意义的持续工作或动机，不能只按重复次数判错。"
    "静默、神情反应、安静保持和持续原动作都可以有效，不强迫每个听者新增物件操作。"
    "情绪因果看刺激是否先可知、反应和策略是否接得住，以及结尾选择与物件去向是否一致。"
    "不要预设有错；五类checks均判断全片。fail须有明确源矛盾或无效动作作用；"
    "unknown保留不确定性，不能写成已证失败或通过。"
    "所有source_evidence/evidence使用source(goal/setup/inputs)+JSONpointer path+非空逐字短quote；"
    "source=goal对应native_goal_document，setup对应native_opening_setup_document，inputs对应实际authority_inputs；"
    "path从所选对象根开始，不含外层包装键，不可引用已从出站投影省略的旧剧情。"
    "quote最长160字符，必须可从指定原文读回，不只引用ID来代替事实。"
    "跨拍issue须引用每个相关拍的原文；initial_to_beat须同时引用setup和相应拍。"
    "reading=unknown的观察必须由对应check的unknown issue引用，不能隐藏未决读法。"
    "checks.issue_ids恰好列该check的全部issues；有unknown则该check=unknown，否则有fail则fail，否则pass。"
    "overall_status同样unknown优先、再fail、否则pass；保留所有已知失败，不能用一个未知抹掉其证据。"
    "这是一次必要的规划诊断，不是创作质量批准、正文通过、导演通过或视频批准。提交指定工具的完整原生报告。"
)


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _array(item, minimum=0, **extra):
    return {"type": "array", "items": item, "minItems": minimum, **extra}


def _text(maximum=800): return {"type": "string", "minLength": 1, "maxLength": maximum, "pattern": r"\S"}


def _pointer(parts):
    return "/" + "/".join(str(x).replace("~", "~0").replace("/", "~1") for x in parts) if parts else ""


def _resolve(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/"): raise ValueError("absolute JSON pointer required")
    value = document
    for token in pointer[1:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            if not key.isdigit() or str(int(key)) != key: raise ValueError("canonical array pointer index required")
            value = value[int(key)]
        elif type(value) is dict: value = value[key]
        else: raise ValueError("source pointer does not resolve")
    return value


def _string_leaves(value):
    if isinstance(value, str): yield value
    elif type(value) is dict:
        for child in value.values(): yield from _string_leaves(child)
    elif type(value) is list:
        for child in value: yield from _string_leaves(child)


def _payload(inputs, goal, setup):
    if any(key in inputs for key in ("previous_complete_document", "revision_diagnostics")):
        raise ValueError("source audit authority cannot contain a failed-script template")
    authority = workflow._base(inputs, goal)
    workflow.validate_opening_setup_document(setup, goal)
    reference = inputs.get("reference_fulltext")
    if not isinstance(reference, str) or not reference: raise ValueError("complete original R01 required")
    value = {"authority_inputs": deepcopy(authority["payload"]), "native_goal_document": deepcopy(goal),
        "native_opening_setup_document": deepcopy(setup)}
    if sum(text.count(reference) for text in _string_leaves(value)) != 1:
        raise ValueError("original complete R01 must occur exactly once")
    return value, authority["manifest"]


def _schema(goal, setup, context):
    beats = [row["id"] for row in goal["whole_plan"]["beats"]]
    entities = list(dict.fromkeys(row["id"] for group in ("characters", "scenes", "props") for row in goal["whole_plan"][group]))
    proof = _object({"source": {"enum": ["goal", "setup", "inputs"]}, "path": _text(300), "quote": _text(160)})
    evidence = _array(proof, 1, uniqueItems=True)
    observation = _object({"id": {"type": "string", "pattern": r"^O[0-9]{3,}$", "description": "Globally unique observation ID across all beat rows."},
        "entity_id": {"enum": entities}, "aspect": {"enum": list(ASPECT_CHECK), "description": "Check routing: " + "; ".join(k+"->"+v for k,v in ASPECT_CHECK.items())},
        "reading": {"enum": ["intent", "occurred", "initial", "unknown"], "description": "initial requires original setup evidence; unknown requires a linked unknown issue."},
        "value": _text(400), "evidence": deepcopy(evidence)})
    beat = _object({"beat_id": {"enum": beats}, "coverage_summary": _text(500),
        "source_evidence": deepcopy(evidence), "observations": _array(observation)})
    issue = _object({"id": {"type": "string", "pattern": r"^I[0-9]{3,}$", "description": "Globally unique issue ID."}, "check_id": {"enum": list(CHECKS)},
        "scope": {"enum": ["within_beat", "cross_beat", "initial_to_beat"], "description": "cross_beat needs at least two distinct beat_ids; within_beat and initial_to_beat each need exactly one."},
        "beat_ids": _array({"enum": beats}, 1, uniqueItems=True),
        "observation_ids": {**_array({"type": "string", "pattern": r"^O[0-9]{3,}$"}, uniqueItems=True),
            "description": "References existing observation IDs within this issue's beat_ids, with aspect routed to this check_id."},
        "status": {"enum": ["fail", "unknown"]}, "summary": _text(), "evidence": deepcopy(evidence),
        "revision_target": {"enum": ["goal", "setup", "both", "clarify_source"]}, "required_revision": _text()})
    check = _object({"status": {"enum": list(STATUSES)}, "reason": _text(),
        "issue_ids": _array({"type": "string", "pattern": r"^I[0-9]{3,}$"}, uniqueItems=True)})
    return _object({"schema": {"const": VERSION}, "native_goal_sha256": {"const": digest(goal)},
        "native_setup_sha256": {"const": digest(setup)}, "context_sha256": {"const": context},
        "beat_reviews": _array(beat, len(beats), maxItems=len(beats)), "issues": _array(issue),
        "checks": _object({name: deepcopy(check) for name in CHECKS}), "overall_status": {"enum": list(STATUSES)}})


def prepare(inputs, profile, goal, setup):
    """Pure actual request, with all original documents once and no answers."""
    payload, authority_manifest = _payload(inputs, goal, setup)
    role = profile.get("director", {})
    parameters = deepcopy(role.get("parameters", {}))
    cap = profile.get("stage_parameters", {}).get("goal_audit", {}).get("max_completion_tokens", parameters.get("max_completion_tokens"))
    if (role.get("model") != clients.REVIEW_MODEL or parameters.get("temperature") != .4
            or parameters.get("thinking") != "disabled" or type(cap) is not int or not 0 < cap <= 32000):
        raise ValueError("current DeepSeek reviewer profile and bounded stage cap required")
    parameters["max_completion_tokens"] = cap
    context = digest(payload); schema = _schema(goal, setup, context)
    Draft202012Validator.check_schema(schema)
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    request = {"role": "director", "stage": "goal_audit", "model": role["model"],
        "parameters": parameters, "messages": [{"role": "system", "content": RULE}, {"role": "user", "content": content}],
        "structured_schema": schema, "input_provenance": {"source_state_audit_version": VERSION,
            "context_sha256": context, "original_inputs_sha256": digest(inputs),
            "native_goal_sha256": digest(goal), "native_setup_sha256": digest(setup)}}
    clients.expected_wire_request(request)
    return {"request": request, "request_sha256": digest(request), "context_sha256": context,
        "views": {"inputs": deepcopy(inputs), "authority_inputs": deepcopy(payload["authority_inputs"]),
            "profile": deepcopy(profile), "goal": deepcopy(goal), "setup": deepcopy(setup)},
        "manifest": {"schema": VERSION + "/manifest", "context_sha256": context,
            "original_inputs_sha256": digest(inputs), "native_goal_sha256": digest(goal), "native_setup_sha256": digest(setup),
            "authority_inputs_sha256": digest(payload["authority_inputs"]),
            "authority_stage_projection_manifest": deepcopy(authority_manifest),
            "prior_full_script_omitted_from_request": True,
            "raw_inputs_retained_in_views_not_sent_as_authority": True,
            "payload_characters": len(content), "payload_utf8_bytes": len(content.encode("utf-8")),
            "schema_characters": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))),
            "R01_occurrences": 1, "manual_expected_findings_in_request": False,
            "program_proves_semantic_state": False, "provider_calls": 0}}


def validate(native, prepared):
    """Validate native quotations, coverage and explicit report consistency."""
    views = prepared["views"]
    expected = prepare(views["inputs"], views["profile"], views["goal"], views["setup"])
    if prepared != expected: raise ValueError("actual prepared source audit request or bindings changed")
    goal, setup, inputs = views["goal"], views["setup"], views["inputs"]
    documents = {"goal": goal, "setup": setup, "inputs": views["authority_inputs"]}
    findings = []
    def add(code, path, reason):
        row = {"code": code, "path": path, "reason": reason}
        if row not in findings: findings.append(row)
    for error in Draft202012Validator(prepared["request"]["structured_schema"]).iter_errors(native):
        add("NATIVE_SCHEMA_INVALID", _pointer(error.absolute_path) or "/", error.message)
    if findings:
        return {"valid": False, "accepted": False, "status": "source_state_audit_contract_rejected",
            "findings": findings, "uncertainties": [], "native_report_sha256": digest(native), "native_report_modified": False}
    beat_ids = [row["id"] for row in goal["whole_plan"]["beats"]]
    observed = [row["beat_id"] for row in native["beat_reviews"]]
    if observed != beat_ids: add("BEAT_COVERAGE", "/beat_reviews", "all native beat IDs must occur once in exact source order")
    beat_index = {bid: i for i,bid in enumerate(beat_ids)}
    def quoted(proofs, path):
        for index, proof in enumerate(proofs):
            try:
                original = _resolve(documents[proof["source"]], proof["path"])
                if not isinstance(original, str) or not proof["quote"].strip() or proof["quote"] not in original:
                    raise ValueError("quote is not a nonempty exact source substring")
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                add("SOURCE_QUOTE_INVALID", f"{path}/{index}", str(exc))
    def covers_beat(proofs, bid):
        prefix = f"/whole_plan/beats/{beat_index[bid]}/"
        return any(proof["source"] == "goal" and proof["path"].startswith(prefix) for proof in proofs)
    observations = {}
    for index, row in enumerate(native["beat_reviews"]):
        quoted(row["source_evidence"], f"/beat_reviews/{index}/source_evidence")
        if not covers_beat(row["source_evidence"], row["beat_id"]):
            add("BEAT_LOCAL_EVIDENCE_MISSING", f"/beat_reviews/{index}/source_evidence", "coverage must cite this original beat")
        for oi, observation in enumerate(row["observations"]):
            path = f"/beat_reviews/{index}/observations/{oi}"
            if observation["id"] in observations: add("OBSERVATION_ID_DUPLICATE", path+"/id", "observation IDs must be globally unique")
            observations[observation["id"]] = (observation, row["beat_id"], path)
            quoted(observation["evidence"], path+"/evidence")
            if observation["reading"] == "initial" and not any(p["source"] == "setup" for p in observation["evidence"]):
                add("INITIAL_SETUP_EVIDENCE_MISSING", path+"/evidence", "initial observations require the original native setup")
    issues = {}
    for index, issue in enumerate(native["issues"]):
        path = f"/issues/{index}"
        if issue["id"] in issues: add("ISSUE_ID_DUPLICATE", path+"/id", "issue IDs must be unique")
        issues[issue["id"]] = issue
        quoted(issue["evidence"], path+"/evidence")
        if issue["scope"] == "cross_beat" and len(issue["beat_ids"]) < 2:
            add("CROSS_BEAT_COVERAGE", path+"/beat_ids", "cross-beat issues need at least two distinct original beats")
        if issue["scope"] != "cross_beat" and len(issue["beat_ids"]) != 1:
            add("ISSUE_SCOPE_COVERAGE", path+"/beat_ids", "within/initial issues identify exactly one beat")
        for bid in issue["beat_ids"]:
            if not covers_beat(issue["evidence"], bid): add("ISSUE_BEAT_EVIDENCE_MISSING", path+"/evidence", "issue needs original text from beat "+bid)
        if issue["scope"] == "initial_to_beat" and not any(p["source"] == "setup" for p in issue["evidence"]):
            add("ISSUE_SETUP_EVIDENCE_MISSING", path+"/evidence", "initial-to-beat issue needs original setup evidence")
        for oid in issue["observation_ids"]:
            if oid not in observations: add("ISSUE_OBSERVATION_UNKNOWN", path+"/observation_ids", "unknown observation "+oid)
            else:
                observation, bid, _ = observations[oid]
                if bid not in issue["beat_ids"] or ASPECT_CHECK[observation["aspect"]] != issue["check_id"]:
                    add("ISSUE_OBSERVATION_BINDING", path+"/observation_ids", "observation beat/aspect differs from issue")
    def status_for(rows):
        return "unknown" if any(row["status"] == "unknown" for row in rows) else "fail" if rows else "pass"
    for name, check in native["checks"].items():
        expected_issues = [row for row in native["issues"] if row["check_id"] == name]
        if set(check["issue_ids"]) != {row["id"] for row in expected_issues}:
            add("CHECK_ISSUE_COVERAGE", "/checks/"+name+"/issue_ids", "check must cite exactly all its original issues")
        if check["status"] != status_for(expected_issues):
            add("CHECK_STATUS_CONFLICT", "/checks/"+name+"/status", "status must retain fail/unknown issues with unknown priority")
    for oid,(observation,bid,path) in observations.items():
        if observation["reading"] == "unknown" and not any(oid in row["observation_ids"] and row["status"] == "unknown" for row in native["issues"]):
            add("UNKNOWN_READING_HIDDEN", path+"/reading", "unresolved observation must remain an unknown issue")
    expected_status = "unknown" if any(c["status"] == "unknown" for c in native["checks"].values()) else "fail" if any(c["status"] == "fail" for c in native["checks"].values()) else "pass"
    if native["overall_status"] != expected_status:
        add("OVERALL_STATUS_CONFLICT", "/overall_status", "overall status must follow all five checks, unknown first")
    valid = not findings
    return {"schema": VERSION + "/decision", "valid": valid,
        "accepted": valid and expected_status == "pass", "status": "source_state_"+expected_status if valid else "source_state_audit_contract_rejected",
        "native_semantic_status": native["overall_status"],
        "findings": deepcopy(findings if not valid else [row for row in native["issues"] if row["status"] == "fail"]),
        "contract_findings": findings,
        "uncertainties": deepcopy([row for row in native["issues"] if row["status"] == "unknown"]),
        "native_report_sha256": digest(native), "context_sha256": prepared["context_sha256"],
        "native_goal_sha256": digest(goal), "native_setup_sha256": digest(setup),
        "native_report_modified": False, "program_proves_semantic_state": False,
        "text_ready_for_director": False, "creative_quality_passed": False, "provider_calls": 0}
