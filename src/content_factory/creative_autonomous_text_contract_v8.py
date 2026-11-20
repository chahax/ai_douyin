"""Focused source-bound business fact and language extraction for text gating.

Frozen v1-v7 remain unchanged. A source-only extractor declares factual scope;
a separate script extractor reports actual claims and precise language findings.
Local decisions compare typed scope and never alter native semantic judgments.
"""
from __future__ import annotations
from copy import deepcopy
from . import creative_autonomous_text_contract_v7 as prior

base=prior.base
v2=prior.v2
VERSION="creative_autonomous_text_contract/v8"
CRITERIA=deepcopy(prior.CRITERIA)
FUNCTIONS=list(prior.FUNCTIONS)
_digest=prior._digest
FROZEN_SOURCE_REPAIR=prior.FROZEN_SOURCE_REPAIR
FROZEN_PLAN_REPAIR=prior.FROZEN_PLAN_REPAIR
build_plan_schema=prior.build_plan_schema
compile_plan=prior.compile_plan
validate_plan=prior.validate_plan
build_script_schema=prior.build_script_schema
compile_script=prior.compile_script
evidence_catalog=prior.evidence_catalog
build_source_audit_schema=prior.build_source_audit_schema
compile_source_audit=prior.compile_source_audit
validate_source_audit=prior.validate_source_audit
decide_source_audit=prior.decide_source_audit
build_review_schema=prior.build_review_schema
compile_review=prior.compile_review
validate_review=prior.validate_review
decide_review=prior.decide_review
project_legacy_review=prior.project_legacy_review
project_legacy_audit=prior.project_legacy_audit

FACT_CATEGORIES=["employment_departure_timing","contract_term","employment_start_timing",
    "wage_or_payment","compensation_or_liability","follow_up_undertaking",
    "company_decision","employee_intention","document_fact","procedural_action",
    "other_legal_fact","scene_timing","private_pressure","performance_action"]
CONTEXT_CATEGORIES={"scene_timing","private_pressure","performance_action"}
MODALITIES=["assertion","request","question","conditional_undertaking","future_intention","other"]
SOURCE_SCOPE_RULE=(
    "仅从冻结brief提取法律/劳动业务事实范围，完整拆分复合负约束为通用类别，"
    "不读剧本、旧审查或测试预期。离开时间包括相对日期和期限；后续undertaking包括公司和办理人的承诺、条件性承担及个人未来行动，不能全部称公司保证。"
    "restrictions绑定限制的来源ID及精确原文片段；allowed_claims只列原来源确实提供的值，value为来源片段内明确真实值，可保持原短句；未提供值留空列表，不发明。"
    "每条source fact须coverage，关联本条所有rule IDs，确属非业务源可non_business；复合限制不能缩为一项。actor_id是主张主体而非转述说话人。不得把同类别的限制句当新增事实许可。普通本场谈话时间、私人交差压力与自然表演不是新增劳动日期或业务承诺。source_quotes只引用真实片段，不复述整段。必要来源判断未知报告unknown_items且coverage.availability=unknown，不臆造允许值。")
FACT_SCOPE_RULE=(
    "独立仅读冻结brief、typed scope及完整实际正文。逐实际步骤记录业务主张，特别覆盖对白中相对离开日期、期限、合同、入职、支付/赔偿与后续承担事项。"
    "报告实际主张而非pass/fail；actor_id是主张承担或决定主体，不是说话人，转述公司决定用company，个人拒绝/未来行动用相应人物。value表示实际命题，可在语义确实相同时归一到来源真实值，不能删限定语、把不允许主张归一成许可。"
    "请求或质问不自动是事实断言；请求/问句若带实际业务事实预设，须另提其assertion或条件性安排原子。区分戏内今天谈话与就业离开期限，区分私人交差压力与新增后续安排。"
    "每个正文步骤必须coverage，无业务主张可空列表，自然动作不当业务新事实。"
    "另逐句核对明确语病、施事歧义、意义冲突，仅列有确定原文证据的dialogue_findings；判断未知列unknown_items。"
    "所有quote用可唯一定位的完整原文子句，不用重复短词。原生状态和问题不能改写为通过。")
