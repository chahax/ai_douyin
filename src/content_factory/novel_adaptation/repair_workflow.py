"""Repair owned fields against source obligations; keep native prose elsewhere."""
from copy import deepcopy
from dataclasses import asdict
from . import contracts as c,scenes as sc
from .events import require_review,validate_requirements
from .patching import mechanical_repair_scope,field_patch_schema,apply_field_patches,schedule_audio,retime_beats,audio_kind_patch_schema,apply_audio_kinds,visual_patch_schema,apply_visual_patches,audio_text_patch_schema,apply_audio_texts
from ..corpus_screenplay_v1 import freeze,digest


def obligation_permissions(scene,events):
    result={}
    for event in events:
        matched=[i for i,b in enumerate(scene['beats']) if set(b['source_ids'])&set(event['source_ids'])]
        if not matched:raise ValueError('source_event_without_addressable_beat')
        if event['kind']=='leave':matched=sorted(set(matched+[min(len(scene['beats'])-1,i+1) for i in matched]))
        field={'transfer':'transfers','transform':'transforms'}.get(event['kind'],'moves')
        for i in matched:result.setdefault(scene['beats'][i]['id'],set()).add(field)
        if event['kind']=='transform':
            for i in matched:result[scene['beats'][i]['id']].add('action_order')
    return result


