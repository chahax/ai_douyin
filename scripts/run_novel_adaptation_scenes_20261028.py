"""New screenplay milestone; old card trials/unknown calls are never resumed."""
import sys
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation import scenes as sc
from src.content_factory.novel_adaptation.patching import bind_patches

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT/'data/corpus_production_trials/20261028_adaptation_cards_targeted'
RUN=ROOT/'data/corpus_production_trials/20261028_adaptation_scenes'
FACT_IDS=['E001','E004','E005','E006','E007','E008','E009','E011','E012','E013','E014','E017','E018','E019']
POLICY='''原文事实与影视设计分开。只改编第一章，完整前三章仅帮助理解身份和语境。
故事开场是穿书后的苏墨、二哥叶南和老六叶西决在屋内。完整本集覆盖第一章至双胞胎带菜回家，结尾留给下集，不提前演第二章。
人物称谓按上下文归属；说出口、内心、旁白分开。原书未来不能当当下或过去已发生事实。
快速传递人物关系和冲突，动作、神情和对白同步；平稳镜头与有动机的切换，避免静止等待与突然放大。
原文没写的陈设光线可作为adaptation_design，并保持统一；原文已给的因果、说话人、否定和条件不改。
NARRATOR仅音轨身份。道具实例区分于物类；源文提到面包不等于多人同时各持一块。'''