AUDIT_RULE=(
    "只从实际正文还原动作、说话及最初行动前物理状态，不用premise/event补缺失。"
    "fact_checks/initial_state_checks仅填写来源ID、实际observed及审查判断；expected来源由本地编译，禁止生成expected_fact/expected_state。"
    "发生与支持证据分离。occurrence_spans可只精确标部分occurrence_refs，其余按完整步骤；片段必须原文唯一位置。")


def _quotes_schema(brief):
    facts=list(v2._facts(brief))
    return {"type":"array","minItems":1,"uniqueItems":True,
        "items":base._obj({"fact_id":{"enum":facts} if facts else False,"quote":base._text()})}


def build_source_fact_scope_schema(brief):
    facts=list(v2._facts(brief))
    source={"id":base._text(),"category":{"enum":FACT_CATEGORIES},
            "source_fact_ids":base._array_refs(facts,1),"source_quotes":_quotes_schema(brief)}
    restriction={**deepcopy(source),"mode":{"enum":["forbid_new","absence"],
        "description":"forbid_new禁止来源未给的新值，不禁止已明确给出的值；absence仅来源绝对禁止出现此类时使用。"}}
    allowed={**deepcopy(source),"actor_id":{"enum":base._actors(brief)+[""]},"value":base._text()}
    ids={"type":"array","uniqueItems":True,"items":base._text()}
    coverage=base._obj({"fact_id":{"enum":facts} if facts else False,
        "restriction_ids":deepcopy(ids),"allowed_claim_ids":deepcopy(ids),
        "non_business":{"type":"boolean"},"availability":{"enum":["known","unknown"]},
        "explanation":base._text()})
    coverage["allOf"]=[
        {"if":{"properties":{"availability":{"const":"known"},"non_business":{"const":False}}},
         "then":{"anyOf":[{"properties":{"restriction_ids":{"minItems":1}}},
                             {"properties":{"allowed_claim_ids":{"minItems":1}}}]}},
        {"if":{"properties":{"non_business":{"const":True}}},
         "then":{"properties":{"restriction_ids":{"maxItems":0},"allowed_claim_ids":{"maxItems":0}}}},
    ]
    return base._obj({"brief_sha256":{"const":_digest(brief)},
        "restrictions":{"type":"array","items":base._obj(restriction)},
        "allowed_claims":{"type":"array","items":base._obj(allowed)},
        "source_fact_coverage":{"type":"array","minItems":len(facts),"maxItems":len(facts),"items":coverage},
        "unknown_items":{"type":"array","items":base._obj({
            "source_fact_ids":base._array_refs(facts,1),"source_quotes":_quotes_schema(brief),
            "explanation":base._text()})}})


