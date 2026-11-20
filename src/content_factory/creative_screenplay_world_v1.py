"""Independent native world -> timed screenplay -> source-bound full review.

Pure request/contract functions. No provider calls, media, or approval inference.
"""
from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator
from scripts.creative_resume_dispatch_v3 import digest

VERSION = 'creative_screenplay_world/v1'
CAST = ('C01', 'C02')
CHECKS = ('brief_and_initial_state', 'world_and_space', 'all_character_performance',
          'dialogue_and_reaction_timing', 'stimulus_choice_consequence', 'prop_document_custody',
          'concession_motivation', 'legal_claim_boundaries', 'ending_payoff')


def obj(properties):
    return {'type':'object', 'properties':properties, 'required':list(properties), 'additionalProperties':False}


def arr(item, minimum=1, maximum=100):
    return {'type':'array','items':item,'minItems':minimum,'maxItems':maximum}


S = {'type':'string','minLength':1}
N = {'type':'number','minimum':0}


def world_schema(brief, fixed_casting):
    characters=[]
    for c in CAST:
        ref=fixed_casting[c]
        characters.append(obj({'id':{'const':c},'name':{'const':ref['name']},'motivation':S,'pressure_and_cost':S,
            'relationship':S,'reference_asset_id':{'const':ref['asset_id']},'reference_sha256':{'const':ref['sha256']},
            'appearance_and_clothing':{'const':ref['appearance_and_clothing']},'initial_work_or_entry':S}))
    return obj({'schema':{'const':VERSION+'/world'},'brief_sha256':{'const':digest(brief)},
        'title':S,'story_question':S,'time_of_day':S,'continuous_time_basis':S,
        'environment_light_sound':S,'space_map':arr(obj({'zone_id':S,'description':S}),2,8),
        'spatial_connections':arr(obj({'from_zone':S,'to_zone':S,'relation':S}),1,10),
        'characters':arr({'oneOf':characters},2,2),
        'props':arr(obj({'prop_id':S,'name':S,'purpose':S,'initial_custody':S,'final_intended_custody':S}),1,7),
        'dramatic_arc':arr(obj({'stage':S,'stimulus':S,'choice':S,'consequence':S}),3,8),
        'legal_guardrails':arr(S,1,8), 'ending_boundary':S})


def validate_world(document, brief, fixed_casting):
    Draft202012Validator(world_schema(brief, fixed_casting)).validate(document)
    if {c['id'] for c in document['characters']} != set(CAST):
        raise ValueError('WORLD_CAST_MUST_BE_EXACTLY_C01_C02')
    zones=[z['zone_id'] for z in document['space_map']]
    props=[p['prop_id'] for p in document['props']]
    if len(set(zones))!=len(zones) or len(set(props))!=len(props):
        raise ValueError('WORLD_DUPLICATE_ZONE_OR_PROP')
    for connection in document['spatial_connections']:
        if any(connection[k] not in zones for k in ('from_zone','to_zone')):
            raise ValueError('WORLD_CONNECTION_UNKNOWN_ZONE')
    if not any(c['id']=='C01' and c['name']=='周桂芳' for c in document['characters']) or not any(c['id']=='C02' and c['name']=='马涛' for c in document['characters']):
        raise ValueError('WORLD_CHARACTER_BINDING_CHANGED')
    return {'valid':True,'necessary_conditions_only':True,'semantic_approval':False,'native_world_sha256':digest(document)}


def state_schema(world):
    zones=[z['zone_id'] for z in world['space_map']]
    actor=obj({'zone_id':{'enum':zones},'pose_hands':S,'expression_eyeline':S})
    return obj({'characters':obj({c:deepcopy(actor) for c in CAST}),
                'props':obj({p['prop_id']:deepcopy(S) for p in world['props']})})


def script_schema(brief, world):
    actor=obj({'action':S,'expression':S,'eyeline':S})
    line=obj({'speaker':{'enum':list(CAST)},'text':S,'start_s':N,'end_s':N})
    event=obj({'start_s':N,'end_s':N,'characters':obj({c:deepcopy(actor) for c in CAST}),
               'dialogue':arr(line,0,4),'prop_change':S})
    segment=obj({'id':S,'start_seconds':N,'duration_seconds':{'type':'number','exclusiveMinimum':0,'maximum':15.083333334},
        'story_time':S,'location_zone_id':{'enum':[z['zone_id'] for z in world['space_map']]},
        'environment_light_sound':S,'previous_causal_link':S,'next_causal_link':S,'emotional_focus':S,
        'start_state':state_schema(world),'end_state':state_schema(world),'events':arr(event,1,5),
        'dramatic_change':S})
    return obj({'schema':{'const':VERSION+'/screenplay'},'brief_sha256':{'const':digest(brief)},
        'world_sha256':{'const':digest(world)},'title':S,'premise':S,
        'total_duration_seconds':{'type':'number','minimum':150,'maximum':180},
        'segments':arr(segment,10,18)})


