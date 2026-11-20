"""Pure typed source-state extraction audit; no inference from language keywords.

The reviewer owns extraction and semantic judgements.  Local replay checks only
the quoted, typed extraction.  It cannot prove extraction completeness or that
two descriptions really denote the same physical event.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from scripts import creative_world_scene_source_state_audit_v1 as prior
from scripts.creative_call_evidence_v1 import digest

VERSION = "creative_world_scene_source_state_audit/v3"
CHECKS = ("spatial_presence", "action_purpose", "emotional_causality")
READINGS = ("intent", "prerequisite", "occurred", "unknown")
RULE = (
    "审查原生源规划与开场，不写正文、不修来源。goal=payload.native_goal_document，"
    "setup=payload.native_opening_setup_document，inputs=payload.authority_inputs。"
    "source_catalog中ref精确映射实际送达的原文字段；evidence只能选该ref及非空逐字短quote，"
    "目录覆盖goal/setup全部文本；authority_inputs仍完整可读以核用户/法律边界，不复制其metadata作物理状态证据目录。"
    "不可拼路径、引用未送达的旧剧情，或只用ID证明事实。全拍按原ID原序覆盖，每拍须有自身字段证据。"
    "逐道具声明quantity/custody是否traced、not_applicable或unknown，不能用无关口径藏掉实际变化；"
    "chain_ids恰好列相应chain；traced必须有chain，not_applicable必须无chain并说明为何无待核状态；"
    "unknown可有或无未决chain但始终阻断。"
    "数量链以object_id+scope+unit区别同一对象、同一计数总体/口径和单位；相同口径只建一链。"
    "before/delta/after必须原生整数或明确null，禁止把汉字数量当类型化值。初始读法initial须有setup证据；"
    "每step的event_id均为非空事件/观察标识，包括intent/prerequisite；重复同一真实事件仍共用标识。"
    "before/after分别照本处原文提取，不根据上一事件或预期连续性替换；源前提不一致照录交程序比较。"
    "setup未给数量时可用最早的源拍prerequisite数量锚，不可因缺数量而猜值。"
    "intent是打算、要求或未兑现目标，不改变实际状态；prerequisite是动作前已需成立的状态，不执行变化；"
    "intent的未来数值/去向允许null表示未指定，而不证明当前状态未知；真正读法未决须reading=unknown。"
    "occurred仅指源剧情明确写出发生，unknown是真正读不清。开放未来不是读不清，也不是已发生。"
    "数量observe/maintain的delta为0且before=after；add的delta>0、remove的delta<0，均after=before+delta。"
    "已发生增减必须有非空event_id和该拍源动作证据；该拍仅说剩余数不同而无变化，不可捏造add来补平。"
    "按明确源时间先后列steps，同拍先后若无法确定用unknown，不按全文重复顺序猜另一次完成。"
    "同一真实事件多处描述聚合一个event_id；如重复列同event_id，typed字段须完全一致，仅证据可不同，"
    "本地只应用一次；不同事件不能为过连续检查故意并成一个。"
    "持有链首态必须逐值取setup.props对应kind、actor_id/container_prop_id/scene_id及location；absent的holder_id/location均空串，"
    "owner_character_id不等于当前持有。state的holder_id按kind引用真实ID，location是稳定的当前位置值；"
    "未知位置或持有用unknown/null，不能换自由措辞绕过前态。occurred转移的before须等于当前状态，"
    "prerequisite只核前提不改变，intent不改变。已入袋后再次从手中放入须有中间取出事件。"
    "静默、神情、安静保持及持续工作不强迫新增物件操作；无事件steps允许空。"
    "三个semantic_checks判断全片空间在场、动作是否产生信息/策略/情绪/必要连续、情绪因果与结尾选择。"
    "不另外填写semantic beat_ids，检查范围由合法evidence ref所属拍确定；全拍覆盖由beat_reviews保证。"
    "fail或unknown引用所有相关拍，pass也给原文理由；不得因动作重复次数就判无意义。"
    "程序只检查已提取事实的类型、引用和连续性，不证明自然语言提取完整正确；"
    "不提交overall pass，语义pass不能覆盖本地状态矛盾或未知。仅诊断，不是文本或视频制作批准。"
)


def _obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _array(item, minimum=0, **extra):
    return {"type": "array", "items": item, "minItems": minimum, **extra}


def _text(maximum=700):
    return {"type": "string", "minLength": 1, "maxLength": maximum, "pattern": r"\S"}


def _leaves(value, parts=()):
    if isinstance(value, str) and value.strip():
        yield parts, value
    elif type(value) is dict:
        for key, child in value.items():
            yield from _leaves(child, parts + (key,))
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from _leaves(child, parts + (index,))


def _catalog(payload, goal):
    result = {}
    for alias, key in (("goal", "native_goal_document"), ("setup", "native_opening_setup_document")):
        for parts, _ in _leaves(payload[key]):
            if any(isinstance(part, str) and (part in ("id", "schema", "contract_version", "version") or
                    part.endswith(("_id", "_ids", "_sha256"))) for part in parts):
                continue
            row = {"source": alias, "path": prior._pointer(parts)}
            if alias == "goal" and len(parts) >= 4 and parts[:2] == ("whole_plan", "beats") and type(parts[2]) is int:
                row["beat_id"] = goal["whole_plan"]["beats"][parts[2]]["id"]
            result[f"R{len(result)+1:04d}"] = row
    return result


def _schema(goal, setup, context, catalog):
    beats = [b["id"] for b in goal["whole_plan"]["beats"]]
    props = [p["id"] for p in goal["whole_plan"]["props"]]
    entities = list(dict.fromkeys(x["id"] for group in ("characters", "scenes", "props") for x in goal["whole_plan"][group]))
    proof = _obj({"ref": {"enum": list(catalog)}, "quote": _text(160)})
    evidence = _array({"$ref": "#/$defs/source_proof"}, 1, uniqueItems=True)
    common = {"beat_id": {"enum": beats}, "reading": {"enum": list(READINGS)},
        "event_id": _text(100), "evidence": deepcopy(evidence)}
    number = {"type": ["integer", "null"]}
    quantity_step = _obj({**deepcopy(common), "operation": {"enum": ["observe", "maintain", "add", "remove", "unknown"]},
        "before": deepcopy(number), "delta": deepcopy(number), "after": deepcopy(number)})
    state = _obj({"kind": {"enum": ["actor", "prop", "scene", "absent", "unknown"]},
        "holder_id": {"enum": ["", *entities]}, "location": {"type": "string", "maxLength": 500}})
    nullable_state = {"anyOf": [state, {"type": "null"}]}
    custody_step = _obj({**deepcopy(common), "before": deepcopy(nullable_state), "after": deepcopy(nullable_state)})
    coverage = _obj({"status": {"enum": ["traced", "not_applicable", "unknown"]}, "reason": _text(),
        "chain_ids": _array(_text(100), uniqueItems=True), "evidence": deepcopy(evidence)})
    semantic = _obj({"status": {"enum": ["pass", "fail", "unknown"]}, "reason": _text(), "evidence": deepcopy(evidence)})
    result = _obj({"schema": {"const": VERSION}, "native_goal_sha256": {"const": digest(goal)},
        "native_setup_sha256": {"const": digest(setup)}, "context_sha256": {"const": context},
        "beat_reviews": _array(_obj({"beat_id": {"enum": beats}, "coverage_summary": _text(),
            "source_evidence": deepcopy(evidence)}), len(beats), maxItems=len(beats)),
        "state_coverage": _obj({p: _obj({"quantity": deepcopy(coverage), "custody": deepcopy(coverage)}) for p in props}),
        "quantity_chains": _array(_obj({"id": _text(100), "object_id": {"enum": props}, "scope": _text(160), "unit": _text(100),
            "initial_reading": {"enum": ["initial", "prerequisite", "unknown"]}, "initial_value": deepcopy(number),
            "initial_evidence": deepcopy(evidence), "steps": _array(quantity_step)})),
        "custody_chains": _array(_obj({"id": _text(100), "object_id": {"enum": props},
            "initial_state": deepcopy(nullable_state), "initial_evidence": deepcopy(evidence), "steps": _array(custody_step)})),
        "semantic_checks": _obj({name: deepcopy(semantic) for name in CHECKS})})
    result["$defs"] = {"source_proof": proof}
    return result


def prepare(inputs, profile, goal, setup):
    payload, authority_manifest = prior._payload(inputs, goal, setup)
    catalog = _catalog(payload, goal)
    payload["source_catalog"] = catalog
    role = profile.get("director", {})
    parameters = deepcopy(role.get("parameters", {}))
    cap = profile.get("stage_parameters", {}).get("goal_audit", {}).get("max_completion_tokens", parameters.get("max_completion_tokens"))
    if (role.get("model") != prior.clients.REVIEW_MODEL or parameters.get("temperature") != .4
            or parameters.get("thinking") != "disabled" or type(cap) is not int or not 0 < cap <= 32000):
        raise ValueError("current DeepSeek reviewer profile and bounded stage cap required")
    parameters["max_completion_tokens"] = cap
    context = digest(payload)
    schema = _schema(goal, setup, context, catalog)
    Draft202012Validator.check_schema(schema)
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    request = {"role": "director", "stage": "goal_audit", "model": role["model"], "parameters": parameters,
        "messages": [{"role": "system", "content": RULE}, {"role": "user", "content": content}], "structured_schema": schema,
        "input_provenance": {"source_state_audit_version": VERSION, "context_sha256": context,
            "original_inputs_sha256": digest(inputs), "native_goal_sha256": digest(goal), "native_setup_sha256": digest(setup)}}
    prior.clients.expected_wire_request(request)
    return {"request": request, "request_sha256": digest(request), "context_sha256": context,
        "views": {"inputs": deepcopy(inputs), "authority_inputs": deepcopy(payload["authority_inputs"]),
            "profile": deepcopy(profile), "goal": deepcopy(goal), "setup": deepcopy(setup), "source_catalog": catalog},
        "manifest": {"schema": VERSION + "/manifest", "context_sha256": context, "original_inputs_sha256": digest(inputs),
            "native_goal_sha256": digest(goal), "native_setup_sha256": digest(setup), "source_catalog_sha256": digest(catalog),
            "source_catalog_fields": len(catalog), "authority_inputs_sha256": digest(payload["authority_inputs"]),
            "catalog_source_groups": ["goal", "setup"], "authority_omitted_from_catalog_not_payload": True,
            "id_version_hash_fields_excluded_from_evidence_catalog": True,
            "authority_stage_projection_manifest": authority_manifest, "prior_full_script_omitted_from_request": True,
            "R01_occurrences": 1, "manual_expected_findings_in_request": False, "program_proves_extraction_complete": False,
            "payload_characters": len(content), "payload_utf8_bytes": len(content.encode("utf-8")),
            "schema_characters": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))), "provider_calls": 0}}


def validate(native, prepared):
    views = prepared["views"]
    if prepared != prepare(views["inputs"], views["profile"], views["goal"], views["setup"]):
        raise ValueError("prepared source audit request or bindings changed")
    goal, setup, catalog = views["goal"], views["setup"], views["source_catalog"]
    documents = {"goal": goal, "setup": setup, "inputs": views["authority_inputs"]}
    contract, failures, unknowns, replay = [], [], [], []
    computation_incomplete = False
    semantic_scopes = {}
    def add(rows, code, path, reason, **details):
        row = {"code": code, "path": path, "reason": reason, **details}
        if row not in rows: rows.append(row)
    for error in Draft202012Validator(prepared["request"]["structured_schema"]).iter_errors(native):
        add(contract, "NATIVE_SCHEMA_INVALID", prior._pointer(error.absolute_path) or "/", error.message)
    def decision():
        status = "contract_rejected" if contract else "unknown" if unknowns else "fail" if failures else "pass"
        return {"schema": VERSION + "/decision", "valid": not contract, "accepted": status == "pass",
            "status": "source_state_" + status, "contract_findings": contract,
            "findings": contract if contract else failures, "uncertainties": unknowns, "typed_replay": replay,
            "computed_state_findings": deepcopy([row for row in failures if row["code"].startswith(("QUANTITY_", "CUSTODY_"))]),
            "computed_state_analysis_incomplete": computation_incomplete, "semantic_scopes_from_evidence": deepcopy(semantic_scopes),
            "native_report_sha256": digest(native), "native_goal_sha256": digest(goal), "native_setup_sha256": digest(setup),
            "context_sha256": prepared["context_sha256"], "native_report_modified": False,
            "program_proves_extraction_complete": False, "program_proves_semantic_state": False,
            "text_ready_for_director": False, "creative_quality_passed": False, "provider_calls": 0}
    if contract:
        # This private shape check is only permission to compute diagnostic
        # facts from intact typed fields. It does not admit an invalid report,
        # modify native data, or replace the actual outbound closed schema.
        shape = deepcopy(prepared["request"]["structured_schema"])
        def diagnostic_shape(node):
            if type(node) is dict:
                if node.get("type") == "object": node["additionalProperties"] = True
                if "event_id" in node.get("properties", {}): node["properties"]["event_id"] = {"type": "string"}
                for child in node.values(): diagnostic_shape(child)
            elif type(node) is list:
                for child in node: diagnostic_shape(child)
        diagnostic_shape(shape)
        shape["properties"]["semantic_checks"] = {"type": "object"}
        if any(Draft202012Validator(shape).iter_errors(native)):
            computation_incomplete = True
            return decision()
    beats = [b["id"] for b in goal["whole_plan"]["beats"]]
    bindex = {bid: i for i, bid in enumerate(beats)}
    if [r["beat_id"] for r in native["beat_reviews"]] != beats:
        add(contract, "BEAT_COVERAGE", "/beat_reviews", "every source beat must occur once in exact source order")
    def proof_check(proofs, path, beat=None, setup_prop=None):
        for i, proof in enumerate(proofs):
            entry = catalog[proof["ref"]]
            value = prior._resolve(documents[entry["source"]], entry["path"])
            if not proof["quote"].strip() or proof["quote"] not in value:
                add(contract, "SOURCE_QUOTE_INVALID", f"{path}/{i}", "exact quote absent from the catalog field")
        if beat and not any(catalog[p["ref"]].get("beat_id") == beat for p in proofs):
            add(contract, "BEAT_LOCAL_EVIDENCE_MISSING", path, "evidence must cite this source beat: " + beat)
        if setup_prop and not any(catalog[p["ref"]]["source"] == "setup" and
                catalog[p["ref"]]["path"].startswith("/props/" + setup_prop + "/") for p in proofs):
            add(contract, "SETUP_PROP_EVIDENCE_MISSING", path, "initial custody must cite this native setup prop")
    for i, row in enumerate(native["beat_reviews"]):
        proof_check(row["source_evidence"], f"/beat_reviews/{i}/source_evidence", row["beat_id"])
    chain_ids, signatures = set(), set()
    for family in ("quantity", "custody"):
        chains = native[family + "_chains"]
        for ci, chain in enumerate(chains):
            path = f"/{family}_chains/{ci}"
            if chain["id"] in chain_ids: add(contract, "CHAIN_ID_DUPLICATE", path + "/id", "chain ID must be globally unique")
            chain_ids.add(chain["id"])
            signature = (family, chain["object_id"], chain.get("scope"), chain.get("unit"))
            if signature in signatures: add(contract, "CHAIN_SCOPE_DUPLICATE", path, "same object/scope/unit must share one chain")
            signatures.add(signature)
            proof_check(chain["initial_evidence"], path + "/initial_evidence", setup_prop=chain["object_id"] if family == "custody" else None)
            if family == "quantity":
                current = chain["initial_value"]
                if type(current) not in (int, type(None)):
                    add(contract, "NATIVE_INTEGER_REQUIRED", path + "/initial_value", "integer must be a native int, not float/bool")
                if chain["initial_reading"] == "initial" and not any(catalog[p["ref"]]["source"] == "setup" for p in chain["initial_evidence"]):
                    add(contract, "INITIAL_SETUP_EVIDENCE_MISSING", path + "/initial_evidence", "initial quantity needs setup evidence")
                if chain["initial_reading"] == "initial":
                    proof_check(chain["initial_evidence"], path + "/initial_evidence", setup_prop=chain["object_id"])
                if chain["initial_reading"] == "prerequisite" and not any(catalog[p["ref"]].get("beat_id") for p in chain["initial_evidence"]):
                    add(contract, "INITIAL_PREREQUISITE_EVIDENCE_MISSING", path + "/initial_evidence", "quantity prerequisite needs source beat evidence")
                if current is None or chain["initial_reading"] == "unknown":
                    add(unknowns, "QUANTITY_INITIAL_UNKNOWN", path, "initial counting state is unresolved")
                    current = None
            else:
                current = chain["initial_state"]
                expected = setup["props"][chain["object_id"]]
                expected_state = {"kind": expected["kind"], "holder_id": expected.get("actor_id", expected.get("container_prop_id", expected.get("scene_id", ""))), "location": expected.get("location", "")}
                if current is not None and current != expected_state:
                    add(failures, "CUSTODY_INITIAL_CONFLICT", path + "/initial_state", "typed initial state differs from native setup, not static owner", expected=expected_state, actual=current)
                if current is None or current["kind"] == "unknown":
                    add(unknowns, "CUSTODY_INITIAL_UNKNOWN", path, "initial custody is unresolved")
                    current = None
            seen, previous_beat = {}, -1
            for si, step in enumerate(chain["steps"]):
                sp = path + f"/steps/{si}"
                proof_check(step["evidence"], sp + "/evidence", step["beat_id"])
                bi = bindex[step["beat_id"]]
                if bi < previous_beat: add(contract, "CHAIN_SOURCE_ORDER", sp + "/beat_id", "trace steps must follow source beat order")
                previous_beat = bi
                reading = step["reading"]
                fields = ("before", "delta", "after", "operation") if family == "quantity" else ("before", "after")
                sig = {key: step[key] for key in fields}
                event = step["event_id"]
                if reading == "occurred" and not event.strip():
                    add(contract, "OCCURRED_EVENT_ID_REQUIRED", sp + "/event_id", "actual event needs a stable nonempty ID")
                if family == "quantity":
                    for key in ("before", "delta", "after"):
                        if type(step[key]) not in (int, type(None)):
                            add(contract, "NATIVE_INTEGER_REQUIRED", sp + "/" + key, "integer must be native int, not float/bool")
                    unresolved = any(step[key] is None for key in ("before", "delta", "after")) or step["operation"] == "unknown"
                else:
                    unresolved = any(step[key] is None or step[key]["kind"] == "unknown" for key in ("before", "after"))
                    for key in ("before", "after"):
                        state = step[key]
                        if state is not None and state["kind"] not in ("unknown", "absent"):
                            ids = {x["id"] for x in goal["whole_plan"][{"actor": "characters", "prop": "props", "scene": "scenes"}[state["kind"]]]}
                            if state["holder_id"] not in ids or not state["location"].strip():
                                add(contract, "STATE_HOLDER_KIND", sp + "/" + key, "holder_id must match its typed kind")
                        elif state is not None and state["kind"] == "absent" and (state["holder_id"] or state["location"]):
                            add(contract, "ABSENT_STATE_FIELDS", sp + "/" + key, "absent state has no holder or location")
                if reading == "intent" and unresolved:
                    replay.append({"path": sp, "event_id": event, "applied": False,
                        "state_after": deepcopy(current), "reason": "unspecified future intent does not alter actual state"})
                    continue
                if reading == "unknown" or unresolved:
                    add(unknowns, "TYPED_STATE_UNKNOWN", sp, "state/event interpretation is unresolved")
                    if reading != "intent": current = None
                    continue
                if reading == "occurred" and event.strip() and event in seen:
                    if sig != seen[event]: add(contract, "EVENT_ID_TYPED_CONFLICT", sp, "same physical event has different typed transition")
                    replay.append({"path": sp, "event_id": event, "applied": False, "reason": "same event aggregated once"})
                    continue
                if family == "quantity":
                    if step["after"] != step["before"] + step["delta"]:
                        add(failures, "QUANTITY_ARITHMETIC_CONFLICT", sp, "after must equal before plus delta", expected=step["before"] + step["delta"], actual=step["after"])
                    op = step["operation"]
                    if (op in ("observe", "maintain") and (step["delta"] != 0 or step["before"] != step["after"]) or
                            op == "add" and step["delta"] <= 0 or op == "remove" and step["delta"] >= 0):
                        add(failures, "QUANTITY_OPERATION_CONFLICT", sp, "typed operation contradicts its signed quantity change")
                    if reading == "prerequisite" and (step["delta"] != 0 or step["before"] != step["after"]):
                        add(contract, "PREREQUISITE_IS_NOT_EVENT", sp, "prerequisite observes a state and cannot perform a quantity change")
                elif reading == "prerequisite" and step["before"] != step["after"]:
                    add(contract, "PREREQUISITE_IS_NOT_EVENT", sp, "prerequisite cannot perform a custody transfer")
                if reading != "intent":
                    if current is None:
                        add(unknowns, "PREVIOUS_STATE_UNKNOWN", sp, "cannot prove prerequisite after unresolved actual state")
                    elif step["before"] != current:
                        add(failures, family.upper() + "_PRECONDITION_CONFLICT", sp + "/before", "event/observation prerequisite differs from prior actual state", expected=current, actual=step["before"])
                    if reading == "occurred":
                        if event.strip(): seen[event] = sig
                        current = deepcopy(step["after"])
                replay.append({"path": sp, "event_id": event, "applied": reading == "occurred", "state_after": deepcopy(current)})
        for prop, coverage in native["state_coverage"].items():
            row = coverage[family]; cp = "/state_coverage/" + prop + "/" + family
            proof_check(row["evidence"], cp + "/evidence")
            expected_ids = [c["id"] for c in chains if c["object_id"] == prop]
            if (row["chain_ids"] != expected_ids or row["status"] == "traced" and not expected_ids or
                    row["status"] == "not_applicable" and expected_ids):
                add(contract, "STATE_COVERAGE_BINDING", cp, "exact chain IDs required; traced needs chains, not_applicable forbids chains, unknown permits either")
            if row["status"] == "unknown": add(unknowns, "STATE_EXTRACTION_UNKNOWN", cp, row["reason"])
    for name, check in native["semantic_checks"].items():
        path = "/semantic_checks/" + name
        check_schema = prepared["request"]["structured_schema"]["properties"]["semantic_checks"]["properties"].get(name)
        if check_schema is None or any(Draft202012Validator({**deepcopy(check_schema), "$defs": prepared["request"]["structured_schema"]["$defs"]}).iter_errors(check)):
            continue
        proof_check(check["evidence"], path + "/evidence")
        semantic_scopes[name] = [bid for bid in beats if any(catalog[p["ref"]].get("beat_id") == bid for p in check["evidence"])]
        if check["status"] == "fail": add(failures, "SEMANTIC_" + name.upper(), path, check["reason"], evidence=deepcopy(check["evidence"]))
        if check["status"] == "unknown": add(unknowns, "SEMANTIC_" + name.upper(), path, check["reason"], evidence=deepcopy(check["evidence"]))
    return decision()