def validate_source_fact_scope(raw,brief):
    base._validate_schema(build_source_fact_scope_schema(brief),raw,"source_fact_scope")
    facts=v2._facts(brief)
    ids=[]
    for table in ("restrictions","allowed_claims","unknown_items"):
        for row in raw[table]:
            if table!="unknown_items":ids.append(row["id"])
            quoted=[item["fact_id"] for item in row["source_quotes"]]
            if len(quoted)!=len(set(quoted)) or set(quoted)!=set(row["source_fact_ids"]):
                raise ValueError("source scope quotes must cover exactly its source_fact_ids")
            for item in row["source_quotes"]:
                if not item["quote"].strip() or item["quote"] not in facts[item["fact_id"]]:
                    raise ValueError("source scope quote must be an unchanged source fragment")
            if table=="allowed_claims" and not any(row["value"] in item["quote"] for item in row["source_quotes"]):
                raise ValueError("source allowed value must literally exist in its quoted source")
    if len(ids)!=len(set(ids)):raise ValueError("source rule IDs must be unique across rules")
    for allowed in raw["allowed_claims"]:
        for rule in raw["restrictions"]:
            if rule["category"]!=allowed["category"]:continue
            if rule["mode"]=="absence":
                raise ValueError("absolute source absence conflicts with an allowed claim category")
            # A compound source may both give a value and forbid inventing more.
            # Reject copying the restriction itself as a positive allowance,
            # while permitting a separately quoted explicit source value.
            if any(left["fact_id"]==right["fact_id"] and
                   (left["quote"] in right["quote"] or right["quote"] in left["quote"])
                   for left in allowed["source_quotes"] for right in rule["source_quotes"]):
                raise ValueError("a prohibition quote cannot self-authorize an allowed claim")
    coverage=raw["source_fact_coverage"]
    keys=[row["fact_id"] for row in coverage]
    if len(keys)!=len(set(keys)) or set(keys)!=set(facts):
        raise ValueError("source factual scope must cover every fact exactly once")
    for row in coverage:
        restricted={item["id"] for item in raw["restrictions"] if row["fact_id"] in item["source_fact_ids"]}
        allowed={item["id"] for item in raw["allowed_claims"] if row["fact_id"] in item["source_fact_ids"]}
        if set(row["restriction_ids"])!=restricted or set(row["allowed_claim_ids"])!=allowed:
            raise ValueError("source fact coverage must link exactly its source rules")
    unknown=bool(raw["unknown_items"]) or any(row["availability"]=="unknown" for row in coverage)
    return {"complete":True,"source_hash":_digest(raw),"brief_sha256":_digest(brief),
            "source_scope_known":not unknown,"availability_unknown":unknown,
            "source_scope_semantics_model_extracted":True,"semantic_quality_approved":False}


def compile_source_fact_scope(raw,brief):
    validation=validate_source_fact_scope(raw,brief)
    if not validation["source_scope_known"]:
        raise ValueError("source factual scope availability_unknown; halt_source_uncertain, not interface failure")
    result=deepcopy(raw)
    result["source_fact_texts"]=deepcopy(v2._facts(brief))
    return result


def _native_scope(scope,brief):
    raw=deepcopy(scope)
    if "source_fact_texts" in raw:
        if raw.pop("source_fact_texts")!=v2._facts(brief):
            raise ValueError("compiled factual scope changed frozen source text")
    if not validate_source_fact_scope(raw,brief)["source_scope_known"]:
        raise ValueError("source factual scope availability_unknown; no script extraction may follow")
    return raw


def _actual_quote(ref,quote,entries):
    if ref not in entries or not quote.strip():raise ValueError("unknown or empty extract source evidence")
    original=entries[ref]["quote"]
    start=original.find(quote)
    if start<0 or original.find(quote,start+1)>=0:
        raise ValueError("extract quote must identify one unchanged actual source position")


def build_fact_scope_schema(script,brief,scope):
    _native_scope(scope,brief)
    refs=list(evidence_catalog(script))
    origin={"id":base._text(),"source_ref":{"enum":refs},"quote":base._text()}
    claim=base._obj({**origin,"category":{"enum":FACT_CATEGORIES},
        "actor_id":{"enum":base._actors(brief)+[""]},"value":base._text(),
        "modality":{"enum":MODALITIES},"source_fact_ids":base._array_refs(list(v2._facts(brief)),0)})
    finding=base._obj({**origin,"issue_type":{"enum":["ungrammatical","ambiguous_actor","meaning_conflict"]},
                      "explanation":base._text()})
    unknown=base._obj({**origin,"topic":base._text(),"explanation":base._text()})
    ids={"type":"array","uniqueItems":True,"items":base._text()}
    coverage=base._obj({"source_ref":{"enum":refs},"claim_ids":deepcopy(ids),
        "dialogue_finding_ids":deepcopy(ids),"unknown_ids":deepcopy(ids)})
    return base._obj({"script_sha256":{"const":_digest(script)},"brief_sha256":{"const":_digest(brief)},
        "scope_sha256":{"const":_digest(scope)},"claims":{"type":"array","items":claim},
        "dialogue_findings":{"type":"array","items":finding},
        "unknown_items":{"type":"array","items":unknown},
        "step_coverage":{"type":"array","minItems":len(refs),"maxItems":len(refs),"items":coverage}})


