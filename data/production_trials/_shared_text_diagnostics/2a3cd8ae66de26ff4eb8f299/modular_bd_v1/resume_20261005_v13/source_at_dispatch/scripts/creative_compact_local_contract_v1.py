"""Small creative local contract; compiler owns identities, slots and total duration."""
from copy import deepcopy
from jsonschema import Draft202012Validator
from scripts import step_index_physical_adapter_v5 as base
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import _speech_units
import json
VERSION='compact_local_performance_contract/v1'
RULES='''只为当前镜生成完整局部表演，保持原steps、原对白、真实首态。采用本次compact合同，不能输出旧step_units/groups的字段。输出只有dialogue_performance和actions两字段。actions按当前镜kind=action的原步骤依次恰好一次，每项source_step_ref和groups。原dialogue不用重说、不进入actions，程序插原句。
每group只有seconds,subject,performance,operations,satisfies五字段。seconds是本组相继执行所需正秒数；subject是观察人物。operations为空数组时表示此人物保持已成立状态；非空时表示真实操作。只为真正有信息的建立或原文反应留hold，不重复保持未动的每个道具，不机械加等待。动作必须完整覆盖原文。
每operation是严格四列数组[kind,actor,target,value]，不写对象，不加action_ref、semantic_role或其它字段。kind枚举move/gaze/affect/sit/stand/take/place/pass/slide/face。gaze/face/affect/move/stand的第三列target为空字符串，目标或状态写第四列；take/place/pass第三列是移动道具ID；sit第三列是固定椅ID；slide第三列道具ID，第四列surface:支持面ID:区域。holder=none才可take/slide，place/pass要求当前持有；slide不能跨支持面。无变化的微细手指、落笔、呼吸写performance，不伪造道具转手或起坐。物理位移/持有/视线/朝向必须写真实operation。
satisfies只在真正可读的保持组里列当前镜after/before反应要求ID，每项恰好一次；subject须对应要求人物，seconds给足最低时间。same-dialogue during由程序自动绑定原整句对白，不放入satisfies，不增加动作组冒充说话表演。对白期间面部、呼吸、情绪只写dialogue_performance，不藏拿放移动。
组ID、输入SHA、动作/保持类型、源action_ref、对白单元、对白正常语速及总镜长由程序确定性生成。不要输出这些字段，不自行计算多个并行组或总镜长。所有groups按原文相继执行，无动作对白并行，不新增剧情、对白、角色或资产。返回Schema完整目标，不交补丁。'''

def obj(p):return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}

def build_schema(inp):
    ctx=inp['context'];shot=next(s for s in base._shots(inp['direction']) if s['shot_id']==inp['shot_id']);sources=base._raw_sources(ctx)
    refs=[r for r in shot['source_step_refs'] if sources[r]['kind']=='action'];chars=[x['id'] for x in ctx['static_visual_manifest']['characters']]
    props=[x['id'] for x in ctx['static_visual_manifest']['props']];elements=[x['id'] for x in ctx['static_visual_manifest']['scene']['elements']]
    op={'type':'array','minItems':4,'maxItems':4,'prefixItems':[{'enum':['move','gaze','affect','sit','stand','take','place','pass','slide','face']},{'enum':chars},{'type':'string'},{'type':'string','minLength':1}], 'items':False}
    op['allOf']=[{'if':{'prefixItems':[{'enum':['move','gaze','affect','stand','face']}]},'then':{'prefixItems':[{}, {},{'const':''}]}},
      {'if':{'prefixItems':[{'enum':['take','place','pass','slide']}]},'then':{'prefixItems':[{}, {},{'enum':props}]}},
      {'if':{'prefixItems':[{'const':'sit'}]},'then':{'prefixItems':[{}, {},{'enum':elements}]}},
      {'if':{'prefixItems':[{'const':'pass'}]},'then':{'prefixItems':[{}, {},{}, {'enum':chars}]}}]
    requirements=[q['id'] for q in shot['performance_requirements'] if q['relation']!='during']
    group=obj({'seconds':{'type':'number','exclusiveMinimum':0},'subject':{'enum':chars},'performance':{'type':'string','minLength':1},'operations':{'type':'array','items':op},'satisfies':{'type':'array','uniqueItems':True,'items':{'enum':requirements}}})
    result=obj({'dialogue_performance':{'type':'string','minLength':1},'actions':{'type':'array','minItems':len(refs),'maxItems':len(refs),'items':obj({'source_step_ref':{'enum':refs},'groups':{'type':'array','minItems':1,'items':group}})}})
    result['description']=RULES;return result

def build_messages(inp):
    return [{'role':'system','content':RULES},{'role':'user','content':json.dumps({'read_only_complete_source_direction_and_start_state':inp,'output_contract':VERSION},ensure_ascii=False,separators=(',',':'))}]

def derive_local(doc,inp):
    Draft202012Validator(build_schema(inp)).validate(doc)
    ctx=inp['context'];shot=next(s for s in base._shots(inp['direction']) if s['shot_id']==inp['shot_id']);sources=base._raw_sources(ctx)
    expected=[r for r in shot['source_step_refs'] if sources[r]['kind']=='action']
    if [a['source_step_ref'] for a in doc['actions']]!=expected:base.fail('COMPACT_SOURCE_COVERAGE','全部原action恰好一次、按序覆盖')
    actions={a['source_step_ref']:a for a in doc['actions']};units=[];windows=[];seconds=0.;dialogue_index=0
    reqs={q['id']:q for q in shot['performance_requirements']};assigned=[]
    for ref in shot['source_step_refs']:
        if sources[ref]['kind']=='dialogue':
            units.append({'source_step_ref':ref,'groups':[],'dialogue_ref':ref})
            seconds+=max(1.,_speech_units(sources[ref]['text'])/3.5+0.3)
            for q in reqs.values():
                if q['relation']=='during' and q['reaction_ref']==ref:
                    windows.append({'requirement_id':q['id'],'anchor':'dialogue_'+str(dialogue_index)});assigned.append(q['id'])
            dialogue_index+=1;continue
        groups=[]
        for gi,g in enumerate(actions[ref]['groups']):
            gid=f'{shot["shot_id"]}-A{shot["source_step_refs"].index(ref):02}-G{gi:02}'
            ops=[dict(zip(('kind','actor','target','value'),op)) for op in g['operations']]
            groups.append({'id':gid,'kind':'action' if ops else 'hold','duration_seconds':g['seconds'],'hold_subject':'' if ops else g['subject'],
              'performance':g['performance'],'operations':ops,'action_ref':ref,'semantic_role':'reaction' if g['satisfies'] else 'action'})
            seconds+=g['seconds']
            for rid in g['satisfies']:
                q=reqs[rid]
                if ops or q['reaction_ref']!=ref or q['subject']!=g['subject']:base.fail('COMPACT_WINDOW_BINDING','要求须标在正确原反应的指定人物保持组',rid)
                windows.append({'requirement_id':rid,'anchor':gid});assigned.append(rid)
        units.append({'source_step_ref':ref,'groups':groups,'dialogue_ref':None})
    if len(set(assigned))!=len(assigned) or set(assigned)!=set(reqs):base.fail('COMPACT_WINDOW_COVERAGE','全部要求恰好绑定一次')
    local={'schema':base.LOCAL,'shot_id':inp['shot_id'],'input_sha256':digest(inp),'duration_seconds':seconds,
      'dialogue_performance':doc['dialogue_performance'],'step_units':units,'performance_windows':windows}
    base._validate(local,base._local_schema(ctx,inp['direction'],inp['shot_id'],digest(inp)))
    return local
