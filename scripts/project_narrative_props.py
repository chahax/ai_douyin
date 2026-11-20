"""Real critical-prop projection; preserve prose and replay shared state engine."""
import argparse
import hashlib
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c,narrative_props as props
from src.content_factory.novel_adaptation.presence_evidence import catalog
from src.content_factory.novel_adaptation.narrative_presence import replay,error_record
from src.content_factory.novel_adaptation.scenes import initial_state
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient


def registry_schema(people,places,source):
    def recipe(kind):
        return c.obj(id=c.TEXT,kind=c.choices([kind]),action=c.TEXT,inputs=c.array(c.TEXT,1),
            outputs=c.array(c.TEXT,1) if kind=='transformation' else {'type':'array','items':False,'maxItems':0},
            retained_inputs=c.array(c.TEXT) if kind=='transformation' else {'type':'array','items':False,'maxItems':0},
            source_ids=c.refs(c.catalog(source)))
    return c.obj(props=c.array(c.obj(id=c.TEXT,owner=c.choices(people+places),
        description=c.TEXT,initial_status=c.choices(['present','planned','consumed'])),1),
        initial_containers=c.array(c.obj(child=c.TEXT,container=c.TEXT)),
        recipes=c.array({'oneOf':[recipe('transformation'),recipe('consumption')]}),uncertainties=c.array(c.TEXT))


def validate_initial_containers(registry):
    """Reject future containment instead of discarding it or guessing a repair."""
    by={row['id']:row for row in registry['props']}
    if len(by)!=len(registry['props']):raise ValueError('duplicate_prop_id')
    errors=[];seen=set()
    for row in registry['initial_containers']:
        child,parent=row['child'],row['container']
        if child in seen:errors.append(f'duplicate_container_child:{child}')
        seen.add(child)
        if child not in by or parent not in by:
            errors.append(f'unknown_container_endpoint:{child}:{parent}');continue
        if by[child]['initial_status']!='present' or by[parent]['initial_status']!='present':
            errors.append(f'future_or_consumed_initial_containment:{child}:{parent}')
        if by[child]['owner']!=by[parent]['owner']:
            errors.append(f'initial_container_owner_mismatch:{child}:{parent}')
    if errors:raise ValueError(';'.join(errors))