def validate_fact_scope_extract(value,script,brief,scope):
    base._validate_schema(build_fact_scope_schema(script,brief,scope),value,"fact_scope_extract")
    body={key:deepcopy(item) for key,item in script.items() if key!="selected_candidate_id"}
    if compile_script(body,brief)!=script:raise ValueError("extract script changed compiler-bound source")
    entries=evidence_catalog(script)
    if [row["source_ref"] for row in value["step_coverage"]]!=list(entries):
        raise ValueError("focused extract must cover every actual step in original order")
    specs=[("claims","claim_ids"),("dialogue_findings","dialogue_finding_ids"),("unknown_items","unknown_ids")]
    allids=[]
    for table,key in specs:
        rows={row["id"]:row for row in value[table]}
        if len(rows)!=len(value[table]):raise ValueError("extract IDs must be unique")
        allids.extend(rows)
        linked=[]
        for coverage in value["step_coverage"]:
            for id_ in coverage[key]:
                if id_ not in rows or rows[id_]["source_ref"]!=coverage["source_ref"]:
                    raise ValueError("extract coverage links a missing or different-step finding")
                linked.append(id_)
        if len(linked)!=len(set(linked)) or set(linked)!=set(rows):
            raise ValueError("extract coverage must link every finding exactly once")
        for row in rows.values():
            _actual_quote(row["source_ref"],row["quote"],entries)
            if table=="dialogue_findings" and entries[row["source_ref"]]["kind"]!="dialogue":
                raise ValueError("dialogue finding must cite an actual spoken step")
    if len(allids)!=len(set(allids)):raise ValueError("extract IDs must be unique across tables")
    return {"complete":True,"source_hash":_digest(value),"script_sha256":_digest(script),
        "brief_sha256":_digest(brief),"scope_sha256":_digest(scope),"step_count":len(entries),
        "semantic_quality_approved":False}


def decide_fact_scope_extract(value,script,brief,scope):
    validation=validate_fact_scope_extract(value,script,brief,scope)
    source=_native_scope(scope,brief)
    entries=evidence_catalog(script)
    requirements,uncertainties=[],[]
    def add(target,code,row,problem):
        v2._add(target,entries,code,[row["source_ref"]],problem,FROZEN_SOURCE_REPAIR)
        target[-1]["extracted_quote"]=row["quote"]
        target[-1]["claim_id"]=row["id"]
    for row in value["claims"]:
        if row["category"] in CONTEXT_CATEGORIES or row["modality"] in ("question","request"):continue
        rules=[item for item in source["restrictions"] if item["category"]==row["category"]]
        matches=[item for item in source["allowed_claims"] if item["category"]==row["category"]
            and item["actor_id"] in ("",row["actor_id"]) and item["value"]==row["value"]
            and set(item["source_fact_ids"]).intersection(row["source_fact_ids"])]
        if any(rule["mode"]=="absence" for rule in rules) or not matches:
            add(requirements,"FACT_SCOPE_"+row["id"],row,
                "实际正文引入未获来源允许的业务主张："+row["category"]+"；"+row["value"]+
                "；话语方式="+row["modality"]+"。仅使用冻结来源，不新增期限、业务事实或后续承担。")
    for row in value["dialogue_findings"]:
        add(requirements,"LANGUAGE_FOCUSED_"+row["id"],row,row["issue_type"]+"："+row["explanation"])
    for row in value["unknown_items"]:
        add(uncertainties,"FACT_SCOPE_UNKNOWN_"+row["id"],row,row["topic"]+"："+row["explanation"])
    result=v2._result("fact_scope_extract",value,script,validation,requirements,uncertainties)
    result["scope_sha256"]=_digest(scope)
    return result