def validate_script(document, brief, world):
    Draft202012Validator(script_schema(brief, world)).validate(document)
    diagnostics=[]; cursor=0; previous=None; seen=set()
    for segment in document['segments']:
        sid=segment['id']; duration=segment['duration_seconds']
        if sid in seen:diagnostics.append(f'{sid}: duplicate segment ID')
        seen.add(sid)
        if abs(segment['start_seconds']-cursor)>.001:diagnostics.append(f'{sid}: global timeline gap/overlap')
        if previous is not None and segment['start_state']!=previous:
            diagnostics.append(f'{sid}: start_state differs from previous original end_state')
        if previous is None and segment['start_state']['props']!={p['prop_id']:p['initial_custody'] for p in world['props']}:
            diagnostics.append(f'{sid}: opening prop custody differs from original world')
        if cursor==0 and abs(duration-15.0)>.001:diagnostics.append(f'{sid}: revised opening must be15.0seconds')
        last_start=-1; covered=0; dialogue=[]
        for ei,event in enumerate(segment['events']):
            if not 0<=event['start_s']<event['end_s']<=duration+.001 or event['start_s']<last_start:
                diagnostics.append(f'{sid}.events.{ei}: invalid local event interval/order')
            last_start=event['start_s']
            if event['start_s']>covered+.001:diagnostics.append(f'{sid}.events.{ei}: undescribed timeline gap')
            covered=max(covered,event['end_s'])
            for line in event['dialogue']:
                if not event['start_s']<=line['start_s']<line['end_s']<=event['end_s']+.001:
                    diagnostics.append(f'{sid}.events.{ei}: dialogue outside event interval')
                chars=len(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',line['text']))
                if chars>4.2*(line['end_s']-line['start_s'])+.5:
                    diagnostics.append(f'{sid}.events.{ei}: line exceeds4.2spoken characters/sec; leave natural reactions')
                dialogue.append(line)
        if covered<duration-.001:diagnostics.append(f'{sid}: undescribed tail interval')
        dialogue.sort(key=lambda l:l['start_s'])
        for before,after in zip(dialogue,dialogue[1:]):
            if after['start_s']<before['end_s']-.001:diagnostics.append(f'{sid}: overlapping spoken turns')
        if cursor==0:
            if not dialogue or dialogue[0]['speaker']!='C02' or dialogue[0]['start_s']>.15:
                diagnostics.append(f'{sid}: manager must speak immediately during entrance')
            if not any(l['speaker']=='C01' for l in dialogue):diagnostics.append(f'{sid}: first segment needs Guifang actual reply')
            if segment['events'][0]['start_s']!=0:diagnostics.append(f'{sid}: opening work/entry event must start at0')
        previous=segment['end_state']; cursor+=duration
    if abs(cursor-document['total_duration_seconds'])>.001:diagnostics.append('total_duration_seconds differs from summed segments')
    return {'valid':not diagnostics,'diagnostics':diagnostics,'necessary_conditions_only':True,
            'semantic_approval':False,'native_script_sha256':digest(document),'total_seconds':cursor,
            'segment_count':len(document['segments'])}


def evidence_check_schema():
    return obj({'status':{'enum':['pass','fail','unknown']},'reason':S,
                'quotes':arr(S,1,5),'required_revision':{'type':'string'}})


def review_schema(brief, world, script):
    check=evidence_check_schema()
    return obj({'schema':{'const':VERSION+'/full_review'},'brief_sha256':{'const':digest(brief)},
        'world_sha256':{'const':digest(world)},'script_sha256':{'const':digest(script)},
        'world_and_story_checks':obj({k:deepcopy(check) for k in CHECKS}),
        'segments':obj({s['id']:deepcopy(check) for s in script['segments']}),
        'overall_status':{'enum':['pass','fail','unknown']},'whole_revision_instructions':{'type':'string'}})


def strings(document):
    if isinstance(document,str):yield document
    elif isinstance(document,dict):
        for value in document.values():yield from strings(value)
    elif isinstance(document,list):
        for value in document:yield from strings(value)


def validate_review(document, brief, world, script):
    Draft202012Validator(review_schema(brief,world,script)).validate(document)
    fulltexts=list(strings(script)); issues=[]
    for group,rows in [('world_and_story_checks',document['world_and_story_checks']),('segments',document['segments'])]:
        for key,check in rows.items():
            texts=fulltexts if group!='segments' else list(strings(next(s for s in script['segments'] if s['id']==key)))
            if any(not any(quote in text for text in texts) for quote in check['quotes']):
                issues.append(f'{group}.{key}: quote not found in same original screenplay scope')
            if check['status']=='fail' and not check['required_revision'].strip():
                issues.append(f'{group}.{key}: failure lacks actionable revision')
    statuses=[r['status'] for rows in (document['world_and_story_checks'],document['segments']) for r in rows.values()]
    expected='unknown' if 'unknown' in statuses else ('fail' if 'fail' in statuses else 'pass')
    if document['overall_status']!=expected:issues.append('overall_status contradicts detailed checks')
    return {'valid':not issues,'accepted':not issues and expected=='pass','uncertain':not issues and expected=='unknown',
            'diagnostics':issues,'same_source_quotes_bound':not issues,'human_quality_approved':False,
            'creative_quality_passed':False,'native_document_rewritten':False}


def request(stage, profile, system, payload, schema):
    role='writer' if stage in ('goal_plan','complete_script') else 'director'
    parameters=deepcopy(profile[role]['parameters'])
    parameters.update(profile.get('stage_parameters',{}).get(stage,{}))
    logical={'stage':stage,'role':role,'model':profile[role]['model'],
        'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],
        'parameters':parameters,'structured_schema':schema}
    return {'request':logical,'request_sha256':digest(logical),'provider_calls':0,'native_document_modified':False}


def prepare_world(brief, seed, profile):
    system='''你是MiniMax编剧。先建立可落实到表演的完整剧本世界框架，调用给定工具提交唯一完整原生JSON，不写JSON外说明。新用户简报改变旧初态，不能沿用旧门外等候。C01周桂芳已在值班室内做具体工作；C02马涛从后仓通道跨门立即开口。仅两人，固定现有写实人物/场景资产。对各人物欲望、现实顾虑和关系，空间门/桌/座位/监控与走位，所有纸张唯一身份、用途、初始位置及最后去向作明确计划。世界框架需能在150–180秒自然演出，不用背景摘要替代实际戏。保留劳动关系冲突的现实立场，不声称特定赔偿或个案法律结论；不以经理个人签字证明公司授权或解除已成立。经理让步须有当场可见动因及代价，不能“只要你不签我就填”无因果交换。旧稿仅供辨认故事和失败，整稿可自然重写，不照抄旧台词/纸张矛盾。不能将旧全文审核失败改成通过，不新增导演/媒体调用。'''
    return request('goal_plan',profile,system,{'new_user_brief':brief,'original_story_and_diagnostics':seed,
        'world_framework_is_not_old_plan_capacity_reset':True},world_schema(brief,seed['fixed_casting']))


def prepare_script(brief, world, seed, profile, previous=None, diagnostics=None):
    system='''你是MiniMax编剧，按冻结的新用户简报与本次原生世界框架，完整重写可直接阅读/表演的全部剧本，调用工具提交完整原生JSON。不是摘要、建议、补丁或只返首段。目标150–180秒，10–18个自然互动段，首段15.0秒、其余每段<=15.083秒。每段写全时间、地点、环境光声、每个人动作/神情/视线和段首段尾人物/道具状态、前后因果；每个event两个人都具体描写，可动作与对白并行。C01周桂芳已在屋内真实工作，C02马涛跨门0秒立即说话，桂芳当段有自然回话且工作被打断，禁止固定3秒开场/末6秒静候。自然口语不抢说，通常3–3.5中文字/秒、上限4.2，留适量可读反应，但不要为凑时长空等。events的start_s/end_s及对白start_s/end_s均是本段相对秒；段start_seconds是整片起秒；story_time写剧中清晨具体时间。events按时间顺序覆盖本段；可以描述同步动作，但对白不重叠。每段start_state必须逐值等于上一段原生end_state（连续时间无镜外瞬移），首段props逐值等于world.props.initial_custody；状态值描述位置/持有人/折叠/是否签字，不能仅写“同前”。道具新增/拿出/递交/签字/收回要演出并记清用途；全稿修旧B6让步无动因、排班表与确认单混用和结尾“带走”却留桌上的矛盾。人物说话可以回避，但戏中应有明确刺激、反应、策略改变与代价，结尾从交锋自然落下。叙事不是法律教程，所有法律结论保守，未签书面提议不代表接受/解除成立，排班确认不证明全部争议解决。不得伪写用户采用/导演通过/媒体通过。若有前稿与诊断，用它们生成完整新正文，不作手工拼接或仅返回修改段。'''
    return request('complete_script',profile,system,{'new_user_brief':brief,'native_world':world,
        'same_story_context_and_failures':seed,'previous_complete_native_script':previous,
        'whole_revision_diagnostics':diagnostics},script_schema(brief,world))


def prepare_review(brief, world, script, seed, profile):
    system='''你是DeepSeek全文剧本审查员。审核给定同源完整世界/剧本，不创作新台词、不替换来源、不因摘要声称就通过。逐段阅读每一event、对白、状态，逐一给出实际正文原句quotes和理由；quotes必须逐字复制该段正文某一字符串中的连续原句，全局项也只能引正文。检查用户初态桂芳屋内工作、经理0秒进门立即开口、当段自然来回；每人动作神情视线随刺激变化；全世界时间/空间/环境和连续状态可表演；普通语速、足够反应但无凑时长静候；纸张唯一用途/来源/持有/签字/去向与台词一致；经理让步为何值得、有何现实代价要在戏中兑现，不能无因果交换；结尾承接冲突且不夸大法律结果。注意旧稿B6与B8是具体失败，不得被逐段局部文字正确掩盖；跨段并读前后实际动作再判。所有9个全局项及每段必须检查，fail要明确required_revision；不确定写unknown，不能硬判pass。overall_status按unknown优先、其次fail、否则pass。full review仅是机器文本审核，永不表示用户美学或视频批准。'''
    return request('full_review',profile,system,{'new_user_brief':brief,'native_world':world,'native_complete_screenplay':script,
        'original_story_and_failure_context':seed},review_schema(brief,world,script))


def render_world(world):
    lines=['## 剧本世界框架','',f"核心问题：{world['story_question']}",
        f"时间：{world['time_of_day']}；连续时间依据：{world['continuous_time_basis']}",
        f"环境、光线与声音：{world['environment_light_sound']}",'','### 人物与关系','']
    for c in world['characters']:
        lines += [f"**{c['name']}（{c['id']}）**：{c['appearance_and_clothing']}",
            f"动机：{c['motivation']}；顾虑/代价：{c['pressure_and_cost']}",
            f"关系：{c['relationship']}；开场工作/进门：{c['initial_work_or_entry']}",
            f"固定资产：{c['reference_asset_id']}；SHA256：{c['reference_sha256']}",'']
    lines += ['### 空间与道具','']
    for z in world['space_map']:lines += [f"- {z['zone_id']}：{z['description']}"]
    for c in world['spatial_connections']:lines += [f"- {c['from_zone']} → {c['to_zone']}：{c['relation']}"]
    for p in world['props']:
        lines += [f"- {p['name']}（{p['prop_id']}）：{p['purpose']}；初态：{p['initial_custody']}；计划去向：{p['final_intended_custody']}"]
    lines += ['','### 冲突推进','']
    for a in world['dramatic_arc']:
        lines += [f"- {a['stage']}：刺激 {a['stimulus']} → 选择 {a['choice']} → 后果 {a['consequence']}"]
    lines += ['','### 结尾及法律表达边界','',world['ending_boundary']]
    lines += ['- '+s for s in world['legal_guardrails']]
    return '\n'.join(lines)


def render_state(state):
    lines=[]
    for c in CAST:
        row=state['characters'][c];name='周桂芳' if c=='C01' else '马涛'
        lines += [f"- {name}：{row['zone_id']}；姿态/手：{row['pose_hands']}；神情/视线：{row['expression_eyeline']}"]
    lines += ['- 道具 '+p+'：'+v for p,v in state['props'].items()]
    return '\n'.join(lines)


def render_script(document, world):
    lines=['# '+document['title'],'','完整模型原生修订正文；机器文本审查与用户视频批准分别记录。','',document['premise'],'',
           f"总计 {document['total_duration_seconds']} 秒；{len(document['segments'])} 段。",'',render_world(world),'']
    for s in document['segments']:
        lines += [f"## {s['id']} · {s['start_seconds']}–{s['start_seconds']+s['duration_seconds']}秒",'',
            f"剧中时间：{s['story_time']}；地点：{s['location_zone_id']}；环境：{s['environment_light_sound']}",
            f"承前：{s['previous_causal_link']}",f"情绪重心：{s['emotional_focus']}",'',
            '段首状态：','',render_state(s['start_state']),'']
        for e in s['events']:
            lines += [f"[{e['start_s']}–{e['end_s']}秒]"]
            for c in CAST:
                a=e['characters'][c];name='周桂芳' if c=='C01' else '马涛'
                lines += [f"{name}：{a['action']}；神情：{a['expression']}；视线：{a['eyeline']}"]
            for d in e['dialogue']:
                name='周桂芳' if d['speaker']=='C01' else '马涛'
                lines += [f"**{name} [{d['start_s']}–{d['end_s']}秒]**：{d['text']}"]
            lines += ['道具：'+e['prop_change'],'']
        lines += ['段尾状态：','',render_state(s['end_state']),f"推进：{s['dramatic_change']}",f"启后：{s['next_causal_link']}",'']
    return '\n'.join(lines)
