"""New explicit review transport: bounded named-tool envelope, lossless v8 payload.

The ordinary tool schema helps shape output. It does not claim strict server
JSON decoding or replace full v7/v9 business and evidence validation.
"""
from copy import deepcopy
import json
from scripts import creative_compact_review_transport_v8 as compact
from scripts import creative_joint_source_binding_v9 as joint

VERSION='creative_review_wire/v9'


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
    return messages


def joint_messages(ctx,messages,source_addendum=None):
    joint.preflight(ctx)
    result=deepcopy(messages)
    if len(result)<2 or result[0].get('role')!='system':raise ValueError('complete joint messages required')
    result[0]['content']+='\n'+format_addendum(ctx)+'\n'+(source_addendum or joint.build_messages_addendum(ctx))
    return result