def build_audit_schema(script,brief,plan):
    schema=prior.build_audit_schema(script,brief,plan)
    spans=schema["properties"]["obligation_evidence"]["items"]["properties"]["occurrence_spans"]
    spans["description"]=("可选，仅为部分occurrence_refs提供精确发生子句。其他引用用完整正文步骤窗口；"
        "每个指定ref最多一条quote，须原文唯一出现，不猜重复位置。严格先后共享步骤需明确非重叠发生子句。")
    return schema


def _expanded_audit(value,script,brief,plan):
    base._validate_schema(build_audit_schema(script,brief,plan),value,"native_audit")
    result=deepcopy(value)
    entries=evidence_catalog(script)
    for proof in result["obligation_evidence"]:
        if "occurrence_spans" not in proof:continue
        spans=proof["occurrence_spans"]
        ids=[row["ref_id"] for row in spans]
        if len(ids)!=len(set(ids)) or not set(ids).issubset(proof["occurrence_refs"]):
            raise ValueError("partial occurrence spans must name unique actual occurrence refs")
        for row in spans:_actual_quote(row["ref_id"],row["quote"],entries)
        spans.extend({"ref_id":ref,"quote":entries[ref]["quote"]}
                     for ref in proof["occurrence_refs"] if ref not in ids)
    prior.validate_audit(result,script,brief,plan)
    return result


def compile_audit(value,script,brief,plan):
    return prior.compile_audit(_expanded_audit(value,script,brief,plan),script,brief,plan)


def validate_audit(value,script,brief,plan):
    expanded=_expanded_audit(value,script,brief,plan)
    compiled=prior.compile_audit(expanded,script,brief,plan)
    validation=prior.validate_audit(expanded,script,brief,plan)
    return {**validation,"source_hash":_digest(value),"raw_audit_sha256":_digest(value),
        "compiled_audit_sha256":_digest(compiled),"partial_occurrence_windows_compiled":True}


def decide_audit(value,script,brief,plan):
    result=prior.decide_audit(_expanded_audit(value,script,brief,plan),script,brief,plan)
    result.update(validation=validate_audit(value,script,brief,plan),raw_audit_sha256=_digest(value),
        compiled_audit_sha256=_digest(compile_audit(value,script,brief,plan)))
    return result


def combine_decisions(review,audit,script,brief,plan):
    result=prior.combine_decisions(review,_expanded_audit(audit,script,brief,plan),script,brief,plan)
    result.update(raw_audit_sha256=_digest(audit),compiled_audit_sha256=_digest(compile_audit(audit,script,brief,plan)))
    result["validation"]["literal_audit"]=validate_audit(audit,script,brief,plan)
    return result


def combine_scope_decisions(review,audit,extract,script,brief,plan,scope):
    primary=combine_decisions(review,audit,script,brief,plan)
    focused=decide_fact_scope_extract(extract,script,brief,scope)
    values={"review":review,"audit":audit,"extract":extract}
    result=v2._result("combined",values,script,{"complete":True,"source_hash":_digest(values),
        "primary_and_literal":primary["validation"],"focused_scope":focused["validation"]},
        primary["revision_requirements"]+focused["revision_requirements"],
        primary["uncertainties"]+focused["uncertainties"])
    result.update(plan_sha256=_digest(plan),scope_sha256=_digest(scope),
        review_sha256=_digest(review),audit_sha256=_digest(audit),extract_sha256=_digest(extract),
        independent_scope_extract_required=True)
    return result

combine_fact_scope_decisions=combine_scope_decisions
