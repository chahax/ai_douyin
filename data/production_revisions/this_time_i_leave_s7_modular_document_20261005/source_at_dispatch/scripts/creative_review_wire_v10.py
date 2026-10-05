"""New explicit review transport: bounded named-tool envelope, lossless v8 payload.

The ordinary tool schema helps shape output. It does not claim strict server
JSON decoding or replace full v7/v9 business and evidence validation.
"""
from copy import deepcopy
import json
from scripts import creative_compact_review_transport_v8 as compact
from scripts import creative_joint_source_binding_v10 as joint
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION='creative_review_wire/v10'


def schema(ctx):
    compact._rows(ctx)
    text={'type':'string'}
    refs={'type':'array','items':{'type':'array','minItems':2,'maxItems':2,'items':deepcopy(text)},
          'description':'Each item is exactly [path,quote]; path is a real dot-separated scalar leaf in the full input, with script. or shots. prefix.'}
    issue_fields={k:deepcopy(text) for k in sorted(compact.ISSUE_FIELDS) if k!='evidence_refs'}
    issue_fields['evidence_refs']=deepcopy(refs)
    issue_fields['owner']={'type':'string','enum':['writer','director']}
    issue_fields['severity']={'type':'string','enum':['blocking','major']}
    obj=lambda props:{'type':'object','additionalProperties':False,'required':list(props),'properties':props}
    return obj({'schema':{'type':'string','enum':[compact.VERSION]},
        'context_sha256':{'type':'string','enum':[compact.context_digest(ctx)]},
        'story_preserved':{'type':'boolean'},'issues':{'type':'array','items':obj(issue_fields)},
        'suggestions':{'type':'array','items':obj({k:deepcopy(text) for k in ('location','proposal','reason')})},
        'calibration_focus':{'type':'array','items':deepcopy(text)},
        'coverage':{'type':'array','items':{'type':'array','minItems':7,'maxItems':7,'items':{}},
          'description':'Every row is an ARRAY [id,requirements,timing,continuity,dialogue_timing,first_frame,assets]. Every check is ARRAY [status,reason,[[path,quote],...],[issue_id,...]]. Never {id,checks} objects.'}})


def format_addendum(ctx):
    ids=compact._rows(ctx)
    check=['pass|fail|not_applicable','具体核对理由',[['输入完整点分叶子路径','逐字引用']],['仅fail的已列真实issue_id']]
    example=['实际正文编号']+[deepcopy(check) for _ in range(6)]
    return ('本次使用submit_creative_json提交一次完整结果。唯一输出合同是工具Schema及下列无损v8结构；不返回分析。'
      'coverage每行是七列普通数组，六检查也都是四列数组，绝不输出{id,checks}。仅结构示例，示例编号/占位词不可写入真实结果：'
      +json.dumps(example,ensure_ascii=False,separators=(',',':'))
      +'\n实际必须一次覆盖全部编号：'+json.dumps(ids,ensure_ascii=False)
      +'。实际叶子示例根前缀script.beats.0.before或shots.shots.0.start_state；不能写beats[0]、省略script根或引数组对象。'
       '无对白检查可not_applicable且evidence_refs=[]，不能引用dialogue数组。其他需哪些正文/前拍/执行证据按审查规则。'
       '证据只引用实际相关逐字短片段，reason写核对理由，勿复述全部原稿，不删真实issue或默认通过以节省输出。')


def script_messages(ctx):
    messages=compact.build_review_messages(ctx)
    messages[0]['content']+='\n'+format_addendum(ctx)
    if ctx.get('script_timing_status')=='preliminary_budget_not_actual':
        messages[0]['content']+='\n本阶段script的duration_seconds由程序给出初步预算，仅用于旧接口形状；尚无局部表演及真实执行窗口。timing/dialogue_timing可核对对白文字下界与先后，但不得把预算当实际表演通过，不编造秒点证据。timing检查继续逐拍审刺激→对白→反应的源顺序，不能not_applicable；没有真实执行窗口时dialogue_timing应not_applicable，reason说明尚未局部编排、evidence_refs=[]、issue_ids=[]。不得把程序预算写成实际语速/反应窗口通过。实际对白前中后窗口及源动作兑现须在后续整片联合审查重新全文核对；本次只批准正文进入导演安排。'
    return messages


def joint_messages(ctx,messages,source_addendum=None):
    joint.preflight(ctx)
    result=deepcopy(messages)
    if len(result)<2 or result[0].get('role')!='system':raise ValueError('complete joint messages required')
    result[0]['content']+='\n'+format_addendum(ctx)+'\n'+(source_addendum or joint.build_messages_addendum(ctx))
    return result


def validate_script_review(raw,ctx):
    """No delivery-timing approval can be manufactured from preliminary budgets."""
    review=compact.expand_review(raw,ctx)
    if ctx.get("script_timing_status")=="preliminary_budget_not_actual":
        for index,row in enumerate(review["coverage"]):
            if row["checks"]["dialogue_timing"]["status"]!="not_applicable":
                exc=CreativeContractError("SCRIPT_ACTUAL_TIMING_UNAVAILABLE: script has no actual local delivery windows")
                exc.detail={"code":"SCRIPT_ACTUAL_TIMING_UNAVAILABLE","path":f"coverage.{index}.checks.dialogue_timing",
                            "complete_review_required":True,"automatic_retry":False,"blocks_handoff":True}
                raise exc
    return review
