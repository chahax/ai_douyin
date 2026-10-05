"""Offline only: freeze small-context rule variants before any budget approval."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/qa/minimax_rule_probe_20261003/matrix_v3"
PARENT=ROOT/"data/production_trials/boundary_live_action_reference_v15_20261001/round_01"
DIAGNOSTIC=ROOT/"data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299"
PARAMETERS={"model":"MiniMax-M3","temperature":0.4,"thinking":"disabled","max_completion_tokens":1024,
            "tool_choice":{"type":"function","function":{"name":"submit_creative_json"}}}
CONTEXT={"schema":"synthetic_rule_probe_context/v1","fixture_only":True,
    "characters":[{"id":"C01","name":"甲"},{"id":"C02","name":"乙"}],
    "script":{"beats":[{"id":"B1","event":"甲把杯子放到桌面。",
                       "dialogue":[{"speaker":"C02","text":"今晚我自己弄，你先走。"}]}]},
    "task":"只提交两项表演要求：第一项，放杯事件结束后观察甲两秒；第二项，乙说这句对白期间观察甲两秒。来源填写对应剧本字段路径。"}
BASE_SYSTEM="用指定工具提交本任务的完整结果。不要写分析或其他正文。"
RULES=("beats必须是仅含本拍B1的数组。performance_requirements必须直接是数组，不能用item或items对象包裹。每项是一个对象，"
       "包含id、subject、stimulus_source、relation、minimum_seconds。id互不重复；"
       "subject是被观察的人物编号。stimulus_source只能是script.beats.0.event或script.beats.0.dialogue.0.text。"
       "relation说明观察窗口相对刺激的时间：before在刺激之前，during在刺激期间，after在刺激结束之后。"
       "本协议事件来源只能选before/after；对白来源允许before/during/after。minimum_seconds是数值。")
# Different, explicitly marked example; it cannot be copied as this task's answer.
EXAMPLE={"beats":[{"beat_id":"DEMO_B9","performance_requirements":[
    {"id":"DEMO_EVENT","subject":"C02","stimulus_source":"script.beats.8.event","relation":"before","minimum_seconds":1},
    {"id":"DEMO_DIALOGUE","subject":"C02","stimulus_source":"script.beats.8.dialogue.0.text","relation":"after","minimum_seconds":1}]}]}
EXPECTED={"beats":[{"beat_id":"B1","performance_requirements":[
    {"id":"EVENT_REACTION","subject":"C01","stimulus_source":"script.beats.0.event","relation":"after","minimum_seconds":2},
    {"id":"DIALOGUE_REACTION","subject":"C01","stimulus_source":"script.beats.0.dialogue.0.text","relation":"during","minimum_seconds":2}]}]}

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def digest(value):return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()
def obj(properties):return {"type":"object","additionalProperties":False,"required":list(properties),"properties":properties}

def base_schema():
    row=obj({"id":{"type":"string","minLength":1},"subject":{"type":"string","minLength":1},
             "stimulus_source":{"type":"string","minLength":1},"relation":{"type":"string","minLength":1},
             "minimum_seconds":{"type":"number","exclusiveMinimum":0}})
    beat=obj({"beat_id":{"type":"string","minLength":1},
              "performance_requirements":{"type":"array","minItems":2,"maxItems":2,"items":row}})
    return obj({"beats":{"type":"array","minItems":1,"maxItems":1,"items":beat}})

def flat_schema():
    s=base_schema()
    beat=s["properties"]["beats"]["items"]
    beat["properties"]["beat_id"]={"enum":["B1"]}
    p=beat["properties"]["performance_requirements"]["items"]["properties"]
    p["subject"]={"type":"string","enum":["C01","C02"]}
    p["stimulus_source"]={"type":"string","enum":["script.beats.0.event","script.beats.0.dialogue.0.text"]}
    p["relation"]={"enum":["before","during","after"]}
    return s

def prefix_schema():
    s=flat_schema()
    beats=s["properties"]["beats"]
    beats["prefixItems"]=[deepcopy(beats["items"])]
    beats["items"]=False
    return s

def conditional_schema():
    s=prefix_schema()
    row=s["properties"]["beats"]["prefixItems"][0]["properties"]["performance_requirements"]["items"]
    row["allOf"]=[{"if":{"properties":{"stimulus_source":{"const":"script.beats.0.event"}},"required":["stimulus_source"]},
                   "then":{"properties":{"relation":{"enum":["before","after"]}}}}]
    return s

def variants():
    base=base_schema();flat=flat_schema();prefix=prefix_schema();conditional=conditional_schema()
    cases=[
        ("A","基本工具格式",None,base,BASE_SYSTEM),
        ("B","基本格式加中文关系说明","A",base,BASE_SYSTEM+"\n"+RULES),
        ("C","中文说明加另一场景的正确结构示例","B",base,BASE_SYSTEM+"\n"+RULES+
         "\n下面是另一场景的完整格式示例，只参考结构，不复制其中人物、路径、关系或数值：\n"+canonical(EXAMPLE)),
        ("D","中文说明加简单字段枚举","B",flat,BASE_SYSTEM+"\n"+RULES),
        ("E","枚举Schema改用等价逐拍prefixItems","D",prefix,BASE_SYSTEM+"\n"+RULES),
        ("F","逐拍Schema加入if/then条件","E",conditional,BASE_SYSTEM+"\n"+RULES),
    ]
    value=[]
    for cid,title,baseline,schema,rule_text in cases:
        schema=deepcopy(schema)
        if rule_text != BASE_SYSTEM:
            schema["description"]=rule_text[len(BASE_SYSTEM)+1:]
        # The six messages are byte-identical; only tool schema encoding varies.
        messages=[{"role":"system","content":BASE_SYSTEM},{"role":"user","content":canonical(CONTEXT)}]
        wire={"model":PARAMETERS["model"],"messages":messages,"temperature":PARAMETERS["temperature"],
              "max_completion_tokens":PARAMETERS["max_completion_tokens"],"thinking":{"type":"disabled"},
              "tools":[{"type":"function","function":{"name":"submit_creative_json",
                         "description":"提交本阶段完整结构化创作结果","parameters":schema}}],
              "tool_choice":PARAMETERS["tool_choice"]}
        value.append({"case_id":cid,"title":title,"compare_to":baseline,
                      "input_context_sha256":digest(CONTEXT),"request_sha256":digest(wire),
                      "request":wire,"conservative_token_reservation":len(canonical(wire))+PARAMETERS["max_completion_tokens"]})
    return value

def evaluate(output):
    checks={}
    schema_errors=list(Draft202012Validator(base_schema()).iter_errors(output))
    checks["base_shape"]={"passed":not schema_errors,
        "errors":[{"path":".".join(map(str,e.absolute_path)),"message":e.message} for e in schema_errors]}
    if schema_errors:
        for name in ("sources","source_relation","task_values"):
            checks[name]={"passed":None,"reason":"blocked_by_base_shape"}
        return {"status":"schema_rejected","checks":checks,"automatic_retry":False,"semantic_approval":False}
    rows=output["beats"][0]["performance_requirements"]
    allowed=["script.beats.0.event","script.beats.0.dialogue.0.text"]
    checks["sources"]={"passed":set(r["stimulus_source"] for r in rows)==set(allowed)}
    checks["source_relation"]={"passed":all(
        (r["relation"] in ["before","after"] if r["stimulus_source"]==allowed[0]
         else r["relation"] in ["before","during","after"] if r["stimulus_source"]==allowed[1] else False)
        for r in rows)}
    expected=[(allowed[0],"after"),(allowed[1],"during")]
    checks["task_values"]={"passed":output["beats"][0]["beat_id"]=="B1" and len({r["id"] for r in rows})==2
        and [(r["stimulus_source"],r["relation"]) for r in rows]==expected
        and all(r["subject"]=="C01" and r["minimum_seconds"]==2 for r in rows)}
    return {"status":"probe_contract_valid" if all(v["passed"] for v in checks.values()) else "rule_rejected",
            "checks":checks,"automatic_retry":False,"semantic_approval":False}

def prepare(output_dir=OUT):
    cases=variants()
    for c in cases:
        schema=c["request"]["tools"][0]["function"]["parameters"]
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(EXPECTED)
    assert evaluate(EXPECTED)["status"]=="probe_contract_valid"
    parent=json.loads((PARENT/"state.json").read_text(encoding="utf-8"))
    spent=json.loads((DIAGNOSTIC/"RESULT.json").read_text(encoding="utf-8"))
    assert (parent["calls_started"],spent["effective_calls_started"],spent["remaining_calls"])==(21,24,0)
    reserve=sum(c["conservative_token_reservation"] for c in cases)
    plan={"schema":"minimax_small_context_rule_probe_plan/v3","status":"prepared_pending_new_call_budget",
          "paid_calls":0,"network_model_calls":0,"dispatch_enabled":False,
          "supersedes_unexecuted_preview":str(ROOT/"data/qa/minimax_rule_probe_20261003/matrix_v2/TEST_PLAN.json"),
          "model_parameters":PARAMETERS,"context_sha256":digest(CONTEXT),"context":CONTEXT,
          "messages_sha256":digest(cases[0]["request"]["messages"]),
          "all_messages_identical":all(c["request"]["messages"]==cases[0]["request"]["messages"] for c in cases),
          "sole_varied_request_part":"tools[0].function.parameters",
          "cases":cases,"expected_fixture":EXPECTED,
          "repeat_plan":{"first_round":list("ABCDEF"),"second_round":list("FEDCBA"),
                         "third_round":list("CDAFEB"),"max_new_calls_proposed":18,
                         "first_round_call_limit_alternative":6,"no_auto_retry":True},
          "conservative_tokens_all_18":reserve*3,
          "budget":{"parent_run":str(PARENT),"frozen_parent_calls":21,"effective_calls_started":24,
                    "current_max_calls":24,"current_reported_tokens":spent["effective_reported_tokens"],
                    "current_max_total_tokens":parent["max_total_tokens"],
                    "remaining_tokens":parent["max_total_tokens"]-spent["effective_reported_tokens"],
                    "new_max_calls_if_6_approved":30,"new_max_calls_if_18_approved":42,
                    "max_total_tokens_unchanged":True,"new_call_authorization":None,"old_budget_reset":False},
          "limits":["sample follows one synthetic context only; no production creative approval",
                    "one or three successes cannot prove strict server decoding",
                    "a complex-schema failure cannot distinguish unsupported keyword from model error without further evidence",
                    "no provider/model/endpoint/temperature change within this matrix",
                    "no picture/video/full screenplay generation; no DeepSeek review",
                    "source paths and task relation checks are evaluated separately from object/array shape",
                    "example values intentionally differ from the target to expose example copying"],
          "required_receipt_fields":["complete safe response envelope (content/reasoning/tool arguments)",
                                     "finish_reason","response_id","response_model","usage",
                                     "request_sha256","messages_sha256","schema_sha256",
                                     "outcome_unknown reservation (no free retry)"],
          "official_docs":{"openai":"https://platform.minimax.io/docs/api-reference/text-openai-api",
                           "anthropic":"https://platform.minimax.io/docs/api-reference/text-anthropic-api",
                           "finding":"tools are documented; strict/prefixItems/if-then support guarantee not found in pages read; absence is not proof of non-support"}}
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    def save(name,value):
        p=output_dir/name
        text=json.dumps(value,ensure_ascii=False,indent=2)
        if p.exists() and json.loads(p.read_text(encoding="utf-8"))!=value:
            raise RuntimeError("prepared experiment differs; preserve original and version explicitly")
        if not p.exists():p.write_text(text,encoding="utf-8")
    save("TEST_PLAN.json",plan)
    for c in cases:save("REQUEST_"+c["case_id"]+".json",c)
    return {"status":plan["status"],"cases":6,"paid_calls":0,"context_characters":len(canonical(CONTEXT)),
            "conservative_tokens_first_6":reserve,"conservative_tokens_all_18":reserve*3,
            "current_remaining_calls":0,"plan":str((output_dir/"TEST_PLAN.json").resolve())}

if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(prepare(),ensure_ascii=False,indent=2))