def main():
    parser=argparse.ArgumentParser()
    for name in ('prior','run'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--additional-calls',type=int,default=0)
    parser.add_argument('--registry-from',type=Path,help='Reuse a known native registry for exactly the same candidate and source.')
    a=parser.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    candidate=read(a.prior/'CANDIDATE.json');source=read(a.prior/'SOURCE.json');inputs=read(a.prior/'INPUT.json')
    presence=read(a.prior/('PROGRAM_BOUND_PROJECTION.json' if (a.prior/'PROGRAM_BOUND_PROJECTION.json').exists() else 'PRESENCE.json'))
    people=inputs['people'];places=[r['id'] for r in inputs['places']]
    if presence['candidate_sha256']!=digest(candidate):raise ValueError('stale_presence')
    entities={'entities':[{'id':p,'kind':'character'} for p in people]}
    if a.additional_calls<0:raise ValueError('negative_engineering_extension')
    old_ceiling=plan['max_calls'];plan['max_calls']=max(old_ceiling,old['calls_started']+a.additional_calls)
    a.run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',source),('CANDIDATE',candidate),('PRESENCE',presence),('INPUT',inputs),
        ('ACCOUNTING',{'prior':str(a.prior),'prior_state_sha256':digest(old),'ceiling':plan['max_calls'],
                      'old_ceiling':old_ceiling,'net_extension':plan['max_calls']-old_ceiling,
                      'calls_carried':old['calls_started'],'tokens_carried':old['reported_tokens']})]:
        freeze(a.run/(name+'.json'),value)
    snap=a.run/'implementation';snap.mkdir();manifest={}
    for path in [Path(__file__),*Path('src/content_factory/novel_adaptation').glob('*.py')]:
        raw=path.read_bytes();(snap/path.name).write_bytes(raw);manifest[str(path)]=hashlib.sha256(raw).hexdigest()
    freeze(snap/'MANIFEST.json',manifest)
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=StringEnvelopeLedger(a.run,plan,state,StringEnvelopeClient(a.run,plan));ledger.save()
    try:
        if a.registry_from:
            prior_registry_state=read(a.registry_from/'STATE.json')
            if prior_registry_state['pending'] is not None or prior_registry_state['status'] in ('running','prepared'):
                raise ValueError('registry_source_not_terminal')
            if digest(read(a.registry_from/'CANDIDATE.json'))!=digest(candidate) or digest(read(a.registry_from/'SOURCE.json'))!=digest(source):
                raise ValueError('registry_input_mismatch')
            registry=read(a.registry_from/'PROP_REGISTRY_ENVELOPE_DECODED.json')
            freeze(a.run/'REGISTRY_ADOPTION.json',{'from':str(a.registry_from),'native_registry_sha256':digest(registry),
                'candidate_sha256':digest(candidate),'source_sha256':digest(source),'regenerated':False})
            freeze(a.run/'PROP_REGISTRY_ENVELOPE_DECODED.json',registry)
        else:
            registry=ledger.call('PROP_REGISTRY','writer',
                '''从固定候选建立关键叙事道具初态，不写剧本、不修复缺失动作。追踪会发生拿取、入锅、盛出、分配、吃掉的食材及必要容器，不登记所有普通布景和器具。owner只能是人物或地点。initial_containers只列整稿开始前已存在的真实容纳关系：两端必须initial_status=present且owner相同；planned产物不得提前放入锅或碗，后续容纳由事件创建。切片、炖成菜用recipes区分原料和产物，尚未产生的产物initial_status=planned。所有原料/产物/容器ID必须在props登记。recipes.source_ids选支持该过程的原文章节段号；只引证，不称原文包含每个影视细节。初始状态是整稿开始前，不能把后段状况提前。若原稿没有明确承接或同一物品先后冲突，列uncertainties，不补造过程。recipes.kind=transformation表示改变形态，必须有outputs；kind=consumption表示吃掉或销毁，outputs与retained_inputs都必须为空，不虚构eaten-meal之类物理产物。泛称“吃饭”不能擅定另煮了米饭。盛菜换容器不是复制一份菜，不能保留整份原菜再生成一份等量新菜。''',
                {'candidate':candidate,'locations':presence['initial_locations'],'places':inputs['places'],
                 'source_catalog':c.catalog(source)},registry_schema(people,places,source))
        errors=c.schema_issues(registry,registry_schema(people,places,source),'registry')
        if errors:raise c.ContractError(errors)
        validate_initial_containers(registry)
        prop_plan={'places':inputs['places'],'scenes':[{'id':s['id'],'place':s['place']} for s in candidate['scenes']],
            'initial_locations':presence['initial_locations'],'props':registry['props'],
            'initial_prop_status':{p['id']:p['initial_status'] for p in registry['props']},
            'containers':{p['child']:p['container'] for p in registry['initial_containers']},
            'recipes':registry['recipes'],'container_actions':True,'action_contract_version':2,
            'allow_consumption_recipes':True}
        initial_state(prop_plan,entities);freeze(a.run/'PROP_PLAN.json',prop_plan)
        identity={'candidate_sha256':digest(candidate),'plan_sha256':digest(prop_plan)}
        freeze(a.run/'PROJECTION_IDENTITY.json',identity)
        evidence={k:{f:v for f,v in r.items() if f!='text'} for k,r in catalog(candidate).items()}
        body=ledger.call('PROP_EVENTS','writer',
            '''将固定剧本的关键道具动作投影到已有注册表，不改人物移动、不写新剧本。不确定或缺失步骤列uncertainties，禁止补动作让状态过关。
每段必须返回一行，events可空。kind使用合同规定的transfers/prop_uses/unpacks/packs/transforms/gestures；evidence_ids只能引用本段动作或连续性义务的地址。容器中物品先unpacks才能转移；整容器转移会携带内容物。transforms根据recipe改变状态，transformation产生新物，consumption只消耗不产生物品；completion_action要来自实际候选。吃掉用有据转化，不让已消耗食物再出现。
action_order按段内执行顺序列出所有事件及人物投影中的moves（索引按各类型分开），每项恰好一次。phase=start/end/after_audio；after_audio_index只在after_audio时填写。不能跳过人物moves。普通布景无需补演员搬运；关键物品状态变化才需明确承接。仅当前候选是真实依据；注册表并非语义已验收。''',
            {'candidate':candidate,'prop_plan':prop_plan,'presence':presence,'evidence_catalog':evidence},
            props.body_schema(candidate,prop_plan,entities))
        projection=props.bind_body(candidate,prop_plan,body,identity,entities)
        freeze(a.run/'PROP_PROJECTION.json',projection)
        freeze(a.run/'EVENT_STRUCTURE_AUDIT.json',props.audit_event_structure(presence,projection))
        result=replay(candidate,presence,people,places,prop_plan=prop_plan,prop_projection=projection)
        result['registry_uncertainties']=registry['uncertainties']
        freeze(a.run/'COMBINED_REPLAY.json',result)
        state['status']='combined_replay_awaiting_semantic_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',error_record(exc))
    finally:ledger.save()


if __name__=='__main__':main()
