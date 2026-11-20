"""Reviewed cards -> compiled design -> scoped scenes -> independent review.

No provider-specific experiment IDs or book facts live in this orchestration.
"""
from dataclasses import asdict
from copy import deepcopy
from . import contracts as c,scenes as sc
from .patching import mechanical_repair_scope,field_patch_schema,apply_field_patches,schedule_audio
from ..corpus_screenplay_v1 import freeze,digest
from .events import require_review,validate_requirements,event_schema
from .repair_workflow import obligation_permissions
from .handoff import continue_state,inherit_design,opening_delta_schema,bind_opening_delta
from .blocking import blocking_schema,compile_blocking,action_contract_prompt
from .schema_projection import compact_enums
from .pacing import validate_pacing
from .presentation import display_names
from .reference_repair import adopt_checkpoint
from .review_projection import review_projection
from .context_projection import encode_state

POLICY='''依据原文改编，而不是重新发明事实。显示姓名、实体ID、原文事实和影视设计分别处理。
按当前阶段完成一项任务。既定说话人、条件、因果、时间层保持准确；无据内容只可作为合理影视补足。
原书未来、当下、过去、内心和现场对白分开。节奏紧凑，动作和对白同时传递关系，不用长段静止解说。
镜头衔接平稳有动机。视觉信息以正向内容描述；不把审核过程、禁止项和程序说明写进表演字段。'''


REVIEW_POLICY='''这是小说影视改编审核，不是逐字转写核对。
允许忠于人物已知动机、事实与因果的口语化台词、内心表达及普通可拍动作；仅因原文没有逐字出现，不成立must_fix。
把原文叙述改成对白或内心时，检查该人物是否有相应信息与动机，不能把所有第一人称改编一概当事实错误。
must_fix须说明当前具体矛盾或明确新增的无据事实；合理省略和节奏取舍列suggestion。
同稿中已有明确状态时必须使用：人物已经站立不能再次起身；持物仍在手中可以跨场保持，无须强迫放下。
同时检查补丁是否把返修过程或否定镜头指令写进了给视频模型的表演字段。'''


def require_schema(value,schema,owner):
    errors=c.schema_issues(value,schema,owner)
    if errors:raise c.ContractError(errors)
    return value


def select_packet(packet,fact_ids,previous):
    available={f['id']:f for f in packet['facts']}
    if len(set(fact_ids))!=len(fact_ids) or not set(fact_ids)<=available.keys():raise ValueError('scene_fact_scope')
    result=deepcopy(packet);result['facts']=[deepcopy(available[id]) for id in fact_ids]
    result['previous_state']=deepcopy(previous)
    needed=set().union(*(set(f['source_ids']) for f in result['facts'])) if fact_ids else set()
    result['evidence']={k:v for k,v in packet['evidence'].items() if k in needed}
    return result


def compact_design(design,current_scene_id=None):
    result={k:deepcopy(v) for k,v in design.items() if k not in ('source_constraints','reviewed_packet_sha256')}
    if current_scene_id is not None:
        index=next(i for i,s in enumerate(design['scenes']) if s['id']==current_scene_id)
        result.pop('world_framework',None)
        result['world_framework_source']='Full original chapters and selected reviewed facts are supplied separately; world_fact_ids remain unchanged.'
        for i,row in enumerate(result['scenes']):
            if abs(i-index)>1:row.pop('objective',None)
        result['scene_context_scope']='Current and adjacent scene objectives complete; other scene IDs, places, timings and fact links preserved. Full novel chapters supplied separately.'
    return result


def scene_evidence_ids(facts,events,source):
    """Include each selected fact's source span and required event evidence."""
    catalog=c.catalog(source);ordered=list(catalog);positions={key:i for i,key in enumerate(ordered)}
    allowed=set()
    for fact in facts:
        groups={}
        for key in fact['source_ids']:
            if key not in catalog:raise ValueError('fact_source_missing')
            groups.setdefault(catalog[key]['chapter'],[]).append(positions[key])
        for chapter,indexes in groups.items():
            allowed.update(key for key in ordered[min(indexes):max(indexes)+1] if catalog[key]['chapter']==chapter)
    for event in events:allowed.update(event['source_ids'])
    if not allowed<=catalog.keys():raise ValueError('event_source_missing')
    return [key for key in ordered if key in allowed]


