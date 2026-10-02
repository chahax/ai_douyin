"""Isolated MiniMax content probe; never changes production routing or budgets."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.content_factory.creative_workflow_roles import CreativeRoleClients, role_config
from src.content_factory.creative_workflow_contract import WRITER_TOOL_SCHEMAS, parse_json_object, validate_script, validate_shots, compile_beat_screenplay
from src.content_factory.creative_media_capability import audit_creative_executor
from src.content_factory.creative_workflow_inputs import file_binding, verify_binding
from src.content_factory.reusable_production import read, write, asset_catalog, validate_design, route_assets, DESIGN_PROMPT

def obj(fields):
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
def arr(item):return {'type':'array','items':item}
S={'type':'string'}
SHOT_SCHEMA=obj({**{k:S for k in ('id','beat_id','purpose','composition','camera','visible_performance','event_lock','start_state','end_state','cut_reason','prompt')},
 'duration_seconds':{'type':'integer'},'dialogue_lock':arr(obj({'speaker':S,'text':S})),
 'dialogue_mode':{'type':'string','enum':['画内','画外','画内/画外','无对白']},
 'continuity_mode':{'type':'string','enum':['raw_tail_continuation','planned_cut_requires_adapter']},'production_choices':arr(S)})
DIRECTOR_SCHEMA=obj({'style':obj({k:S for k in ('style_option_id','visual_medium','palette','spatial_layout','character_lock','light_source')}),'shots':arr(SHOT_SCHEMA)})
WRITER_PROMPT='''你担任编剧。依据创作简报生成可拍的原创短片剧本，只提交指定工具JSON。人物与关系变化必须具体、可信，保留克制而可读的表演。
本次固定候选ID为C01，5个节拍按B01、B02、B03、B04、B05完整返回，合计70—100秒，duration_seconds等于各拍之和。每拍必须包含id/duration_seconds/event/trigger/before/during/after/dialogue；dialogue永远是数组，没有对白用[]。
陈默与林屿是疏远的老朋友，可使用已审人物资产；场景为日间画室。对方记得不起眼的细节使戒备动摇，结尾用主动动作让对方留下，不靠总结台词。
每拍before是第一句之前，during是对白之间可见反应，after是全部对白之后；不要把听到本拍台词后的反应写到before。对白只写在dialogue中，动作字段不复述说话，不以微动作堆叠假装情绪。重要句前、中、后留反应时间，收尾简短。
全程追踪画笔、调色板、画架、凳子的位置、持物手与支撑；换手或放下须有动作承接。不用假想的手机字。人物外观、门窗方向服从asset_observations，不把未知空间写成已证实。不得照抄故事以外的例子。'''
DIRECTOR_PROMPT='''你担任导演。只根据已锁定script制作分镜，只提交指定工具JSON，不改故事、事件、对白、说话人及顺序。style_option_id固定S01。
完整覆盖全部节拍，镜号唯一。每拍镜头时长之和必须精确等于该拍时长，每镜整数秒且满足executor_constraints范围。长节拍必须真实拆镜，不要把23秒塞进单镜，也不要将总节拍压短。每镜最多5字/秒且为动作及反应留时间，不让其他镜头替有对白镜头抵扣时长。
event_lock逐字复制所属节拍event。dialogue_lock按script逐句原样分配，每句恰好出现一次。画内时说话人应入画；画外时明确声音属于谁、听者不对口型；同镜混合才用画内/画外，无对白用无对白。构图、表演、prompt与模式一致。
start_state是尚未发生本镜动作的瞬间，end_state是结束结果；与相邻镜状态相容。raw_tail_continuation只用于与上镜原尾直接接续，start_state需逐字等于上镜end_state；切换机位用planned_cut_requires_adapter，不伪称已适配。
全程明确道具支撑和空闲手，不能让物品消失，不能把编剧已放下的物品继续写成手持。参考asset_observations描述布局，不虚构另一扇窗或无遮挡通道。选实际能同时容纳主体的景别，不能近景同时拍清脸和脚。
每镜说明新增信息、重点反应及为何切走；关键句的刺激与反应要对应，删去没有叙事功能的停顿须回报上游而非擅自改时长。prompt描述本镜实际动作，不重复上一镜对白。'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    run=args.run_dir.resolve();run.mkdir(parents=True,exist_ok=True)
    sources={'brief':ROOT/'data/production_trials/reusable_20260927/brief.json','library':ROOT/'data/visual_asset_library/reusable_assets.json','observations':ROOT/'data/production_trials/reusable_20260927/ASSET_VISUAL_OBSERVATIONS.json'}
    bindings={k:file_binding(p) for k,p in sources.items()}
    observations=read(sources['observations'])
    for row in observations['assets']:verify_binding(row['image'])
    scope={'schema':'minimax_independent_content_probe/v1','authorization':'可以独立测试minimax模型生成内容吧','source_bindings':bindings,'max_calls':3,'automatic_repair':False,'media_submit':False,'production_routing_changed':False,'old_production_budget_unchanged':True,'comparison':'same creative brief, simplified prompts; not a controlled model-only A/B comparison'}
    if (run/'SCOPE.json').exists():
        if read(run/'SCOPE.json')!=scope:raise RuntimeError('输入绑定改变，不可复用该测试目录')
    else:write(run/'SCOPE.json',scope)
    config=role_config('writer')
    if config.provider!='minimax' or config.model!='MiniMax-M3':raise RuntimeError('仅允许配置的MiniMax-M3')
    client=CreativeRoleClients()
    records=[]
    def call(stage,logical_role,prompt,payload,schema=None):
        path=run/(stage+'.json')
        messages=[{'role':'system','content':prompt+'\n只提交JSON；有工具时使用submit_creative_json。'},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
        request={'messages':messages,'schema':schema,'max_tokens':12000,'temperature':0.2,'thinking':'disabled'}
        if path.exists():
            receipt=read(path)
            if receipt['request']!=request:raise RuntimeError(stage+'请求已变，禁止覆盖')
            if receipt['status']!='response_received':raise RuntimeError(stage+'调用状态未确认，禁止重发')
        else:
            if len(list(run.glob('0*.json')))>=3:raise RuntimeError('独立测试调用上限')
            receipt={'logical_role':logical_role,'transport_config_role':'writer','provider':config.provider,'model':config.model,'status':'pending_response','started_at':datetime.now(timezone.utc).isoformat(),'request':request}
            write(path,receipt)
            print('Calling '+stage+' '+logical_role,flush=True)
            try:
                result=client.call('writer',messages,max_tokens=12000,temperature=0.2,thinking='disabled',structured_schema=schema)
            except Exception as exc:
                receipt.update(status='failed_or_uncertain',error=str(exc));write(path,receipt);raise
            receipt.update(status='response_received',response_text=result.text,response_metadata=result.metadata,completed_at=datetime.now(timezone.utc).isoformat());write(path,receipt)
        records.append(file_binding(path))
        if receipt['response_metadata'].get('finish_reason')=='length':raise RuntimeError(stage+'输出截断')
        return parse_json_object(receipt['response_text'])
    summary={'schema':'minimax_independent_content_result/v1','stages':{},'actual_media_quality_pass':False,'automatic_submit':False,'receipts':records}
    def validate(stage,fn):
        try:fn();summary['stages'][stage]={'contract':'passed','semantic_review':'pending'};return True
        except (ValueError,KeyError,TypeError) as exc:summary['stages'][stage]={'contract':'failed','error':str(exc)};return False
    catalog=asset_catalog(sources['library'])
    facts=[{'reuse_key':r['reuse_key'],'observed':r['observed']} for r in observations['assets']]
    audit=audit_creative_executor({'shots':[]});limits={k:audit[k] for k in ('provider','model','duration_min','duration_max','evidence')}
    common={'creative_brief':read(sources['brief']),'asset_catalog':catalog,'asset_observations':facts,'executor_constraints':limits}
    try:
        schema=deepcopy(WRITER_TOOL_SCHEMAS['writer_script']);schema['properties']['beats'].update(minItems=5,maxItems=5)
        writer=call('01_writer','writer',WRITER_PROMPT,common,schema)
        script=deepcopy(writer);script['screenplay_markdown']=compile_beat_screenplay(writer)
        write(run/'SCREENPLAY.json',script);(run/'SCREENPLAY.md').write_text(script['screenplay_markdown'],encoding='utf-8')
        def writer_check():
            if [b['id'] for b in script['beats']]!=['B01','B02','B03','B04','B05']:raise ValueError('节拍缺失或错序')
            if not 70<=sum(b['duration_seconds'] for b in script['beats'])<=100:raise ValueError('总时长不在简报范围')
            if sum(b['duration_seconds'] for b in script['beats'])!=writer['duration_seconds']:raise ValueError('声明时长不等于合计')
            validate_script(deepcopy(script),'C01','','original')
        if not validate('writer',writer_check):return
        shots=call('02_director','director',DIRECTOR_PROMPT,{**common,'script':script},DIRECTOR_SCHEMA)
        write(run/'STORYBOARD.json',shots)
        def director_check():
            validate_shots(shots,{'selected_style_id':'S01'},script)
            for beat in script['beats']:
                if sum(s['duration_seconds'] for s in shots['shots'] if s['beat_id']==beat['id'])!=beat['duration_seconds']:raise ValueError('节拍时长不精确一致: '+beat['id'])
            for shot in shots['shots']:
                if type(shot['duration_seconds']) is not int or not limits['duration_min']<=shot['duration_seconds']<=limits['duration_max']:raise ValueError('镜头时长超限: '+shot['id'])
        if not validate('director',director_check):return
        design=call('03_design','production_designer',DESIGN_PROMPT+'\n实际首帧必须是start_state的静态投影，不能预先完成动作。复用必须满足真实要求，不删除服装等约束以强行命中；不得凭空增加必需检索标签。',{**common,'script':script,'storyboard':shots})
        write(run/'PRODUCTION_DESIGN.json',design)
        if validate('design',lambda:validate_design(design,shots,catalog)):
            write(run/'ASSET_ROUTES.json',route_assets(design,read(sources['library'])))
    finally:
        summary['receipts']=records
        summary['calls_with_responses']=len(records)
        summary['reported_tokens']=sum(read(Path(r['path']))['response_metadata'].get('total_tokens',0) for r in records)
        write(run/'RESULT.json',summary)
        print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
