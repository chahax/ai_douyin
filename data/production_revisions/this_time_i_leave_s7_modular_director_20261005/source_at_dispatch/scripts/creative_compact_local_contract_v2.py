"""One state operation per authored group; strict projection, never content repair."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from scripts import creative_compact_local_contract_v1 as prior
VERSION="single_operation_local_performance_contract/v2"
RULES="""只为当前镜提交完整局部表演，保持完整原steps/对白及真实首态。根对象只有dialogue_performance与actions；每action只有source_step_ref/groups，按原action先后恰好一次。原对白由程序完整插入，不进actions。
每group恰五键：seconds正秒数、subject人物ID、performance自然可见表演、operation、satisfies数组。operation只能为null或一个四键对象：kind/actor/target/value，不是数组，不是operations，不加其他字段。每组最多一个状态操作，相继组读取前组已完成尾态；take与place必须分属前后组。operation=null表示该人物维持已有状态的可读表演，不藏未记录的状态变化、不机械空等。
操作kind枚举move/gaze/affect/sit/stand/take/place/pass/slide/face。gaze/face/affect/move/stand的target为空字符串，实际目标写非空value；take/place/pass/slide的target是道具ID，value是非空持有位置/落点/对方ID。slide只能同一支持面，value为surface:支持面ID:区域；take要求无人持有，place/pass要求actor已持有。move是人物整体位置，不是伸手或持笔手移动；微细手/笔画写performance且不改变持有。人物侧身/目光改变必须分别记录face/gaze。
satisfies只在operation=null且subject正确的真实反应组填写当前before/after要求ID，最低秒数给足，每项一次。during由程序绑定整句对白，不填satisfies。无对白dialogue_performance也须非空，写本镜无对白；有对白仅语气/面部/呼吸，不藏拿放/移步，不增删原台词。不输出总秒数、ID、SHA、分镜或补丁。程序确定性生成这些字段，所有内容完整重交。"""


def build_schema(inp):
    result=deepcopy(prior.build_schema(inp));result["description"]=RULES
    group=result["properties"]["actions"]["items"]["properties"]["groups"]["items"]
    del group["properties"]["operations"]
    chars=[c["id"] for c in inp["context"]["static_visual_manifest"]["characters"]]
    group["properties"]["operation"]={"anyOf":[{"type":"null"},{"type":"object","properties":{"kind":{"enum":["move","gaze","affect","sit","stand","take","place","pass","slide","face"]},"actor":{"enum":chars},"target":{"type":"string"},"value":{"type":"string","minLength":1}},"required":["kind","actor","target","value"],"additionalProperties":False}]}
    group["required"]=["seconds","subject","performance","operation","satisfies"]
    return result


def build_messages(inp):
    return [{"role":"system","content":RULES},{"role":"user","content":json.dumps({"read_only_complete_source_direction_and_start_state":inp,"output_contract":VERSION},ensure_ascii=False,separators=(",",":"))}]


def derive_local(doc,inp):
    Draft202012Validator(build_schema(inp)).validate(doc)
    projected=deepcopy(doc)
    for action in projected["actions"]:
        for group in action["groups"]:
            op=group.pop("operation")
            group["operations"]=[] if op is None else [[op[k] for k in ("kind","actor","target","value")]]
    # Existing physical field conditions, source/window coverage and durations remain strict.
    # No operations, performances, times or source refs are invented, removed or repaired.
    return prior.derive_local(projected,inp)