def run_workflow(run,ledger,source,packet,brief,*,design_checkpoint=None,source_contract=None,contract_review=None,continuation=None,native_scene_checkpoints=None,design_only=False):
    if packet['semantic_status']!='selected_dependencies_reviewed' or packet['source_sha256']!=digest(source):
        raise ValueError('unreviewed_or_changed_source')
    entities={'entities':packet['entities']};ids=[r['id'] for r in packet['entities']]
    people=[r['id'] for r in packet['entities'] if r['kind']=='character'];fact_ids=[r['id'] for r in packet['facts']]
    full_source=c.indexed_chapters(source)
    if design_checkpoint is None:
        schema=sc.plan_schema(ids,fact_ids,people,separate_opening=True)
        schema['properties']['scenes'].update(minItems=brief['scene_count'],maxItems=brief['scene_count'])
        if continuation is not None:schema['properties']['places']['minItems']=0
        raw=ledger.call('DESIGN','writer',POLICY+'''
    规划本集场次与视觉设计。world_fact_ids只选已审核事实ID，程序会原样组装世界框架。
    visual_design全部是adaptation_design，仅写画风、光线、布局、服装等补足，不再重述原文事实。
    本次只做地点布局与场次计划；开场位置与持有人由下一步骤确定。
    props按实际需要登记物品实例与物理外观，不写前后交接故事；赠予面包和另一次购买面包是不同实例。出示现金就登记现金，拒收不发生交接；发传单是过去的工作，不代表开场拿着传单。
    每场objective写剧情目标，fact_ids只选本场所需的事实；场次前后有清楚的进入/离开连接。
    一个场次对应一个地点，人物离开后在门外的对白另设场次。未来才加工生成的成品登记planned_props，初始不可见；recipes列出加工动作、输入、输出、保留输入及原段source_ids。食材消耗后不能重复使用；分装可保留母体输入。需要从袋中取出或装入物品时设置container_actions=true。
    若previous_episode非空：places和props只输出新增资产，旧ID及描述由程序继承，不能重复输出；scenes可以引用旧地点/道具。visual_design只写新增场地需要的局部设计，旧整体画风由程序继承。''',
            {'complete_chapters':full_source,'reviewed_packet':packet,'brief':brief,'previous_episode':continuation},schema)
        require_schema(raw,schema,'design')
        if continuation is not None:raw=inherit_design(raw,continuation)
        design=sc.compile_design(raw,packet)
        design['target_chapters']=brief.get('target_chapters',[chapter['index'] for chapter in source['chapters']])
        if continuation is None and any(p['id']=='__OFFSCREEN__' for p in design['places']):raise ValueError('reserved_offscreen_id')
        if not any(p['id']=='__OFFSCREEN__' for p in design['places']):
            design['places'].append({'id':'__OFFSCREEN__','description':'程序状态占位：尚未入场且未细分的画外位置；不是新增具体场景。','basis':'adaptation_design'})
        freeze(run/'DESIGN_CONTEXT_COMPILED.json',design)
        schema=opening_delta_schema(design,entities,continuation) if continuation is not None else sc.opening_schema(design,entities)
        opening=ledger.call('OPENING_STATE','writer',POLICY+'''
    只填写本集第一帧的状态。所有值从已给编号中选择，位置说明不写进编号。
    按原文开头判断谁在现场、谁还没进来、道具尚未交给谁；不能把后场状态当开场。
    在后场首次出现的人也要有合理场外/相邻屋初始位置，使其后续通过动作进入。
    尚未归家或未交代位置者使用__OFFSCREEN__，后续入场再移动到实际地点；不要为了填表虚构已经在屋内。
    这是本集最开始，不是第一场结尾。原文开头对白正在发生，后面的递物、拿走、离场均尚未发生。
    previous_episode非空时，只填写schema中新增人物/道具的位置，旧人物位置及道具持有者由程序继承，不能重新指定或覆盖。''',
            {'complete_chapters':full_source,'entities':entities,'layout_and_instances':design,
             'opening_scene':design['scenes'][0],'brief':brief,'previous_episode':continuation},schema)
        design=(bind_opening_delta(design,entities,continuation,opening) if continuation is not None
                else sc.bind_opening(design,opening,entities))
        freeze(run/'DESIGN_COMPILED.json',design)
    else:
        design=deepcopy(design_checkpoint)
        if brief.get("title"):design["title"]=brief["title"]
        if design.get('reviewed_packet_sha256')!=digest(packet):raise ValueError('checkpoint_packet_changed')
        expected=sc.compile_design({'world_fact_ids':design['world_fact_ids']},packet)
        if design['source_constraints']!=expected['source_constraints'] or design['world_framework']!=expected['world_framework']:
            raise ValueError('checkpoint_source_facts_changed')
        freeze(run/'DESIGN_COMPILED.json',design)
    for recipe in design.get('recipes',[]):
        if not set(recipe['source_ids'])<=c.catalog(source).keys():raise ValueError('recipe_source_unknown')
    if source_contract is not None:
        require_review(source_contract,source,contract_review or {})
        require_schema(source_contract,event_schema(source,design,entities,design['target_chapters']),'source_events')
        freeze(run/'SOURCE_EVENTS.json',source_contract)
        freeze(run/'SOURCE_EVENTS_REVIEW.json',contract_review)
    elif brief.get('require_source_events') and not design_only:
        raise ValueError('reviewed_source_events_required_before_scene_generation')
    previous=(continue_state(continuation,brief['handoff_sha256'],design,entities,
        book_id=brief['book_id'],episode_id=brief['episode_id'],timeline_id=brief['timeline_id'])
        if continuation is not None else sc.initial_state(design,entities))
    if continuation is not None:freeze(run/'PREVIOUS_EPISODE_HANDOFF.json',continuation)
    completed=[];views=[]
    freeze(run/'INITIAL_STATE.json',previous)
    if design_only:
        prepared={'design':design,'initial_state':previous,'status':'design_awaiting_review',
            'source_event_gate':'not_executed','scene_generation_executed':False}
        freeze(run/'DESIGN_PREPARATION.json',prepared)
        return prepared,None
    for spec in design['scenes']:
        selected=select_packet(packet,spec['fact_ids'],{})
        scene_events=[e for e in (source_contract or {}).get('events',[]) if e['scene_id']==spec['id']]
        evidence_ids=scene_evidence_ids(selected['facts'],scene_events,source)
        schema=sc.model_scene_schema(design,entities,spec['fact_ids'],source,previous,
            evidence_ids=evidence_ids)
        if brief.get('typed_blocking'):
            schema=blocking_schema(design,entities,spec['fact_ids'],source,previous,
                evidence_ids)
        generation_events=deepcopy(scene_events)
        for event in generation_events:
            if event['kind']=='transfer' and event['prop'] in previous.get('containers',{}):
                event['execution']='inherited_from_container_transfer'
                event['container']=previous['containers'][event['prop']]
        payload={'required_source_events':generation_events,'complete_chapters':full_source,'selected_facts':selected['facts'],'design':compact_design(design,spec['id']),
            'current_scene':spec,'previous_state':encode_state(previous,design,compact_events=bool(brief.get('compact_information_events'))),'previous_ending_beats':completed[-1]['beats'][-2:] if completed else [],'brief':brief}
        prompt=POLICY+'''
本次只写指定场次，其他场次不重写。全文仅提供理解上下文，新增事实只采用本场selected_facts；不把上下文中未分配的背景强行加进本场。required_source_events是已核对的原文必需动作，在本场实际演出且登记状态，不能仅靠前后状态自洽而省略这些动作。每beat是连续不超过15秒的一段动作；本场从0秒连续到duration_seconds。
camera/action/emotion只写可见、可表演内容。audio为实际音轨，绝对秒位于本beat内、顺序不重叠；每秒最多6个字符含标点，需留出自然停顿。
dialogue是说出的台词，inner是角色自己的内心，narration说话者为NARRATOR。
角色的在场名单由程序从前态计算，不需要输出present。人物换房间才写moves，同房间走动写action。
moves/transfers的phase=start表示音轨之前发生，phase=end表示音轨之后发生；先说完再离场用end，入场后再说话用start。省略phase默认start。
中途入场可用phase=after_audio和after_audio_index（0起始），在该句结束后动作、后面的句子前完成。
prop_uses必填：列出本beat画面实际持有或放置的已登记关键道具，写prop/holder及phase（默认start）。仅台词提及不算画面使用。已在前场交给别人且没有再交回的物件，当前角色不能再次拿出。
transfers只记录拿起、放下、交给的持有变化。人带物进屋无需transfer，持有人仍是这个人。
重要物件在正文放下/拿起时要有相应transfer，交接动作只写一次。空moves/transfers可省略，省略表示没有变化。
requires_information仅在表演依赖前beat已听到的信息时填person/event_id，ID只能从该人物previous_state.information取得，E001之类事实编号不是音轨编号；前态没有音轨时此列表只能为空或省略；旁白和他人内心不能被听到。
adaptation_detail只简短说明新增的影视补足，不解释本次修复，不复述当前持物或程序规则。'''
        if brief.get('typed_blocking'):
            prompt=POLICY+'''
只输出本场指定资料支持的内容，完整章节只作上下文。
blocking是唯一动作记录；程序从它生成动作文字与状态表。不要另写action/moves/transfers/camera。
container_actions启用时，取出容器内物品用unpack，装入用pack；按已审核recipes加工用transform。planned物品在transform完成前不可展示或交接；已经consumed的输入不能再次使用。按真实动作顺序排列这些操作。
同一phase内严格按blocking数组顺序执行。show表示本人持物展示，交出后原持有人不能再show；先展示再交出时将show排在transfer前。adaptation_detail只简述设计补足，不另写一套动作过程。
shot只选择构图、机位、运动与主体。所有递交、放下、拿起都用transfer；同物归属必须承接previous_state。
previous_state.containers是内含物到容器的关系。完整递交容器时，仍在其中的内含物随容器转移；显式unpack之后，该物品独立承接新持有人，不再随原容器转移。
gesture用于清楚的表演，目标必须与动作相符；双手接袋前可把药瓶放在已登记地点，作为合理调度补足。
不得把袋中集体道具拆成未登记的个体；每条required_source_events实际执行。
phase=start表示音轨前；end表示音轨后；after_audio配0起始after_audio_index表示某句后。
台词与内心保留原文含义、条件与时间层；事实编号不是音轨编号。本场selected_facts之外的背景不另加。
每beat必须显式填写audio数组。人物实际说出的对白写入audio的speaker/text/start/end；只在adaptation_detail写“她说/他宣布”不会产生任何声音。原文关键对白不能丢失，只有确实静默的beat才填audio=[]。
每beat不超过15秒，逐句音轨顺序不重叠，语速含标点最多6字符/秒。'''
        if brief.get('typed_blocking'):prompt+=action_contract_prompt(design)
        if brief.get('pacing_policy'):
            payload['current_scene']=deepcopy(spec)
            payload['current_scene'].pop('duration_seconds',None)
            payload['pacing_policy']=brief['pacing_policy']
            prompt+='''\n本场按内容需要决定时长，pacing_policy中的max_scene_seconds只是上限，不是必须凑满的目标。
对白发生时同时进行对应动作；画面已明确演出的接袋、微笑、摸头不再逐句旁白重述。
只保留有新信息或情绪变化作用的反应。纯无声注视、点头、微笑段遵守max_silent_reaction_seconds。
不要用空白结尾填满时长，也不要为填时长增加原文之外的剧情。'''
        prompt+='\n前态information按人物列已知音轨ID，完整记录在information_event_catalog，内容未省略。requires_information使用该人物列表中的原ID。recipes_source=design.recipes表示前态配方与设计完全相同，读取design.recipes；它不是缺失配方。'
        if brief.get('compact_information_events'):
            prompt+='\n本请求将information_event_catalog无损按字段分组为information_event_groups：每组fields是列名，rows每行按相同列序对应值；id列是音轨ID。逐列对应即可还原完整音轨记录，没有省略内容。'
        if spec['id'] in (native_scene_checkpoints or {}):
            entry=native_scene_checkpoints[spec['id']]
            scene=adopt_checkpoint(entry,source,design,previous)
            freeze(run/(spec['id']+'_NATIVE_REUSE.json'),entry)
        else:
            scene=ledger.call('SCENE_'+spec['id'],'writer',prompt,payload,compact_enums(schema) if brief.get('compact_output_schema') else schema)
        compiled_reuse=(native_scene_checkpoints or {}).get(spec['id'],{}).get('representation')=='compiled'
        if not compiled_reuse:require_schema(scene,schema,'scene')
        if brief.get('typed_blocking') and not compiled_reuse:
            native_sha=digest(scene);scene=compile_blocking(scene,design,entities,schema)
            freeze(run/(spec['id']+'_BLOCKING_COMPILED.json'),{'native_sha256':native_sha,'scene':scene})
            schema=sc.model_scene_schema(design,entities,spec['fact_ids'],source,previous,
                evidence_ids=evidence_ids)
        scene,timing=schedule_audio(scene);spec['duration_seconds']=timing['duration_seconds']
        freeze(run/(spec['id']+'_PROGRAM_TIMING.json'),timing)
        freeze(run/(spec['id']+'_DISPLAY_NAMES.json'),{'registry_projection':display_names(design,entities),'identity_changed':False})
        pacing_result=validate_pacing(scene,brief.get('pacing_policy'))
        freeze(run/(spec['id']+'_PACING.json'),pacing_result)
        for attempt in range(3):
            try:
                effects=[]
                ending=sc.advance(scene,spec,design,entities,spec['fact_ids'],source,previous,effects=effects)
                validate_requirements({'scenes':[scene],'containers':previous.get('containers',{})},{'events':scene_events},transition_effects=effects)
                freeze(run/(spec['id']+'_EXECUTED_TRANSFERS.json'),effects)
                break
            except c.ContractError as exc:
                freeze(run/f'{spec["id"]}_ISSUES_{attempt}.json',[asdict(x) for x in exc.issues])
                if attempt==2 or brief.get('typed_blocking'):raise
                state_issues=[x for x in exc.issues if x.owner!='source_event']
                missing={x.path for x in exc.issues if x.owner=='source_event'}
                permissions=mechanical_repair_scope(scene,state_issues)
                for id,fields in obligation_permissions(scene,[e for e in scene_events if e['id'] in missing]).items():
                    permissions.setdefault(id,set()).update(fields)
                patch_schema=field_patch_schema(schema,permissions)
                proposal=ledger.call(f'PATCH_{spec["id"]}_{attempt}','writer',prompt+'''
只修机械字段，按给定allowed_fields返回changes。位置或持物问题只能更正状态登记，不能改变正文动作、摄像或台词来迎合校验。
当正文已经写离开/拿走而状态漏报时，在实际发生该动作的beat补moves/transfers，不能让人物停在门口、改变故事。
语速问题可调整该beat音轨时间或缩短台词，但不能改变原意和说话人。''',
                    {**payload,'candidate':scene,'candidate_sha256':digest(scene),'allowed_fields':{k:sorted(v) for k,v in permissions.items()},'issues':[asdict(x) for x in exc.issues]},patch_schema)
                require_schema(proposal,patch_schema,'patch')
                scene=apply_field_patches(scene,proposal['patches'],permissions,digest(scene))
                scene,timing=schedule_audio(scene);spec['duration_seconds']=timing['duration_seconds']
        scene=sc.normalize_scene(scene)
        view=sc.production_scene(scene,spec,design,entities,spec['fact_ids'],source,previous)
        freeze(run/(spec['id']+'_FINAL.json'),scene);freeze(run/(spec['id']+'_PRODUCTION_VIEW.json'),view)
        freeze(run/(spec['id']+'_END_STATE.json'),ending)
        completed.append(scene);views.append(view);previous=ending
    candidate={'design':design,'scenes':completed,'end_state':previous,
        'previous_episode_handoff_sha256':digest(continuation) if continuation is not None else None,
        'source_event_gate':'reviewed_contract_enforced' if source_contract is not None else 'not_executed'}
    freeze(run/'EPISODE.json',candidate);freeze(run/'PRODUCTION_VIEWS_UNAPPROVED.json',views)
    # Review the prose and explicit changes once, not repeated cumulative history per beat.
    audit=review_projection(candidate,brief)
    review_schema=c.obj(verdict=c.choices(['pass','revise','uncertain']),issues=c.array(c.obj(
        owner=c.choices(['source_fact','identity','visual_design','scene','continuity','timing']),
        scene_id=c.choices([s['id'] for s in design['scenes']]+['GLOBAL']),beat_id={'type':'string'},
        problem=c.TEXT,source_ids=c.refs(c.catalog(source)),severity=c.choices(['must_fix','suggestion','uncertain']))))
    review=ledger.call('FINAL_REVIEW','writer',POLICY+REVIEW_POLICY+'''
独立审核同一完整候选。逐条指出具体问题及原段依据。允许有明确标注的合理影视补足；不要把叙述顺序误当实际事件顺序。
检查全文动作是否有漏报的进出/持物变化、说话人和内心归属、事实/设计分离、时间与信息密度；不修改稿件。''',
        {'complete_chapters':full_source,**audit},review_schema)
    require_schema(review,review_schema,'review')
    return candidate,review