def repair_episode(run,ledger,source,packet,candidate,contract,contract_review,review_plan):
    require_review(contract,source,contract_review)
    if review_plan['candidate_sha256']!=digest(candidate):raise ValueError('semantic_review_stale_candidate')
    entities={'entities':packet['entities']};fact_ids=[f['id'] for f in packet['facts']]
    result=deepcopy(candidate);design=result['design'];design['target_chapters']=review_plan['target_chapters']
    visual=review_plan.get('visual',{})
    if visual.get('indexes'):
        indexes=visual['indexes'];schema=visual_patch_schema(indexes)
        correction=ledger.call('VISUAL_PATCH','writer',
            '仅修列明视觉设定条目的description。保持已确定事实、人物、场景、道具和其他条目不变。统一已有设定冲突，不增加新剧情。description只写可见的正向视觉内容，不写不能/不得/不要之类禁令、返修解释或给模型的指令。',
            {'design':design,'indexes':indexes,'findings':visual['findings']},schema)
        design=apply_visual_patches(design,correction['corrections'],indexes,digest(design))
        result['design']=design;freeze(run/'DESIGN_REPAIRED.json',design)
    previous=sc.initial_state(design,entities);views=[];all_effects=[]
    for index,(scene,spec) in enumerate(zip(result['scenes'],design['scenes'])):
        original=deepcopy(scene);scene=sc.derive_presence_input(scene);instructions=review_plan['scenes'].get(scene['id'],{})
        removed=set(instructions.get('remove_beats',[]))
        if removed:
            # Explicit source-scope review owns deletion; no automatic silent crop.
            if not removed<={b['id'] for b in scene['beats']}:raise ValueError('remove_unknown_beat')
            scene['beats']=[b for b in scene['beats'] if b['id'] not in removed]
            scene,_=retime_beats(scene)
        text_permissions=instructions.get('audio_text_permissions',{})
        if text_permissions:
            text_schema=audio_text_patch_schema(text_permissions)
            texts=ledger.call('AUDIO_TEXT_'+scene['id'],'writer',
                '仅修指定音轨文字，依原文和已核对问题明确归属，不增加剧情。输出beat_id/index/text；其他台词、说话人、音轨类型和时间由程序保持。尽量保留原句，只改消除歧义所必需的部分。',
                {'complete_chapters':c.indexed_chapters(source),'candidate':scene,
                 'permissions':text_permissions,'findings':instructions.get('text_findings',[])},text_schema)
            scene=apply_audio_texts(scene,texts['corrections'],text_permissions,digest(scene))
        kind_permissions=instructions.get('audio_kind_permissions',{})
        if kind_permissions:
            kind_schema=audio_kind_patch_schema(kind_permissions)
            kinds=ledger.call('AUDIO_KIND_'+scene['id'],'writer',
                '只依据原文判断指定音轨是说出的对白还是内心。返回beat_id、index、kind，不重写台词或时间。',
                {'complete_chapters':c.indexed_chapters(source),'candidate':scene,
                 'permissions':kind_permissions,'findings':instructions.get('findings',[])},kind_schema)
            scene=apply_audio_kinds(scene,kinds['corrections'],kind_permissions,digest(scene))
        scene,timing=schedule_audio(scene);spec['duration_seconds']=timing['duration_seconds']
        freeze(run/(scene['id']+'_TIMING.json'),timing)
        events=[e for e in contract['events'] if e['scene_id']==scene['id']]
        pre_effects=[]
        try:sc.advance(scene,spec,design,entities,fact_ids,source,previous,effects=pre_effects)
        except c.ContractError:pre_effects=[]
        try:
            validate_requirements({'scenes':[scene],'containers':previous.get('containers',{})},{'events':events},transition_effects=pre_effects);missing=[]
        except c.ContractError as exc:
            missing=[e for e in events if e['id'] in {x.path for x in exc.issues}]
        permissions=obligation_permissions(scene,missing)
        for id,fields in instructions.get('fields',{}).items():
            fields=set(fields)
            if id in kind_permissions:fields.discard('audio')
            if fields:permissions.setdefault(id,set()).update(fields)
        try:sc.advance(scene,spec,design,entities,fact_ids,source,previous)
        except c.ContractError as exc:
            freeze(run/(scene['id']+'_PRECHECK.json'),[asdict(x) for x in exc.issues])
            mechanical=mechanical_repair_scope(scene,exc.issues)
            for id,fields in mechanical.items():permissions.setdefault(id,set()).update(fields)
        if permissions:
            schema=field_patch_schema(sc.model_scene_schema(design,entities,fact_ids,source,previous),permissions)
            raw=ledger.call('OWNED_PATCH_'+scene['id'],'writer','''你只修指定字段，不重写其他动作、镜头、情绪或台词。
    当前机械问题不能靠改剧情迎合校验。依据原文动作合同，在实际发生拿走/离场/入场的beat补状态登记。
    每个源文要求必须在指定场次演出。人物拿着东西走动不是持有人变化。
    人物先说话再离场时，在同beat的moves填写phase=end（音轨之后）；进场后再说话用phase=start。离场到__OFFSCREEN__，下一场从画外入场。
    需要在某句之后、下一句之前进出时，用phase=after_audio与after_audio_index（0起始索引），程序按每句时点计算在场和听闻。transfers同样支持start/end/after_audio；moves和transfers都必须是JSON数组，不能用item对象包装；在场名单完全由程序计算，不输出present字段。
    fields列出的语义修订意见已对照原文核验；只纠正这些问题，不凭空添加新情节。
    台词可在原意内精简，说话人及条数保持；只有audio_kind_permissions列明的索引允许改成指定音轨类型，其余类型保持；此类补丁每条台词文字、顺序、时间均原样保留，不能交换同一说话人的不同句；程序会重新计算超速音轨时间，不必靠删台词过检。
    返回patches中的changes，仅允许给定字段。保留beat ID和未选字段。动作表演内容正向、具体，不写审核说明。''',
                {'complete_chapters':c.indexed_chapters(source),'candidate':scene,'previous_state':previous,
                 'scene_plan':spec,'design':{k:v for k,v in design.items() if k not in ('world_framework','source_constraints')},
                 'required_source_events':events,'semantic_findings':instructions.get('findings',[]),
                 'allowed_fields':{id:sorted(v) for id,v in permissions.items()},
                 'audio_kind_permissions':instructions.get('audio_kind_permissions',{})},schema)
            errors=c.schema_issues(raw,schema,'patch')
            if errors:raise c.ContractError(errors)
            scene=apply_field_patches(scene,raw['patches'],permissions,digest(scene),
                audio_kind_permissions=instructions.get('audio_kind_permissions',{}))
        scene,timing=schedule_audio(scene);spec['duration_seconds']=timing['duration_seconds']
        effects=[]
        ending=sc.advance(scene,spec,design,entities,fact_ids,source,previous,effects=effects)
        validate_requirements({'scenes':[scene],'containers':previous.get('containers',{})},{'events':events},transition_effects=effects)
        all_effects.extend(effects)
        freeze(run/(scene['id']+'_EXECUTED_TRANSFERS.json'),effects)
        view=sc.production_scene(scene,spec,design,entities,fact_ids,source,previous)
        freeze(run/(scene['id']+'_FINAL.json'),scene);freeze(run/(scene['id']+'_END_STATE.json'),ending)
        freeze(run/(scene['id']+'_OWNERSHIP.json'),{'original_scene_sha256':digest(original),
            'removed_for_reviewed_scope':sorted(removed),'allowed_fields':{id:sorted(v) for id,v in permissions.items()},
            'timing':timing,'source_event_contract_sha256':digest(contract)})
        result['scenes'][index]=scene;previous=ending;views.append(view)
    result['end_state']=previous
    validate_requirements(result,contract,transition_effects=all_effects)
    freeze(run/'EPISODE.json',result);freeze(run/'PRODUCTION_VIEWS_UNAPPROVED.json',views)
    return result,views