def main():
    global RUN
    continuation='--continue-design' in sys.argv
    prior_run=RUN
    if continuation:RUN=RUN.with_name(RUN.name+'_design_repair')
    RUN.mkdir(exist_ok=False)
    source=read(PARENT/'SOURCE.json');banks=read(PARENT/'AFTER.json')
    events=[r for r in banks['event']['facts'] if r['id'] in FACT_IDS]
    ids=set().union(*(set(r['entity_ids']) for r in events))|{'su-mo-bedroom','siblings-room'}
    entities={'entities':[r for r in banks['identity']['entities'] if r['id'] in ids]}
    # Primary review of these exact records against complete chapters. Unselected cards remain unreviewed.
    reviews={r['id']:{'verdict':'accepted','record_sha256':digest(r),'source_sha256':digest(source),'reviewer':'primary_assistant',
        'scope':'selected record meaning against original; not global material approval'} for r in entities['entities']+events}
    packet=sc.reviewed_packet(entities,{'event':{'facts':events}},{'choices':[]},sorted(ids),FACT_IDS,source,{},reviews)
    plan=read(PARENT/'PLAN.json');plan.update(max_calls=8,version='novel_adaptation/scenes-v1',source_sha256=digest(source))
    if continuation:
        prior=read(prior_run/'STATE.json')
        if prior['pending'] is not None or prior['status']!='needs_attention' or prior['calls_started']!=1:
            raise ValueError('continuation_requires_known_design_failure')
        plan['max_calls']=7
        freeze(prior_run/'BUDGET_TRANSFER.json',{'child':str(RUN),'original_bound':8,'used':1,'remaining':7})
        freeze(RUN/'DESIGN_BEFORE.json',read(prior_run/'DESIGN.json'))
    plan['inference']['writer_max_tokens']=32768
    freeze(RUN/'PLAN.json',plan);freeze(RUN/'SOURCE.json',source);freeze(RUN/'PACKET.json',packet)
    freeze(RUN/'RECORD_REVIEWS.json',reviews)
    freeze(RUN/'AUTHORIZATION.json',{'basis':'用户授权重构并持续开发真实小说MiniMax文本测试',
        'milestone':'first chapter complete episode across two rooms with state continuity',
        'max_calls':plan['max_calls'],'original_scene_bound':8,'scene_calls_previously_used':1 if continuation else 0,
        'card_trial_closed_separately':{'calls':7,'bound':8,'unused':1},
        'book_prior_starts':168 if continuation else 167,'prior_unknowns':2,'media':False,'publish':False})
    snapshot=RUN/'implementation';snapshot.mkdir()
    for path in [Path(__file__),Path(c.__file__),Path(sc.__file__),ROOT/'src/content_factory/serial_story_transport_v6.py']:
        (snapshot/path.name).write_bytes(path.read_bytes())
    state={'status':'prepared','calls_started':0,'reported_tokens':0,'pending':None}
    ledger=Ledger(RUN,plan,state,NativeClient(RUN,plan));ledger.save()
    try:
        payload={'complete_chapters':c.indexed_chapters(source),'reviewed_packet':packet}
        ps=sc.plan_schema(sorted(ids),FACT_IDS,[e['id'] for e in entities['entities'] if e['kind']=='character'])
        ps['properties']['scenes']['maxItems']=2
        if continuation:
            payload['prior_design_for_correction']=read(prior_run/'DESIGN.json')
            payload['design_defects']=['老六重复初态：初态只取本集开场，不混第二场状态',
                '当日/次日矛盾，第一章连续同日；白天先给钱再偷窃的先后无据',
                '铁床灯具布局年龄等设计不能冒充原文约束',
                '面包只在一次拿走动作交接，计划不得提前接住再拿走',
                '碘酒owner与描述桌上矛盾；同一初态保持一致',
                '世界框架不是整章复述；正向写视觉设计，不输出禁止项']
        design=ledger.call('DESIGN','writer',POLICY+'''
本次只做本集世界框架、美术设计和两场任务计划，不写分镜正文。
world_fact_ids选择已审核资料中交代穿书处境、原主背景和人物关系的必要ID；程序原样组装世界框架，不让本阶段重新改写事实。
visual_design只写画风/光线/布局/衣着等需要画出的设计内容，所有条目为adaptation_design；原文约束由程序从已审核资料原样附上，不列禁止项，不在设计描述里重新宣称原文明确写了什么。
places若description混入新增陈设和连接方位，一律basis=adaptation_design，source仅用于纯原文地点说明。
两场总时长约150秒，第一场苏墨卧室，第二场另一间屋子；完整覆盖第一章主要冲突。
initial_locations对象固定7个角色键，是本集开场位置：老六在苏墨卧室，叶东叶嫣儿在另一间屋，双胞胎在外。
places包含房间和必要的场外过渡位置，新增连接空间标adaptation_design；不要把居住分配写成原文事实。
props登记实际需要表演的关键物品实例，至少包含路人赠予的面包、碘酒瓶、菜袋，明确开场持有人。若对白需要出示钱，也登记钱的实例；拒收不发生交接。不要为了省状态而让人物伸空手给钱。
每场fact_ids只列所需事实，角色初态须支持后续进出动作。''',payload,ps)
        errors=c.schema_issues(design,ps,'design')
        if errors:raise c.ContractError(errors)
        design=sc.compile_design(design,packet)
        freeze(RUN/'DESIGN_COMPILED.json',design)
        previous=sc.initial_state(design,entities);completed=[]
        payload.pop('prior_design_for_correction',None);payload.pop('design_defects',None)
        freeze(RUN/'INITIAL_STATE.json',previous)
        for spec in design['scenes']:
            schema=sc.scene_schema(design,entities,FACT_IDS,source)
            selected_packet=sc.reviewed_packet(entities,{'event':{'facts':events}},{'choices':[]},
                sorted(ids),spec['fact_ids'],source,previous,reviews)
            scene_payload={'complete_chapters':c.indexed_chapters(source),'reviewed_packet':selected_packet}
            prompt=POLICY+'''
只输出指定当前场次。每个beat为连续3—15秒，start/end从本场0连续至指定duration_seconds。
动作与神情具体可表演。audio写实际台词和本场绝对起止秒，一次一条清楚音轨，汉字每秒不超过6。
inner是角色内心，dialogue才是说出的话，narration用NARRATOR。
moves在本beat开头发生，明确起点/终点及可见动作；本beat剩余动作与对白发生在移动之后。
在场名单由程序根据前态与moves计算，无需重复填写present。离场应单列短beat，离场者不要在该beat再说话。
transfers在人物移动后发生，明确道具原持有者及新持有者，拿走已有物品不可重新生成同类实例。
人拿着物品走到另一屋时持有者不变，只写moves；transfers只表示放下、拿起、交给等实际持有者变化。
同场最后一beat结束仍在屋内的人自动延续，切镜不等于离场。来源未交代的连接动作用adaptation_detail说明。
fact_ids引用资料；source_ids可直接引用原文必要细节。台词保留原文归属，不加入场外人物的现场回答。
每beat附画面信息与情绪，不用负面限制句充当画面内容。'''
            scene=ledger.call('SCENE_'+spec['id'],'writer',prompt,{**scene_payload,'design':design,
                'current_scene':spec,'previous_state':previous,'previous_completed_scene':completed[-1] if completed else None},schema)
            try:ending=sc.advance(scene,spec,design,entities,FACT_IDS,source,previous)
            except c.ContractError as exc:
                # Repair only addressed beats, including adjacent boundary beats if timing is implicated.
                freeze(RUN/(spec['id']+'_ISSUES.json'),[asdict(x) for x in exc.issues])
                indexes=set()
                for issue in exc.issues:
                    parts=issue.path.strip('/').split('/')
                    if len(parts)<2 or parts[0]!='beats' or not parts[1].isdigit():raise
                    indexes.add(int(parts[1]))
                allowed={scene['beats'][i]['id'] for i in indexes}
                rows=[r for r in scene['beats'] if r['id'] in allowed]
                patch_schema=c.obj(patches=c.array(c.obj(id=c.choices(sorted(allowed)),
                    replacement=schema['properties']['beats']['items']),1))
                proposal=ledger.call('PATCH_'+spec['id'],'writer',prompt+'只修改指定beats，保留id和未选字段；不得重写整场。',
                    {**scene_payload,'design':design,'current_scene':spec,'previous_state':previous,'candidate':scene,
                     'issues':[asdict(x) for x in exc.issues],'allowed_records':[{'record':r,'sha256':digest(r)} for r in rows]},patch_schema)
                errs=c.schema_issues(proposal,patch_schema,'patch')
                if errs:raise c.ContractError(errs)
                scene=c.apply_record_patches(scene,bind_patches(scene,proposal['patches'],allowed,digest(scene)),allowed,digest(scene),
                    lambda value:sc.advance(value,spec,design,entities,FACT_IDS,source,previous))
                ending=sc.advance(scene,spec,design,entities,FACT_IDS,source,previous)
            freeze(RUN/(spec['id']+'_FINAL.json'),scene);freeze(RUN/(spec['id']+'_END_STATE.json'),ending)
            completed.append(scene);previous=ending
        candidate={'design':design,'scenes':completed,'end_state':previous}
        freeze(RUN/'EPISODE.json',candidate)
        review_schema=c.obj(verdict=c.choices(['pass','revise','uncertain']),issues=c.array(c.obj(
            scene_id=c.TEXT,beat_id=c.TEXT,problem=c.TEXT,source_ids=c.refs(c.catalog(source)),severity=c.choices(['must_fix','suggestion','uncertain']))))
        review=ledger.call('REVIEW','writer',POLICY+'独立核对原文与完整候选，检查事实、世界框架、人物关系、进出与持物、对白归属和时长。不要沿用任何旧审核结论；审核不修改稿件。',
            {'complete_chapters':c.indexed_chapters(source),'candidate':candidate,'candidate_sha256':digest(candidate)},review_schema)
        errors=c.schema_issues(review,review_schema,'review')
        if errors:raise c.ContractError(errors)
        state['status']='episode_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(RUN/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()

if __name__=='__main__':main()
