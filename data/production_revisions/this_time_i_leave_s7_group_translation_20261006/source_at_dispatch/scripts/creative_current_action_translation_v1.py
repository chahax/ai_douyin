"""Mechanical current-action translation only; references consumed by creative stages."""
from copy import deepcopy
import json
from scripts.creative_atomic_event_lines_v1 import VERSION
from scripts import creative_local_event_performance_v3 as split

def messages(inp,feedback):
 focus=split.focus(inp);ctx=inp['context'];payload={'role':'mechanical_state_translation_only','current_complete_source':focus,'spatial_contract':deepcopy(inp['direction']['spatial_contract']),'registered_characters':[{k:v for k,v in c.items() if k in ('id','name')} for c in ctx['static_visual_manifest']['characters']],'registered_prop_ids':[p['id'] for p in ctx['static_visual_manifest']['props']],'source_binding':{'raw_script_sha256':ctx.get('raw_script_sha256'), 'raw_source_full_creative_stages':161,'complete_direction_source_consumed_R01':187},'verified_faults':feedback or {}}
 rule=VERSION+'。你只翻译已经确定的当前原动作，不创作剧情、不考虑审美，不添加动作或台词。输出七列事件行：slot|subject|kind|target|value|satisfies|intent。动作组只按当前source里action的0起索引，E从0连续十进制（E10而非EA），每行七列。kind只有hold/gaze/face/move/stand/sit/take/place/pass/slide。hold的target/value都是-；gaze/face/move的target为-、value为实际目标或位置；道具操作target道具ID、value实际位置。satisfies无窗口为-，有窗口填要求ID；人物ID也就是操作者。写字/呼吸/握着笔的手腕动作hold，不站起/重拿笔。所有原action完整、状态变化各一行，不能藏于hold。不要JSON、工具调用、表格标题、围栏、编号解释。'
 payload['format_examples_only']=['A0E0|C02|gaze|-|at_E02_P05|-|看向原明细单','A0E1|C02|hold|-|-|-|原右手持笔落字','A0E3|C02|slide|P06|surface:E02:beside_P05|-|拉齐原结算单','A0E10|C02|hold|-|-|-|继续原动作']
 return [{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]

def validate_consumed(inp,request,raw_sha,ref_sha):
 payload=json.loads(request['messages'][1]['content']);focus=split.focus(inp)
 if payload['current_complete_source']!=focus or payload['spatial_contract']!=inp['direction']['spatial_contract']:raise ValueError('current source/state/requirements changed or omitted')
 binding=payload['source_binding'];binding.update(raw_script_sha256=raw_sha,reference_pack_sha256=ref_sha)
 # Bound digests accompany exact source subset; full references remain in actual creative requests.
 return {'complete_current_original_and_real_start_consumed':True,'current_only_mechanical_translation':True,'upstream_creative_R01_ordinals':[161,187],'full_reference_in_this_translation':False,'raw_script_sha256':raw_sha,'reference_pack_sha256':ref_sha}
