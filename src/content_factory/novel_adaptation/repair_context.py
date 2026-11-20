"""Reconstruct a repair's input state from executed predecessor scenes."""
from copy import deepcopy
from . import contracts as c, scenes as sc
from .events import validate_requirements


def reconstruct(design, entities, source, initial, target_id, load, events):
    ids=[row['id'] for row in design['scenes']]
    if target_id not in ids:raise ValueError('repair_scene_missing')
    state=deepcopy(initial);evidence=[]
    for spec in design['scenes'][:ids.index(target_id)]:
        key=spec['id'];scene=load(key+'_FINAL.json')
        recorded=load(key+'_END_STATE.json')
        if scene['id']!=key:raise ValueError('repair_predecessor_identity')
        # Actual emitted beat timing, not the superseded planning estimate.
        execution={**spec,'duration_seconds':scene['beats'][-1]['end']}
        effects=[]
        state=sc.advance(scene,execution,design,entities,spec['fact_ids'],source,state,effects=effects)
        required=[e for e in events if e['scene_id']==key]
        validate_requirements({'scenes':[scene]},{'events':required},transition_effects=effects)
        if c.digest(state)!=c.digest(recorded):raise ValueError('repair_predecessor_state_mismatch:'+key)
        evidence.append({'scene_id':key,'scene_sha256':c.digest(scene),'end_state_sha256':c.digest(state)})
    return state,{'target_scene_id':target_id,'source_sha256':c.digest(source),
        'design_sha256':c.digest(design),'initial_sha256':c.digest(initial),
        'previous_sha256':c.digest(state),'replayed':evidence}


REPAIR_PROMPT='''只修scope指定beat的指定字段。未选字段由程序原样保留。
audio_texts只给指定索引的新文字，保留说话人、音轨类型、先后顺序；程序重新估算时间。
blocking是唯一实际表演，adaptation_detail是审计说明。观众应看见的动作必须在blocking执行。
previous_state是前面所有场次重放核验后的状态，承接人物位置、道具和知情信息。
依据完整原文与scope中的具体问题返修；保留条件、否定、推测、时间层和对白顺序。
动作正向具体，不在内心旁白里代替实际动作，不改未选字段，不补无据剧情。'''
