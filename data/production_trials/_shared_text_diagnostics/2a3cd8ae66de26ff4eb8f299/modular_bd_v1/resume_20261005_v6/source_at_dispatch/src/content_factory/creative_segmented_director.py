"""Versioned beat-at-a-time storyboards with real evidence review gates."""
from copy import deepcopy
from .creative_static_visual_manifest import validate_static_manifest, style_from_manifest
from .creative_dialogue_normalization import normalize_dialogue_lock_timing as normalize_dialogue_lock_timing
import json
import hashlib
import re
from pathlib import Path
from .creative_workflow_contract import CreativeContractError, validate_shots, compile_beat_screenplay

VERSION = 'reviewed_beat_storyboard_v2'
RULES = '''本次只为script中的当前一个节拍生成分镜，whole_story_outline用于理解全片，不能拍摄后续事件。通常一拍一镜，确需表现不同主体才拆成两镜；不得用空静止镜凑数。保持本拍动作与对白次序。输出完整style/shots/media_assumptions，镜号从next_shot_number起连续SH两位编号，不输出其他节拍。style_lock非空时逐字保持style；previous_shot非空时从它的末状态承接，换机位不代表人物视线/道具重置。static_start只来自实际首态，不提前说话、移动或操作。明确每句对白的时间段、自然速度与之后的反应，不能只写整个镜头总长。issues来自实际审查时逐条解决，不扩写其他情节。上一镜purpose/cut_reason/production_choices对未来动作的预测不具有剧本效力；仅继承实际首尾与镜内执行状态，当前script和upcoming_beats的动作主体、顺序优先，发现预测错人不得照抄。每个SH仅一个连续机位，若镜内需要硬切新机位，必须拆成两个SH并分别给首尾状态和各自符合执行时长的秒数，不把两个切镜藏在一个camera字段。椅子等固定场景资产不通过切镜自动移动；已在身后的椅子可直接转向后坐下，不能无动作变为身前。'''


AUTHORITATIVE_VERSION = 'reviewed_beat_storyboard_v3'
AUTHORITATIVE_RULES = RULES + """
执行契约：当前script的before→第一句对白→during→余下对白→after，是动作主体与先后的权威；whole_story_outline仅供定位，不得重新解释正文。previous_shot仅给上一镜已成立的终态，不包含对未来的预测。已锁upcoming_beats只能约束衔接，不能提前执行。
visible_performance是本镜唯一动作时间轴：按秒写谁做什么及对白发生的窗口。start_state/end_state分别只写第一帧/最后一帧状态，不能另写动作计划。composition仅写固定构图；camera只写一套机位及连续运镜，不能藏硬切、反打或第二机位。需要换机位则分成不同SH。
production_choices必须输出空数组，制作选择写入style、固定composition或camera，不再复述表演。prompt只输出“由执行时间轴自动编译”，程序将从确定的制作字段与唯一动作时间轴编译它。purpose/cut_reason仅描述当前镜叙事作用和切出条件，不预测下一镜由谁执行什么动作。首次画面仅显示start_state，不能把visible_performance里的动作提前完成。
"""


STATIC_VISUAL_VERSION = 'reviewed_beat_storyboard_v4'
STATIC_VISUAL_RULES = AUTHORITATIVE_RULES + "\nstatic_visual_manifest是持久身份外观和固定空间几何的唯一来源；style_lock从它编译，逐字保持。人物位置、站坐、持物、视线、表情和肩部状态只能来自本镜start_state、visible_performance、end_state，不得写入持久清单；composition仅描述取景范围与景别，不重复动作或表情。道具归属不等于当前手持。场景关系使用场景坐标，不要求换机位后仍在画面同一侧。\n"


PROJECTED_VISUAL_VERSION = 'reviewed_beat_storyboard_v5'
PROJECTED_VISUAL_RULES = STATIC_VISUAL_RULES + """
同一时点每人只有一个视线目标，不能同时看道具又与对方对视。media_assumptions只记录静态制作选择/待核实资产，不陈述人物此刻姿态、不声称剧本要求某动作；动作唯一权威仍是时间轴及其首尾状态。
本版替代前述逐字复述style要求：style只输出空对象{}，由程序从static_visual_manifest注入权威静态style；禁止重复生成或修改style、不得把style_lock放入shots。prompt仍只输出占位“由执行时间轴自动编译”，production_choices=[]。这不是语义豁免：composition/start_state/visible_performance/end_state必须忠实于静态资产、完整剧本及实际衔接。
先从完整剧本推导动作前置条件：若后续将坐下，前文不能默认已坐且无起身；若后续放下，前文需合法持有；不能用新增起身/拿取操作去修自己引入的错误起点。当前首帧是本镜第一个动作发生前的状态；时间轴若走入/到达，首态不能已经在终点，末态由时间轴最后状态得出。逐字反读首态与时间轴开头，确认没有动作重复。
每句对白必须单独标出实际起止秒数，中文每字1单位、拉丁词每词2单位，以自然语速分配，绝不超过每秒5单位；例如14个单位至少2.8秒，不能塞进2秒。对白前动作、对白后反应另有可见时长，不能拿整镜总长掩盖过短语音窗口；必要时压缩无作用停顿，不能删原动作或改变对白。
"""


def project_static_style(value, manifest):
    effective = deepcopy(value)
    effective['style'] = style_from_manifest(manifest)
    return effective


def build_execution_repair(error, original_request, invalid_response):
    instruction = ('修复当前节拍分镜完整目标对象，只返回style/shots/media_assumptions三个根字段，不返回patches、信封或shots内style_lock。'
                   'style={}由程序注入；每镜必须有production_choices=[]。保留正确正文，针对实际错误修复。'
                   'original_request含完整剧本前后文、已锁manifest、上一镜终态及原阶段执行合同，全部有效。\n'
                   + original_request['segment_instructions'])
    return instruction, {'error': error, 'original_request': original_request,
                         'invalid_response': invalid_response,
                         'target_root_fields': ['style','shots','media_assumptions']}


def _save_style_projection(workflow, stage_name, original, effective):
    digest = lambda obj: hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    record = {'schema':'creative_static_style_projection/v1','source_stage':stage_name,
              'source_sha256':digest(original),'projected_sha256':digest(effective),
              'discarded_model_style':deepcopy(original.get('style')),
              'authoritative_style':deepcopy(effective['style']),
              'reason':'persistent_style_is_program_owned; performance_not_approved'}
    path = Path(workflow.run_dir) / f'{stage_name}__static_style_projection.json'
    from .creative_stage_contracts import persist_derived
    persist_derived(workflow, stage_name, path, record)


def bind_segmented_director(*, authoritative=False, static_visual=False, state_plan=False, state_plan_version=None, plan_thinking_mode=None, state_plan_guidance_version=None):
    if state_plan:
        return bind_state_plan_director(state_plan_version=state_plan_version, plan_thinking_mode=plan_thinking_mode, state_plan_guidance_version=state_plan_guidance_version)
    if static_visual:
        return {'version': PROJECTED_VISUAL_VERSION, 'prompt': PROJECTED_VISUAL_RULES, 'static_manifest_version': 'static_visual_manifest_v2'}
    return ({'version': AUTHORITATIVE_VERSION, 'prompt': AUTHORITATIVE_RULES}
            if authoritative else {'version': VERSION, 'prompt': RULES})


def project_previous_execution(shot):
    """Only the state already reached can constrain the next shot's execution."""
    if shot is None:
        return None
    return {key: deepcopy(shot[key]) for key in ('id', 'beat_id', 'end_state')}


def validate_execution_contract(value):
    """Small syntactic gates; timing/pose semantics still require real review."""
    for shot in value['shots']:
        if shot.get('production_choices') != []:
            raise CreativeContractError(f"{shot['id']} production_choices必须为空；动作仅写visible_performance")
        for field in ('camera', 'visible_performance'):
            text = str(shot.get(field, ''))
            # Negated prohibitions must not trigger a repair.
            text = re.sub(r'(?:不做|不得|禁止|没有|无|不)[^，。；;\n]{0,10}(?:硬切|切至|切到|切换[至为到]|第二机位|新机位|反打)', '', text)
            if re.search(r'硬切|切至|切到|切换[至为到]|第二机位|新机位|切换机位', text):
                raise CreativeContractError(f"{shot['id']} {field}包含镜内切镜；拆为独立SH")


def compile_execution_storyboard(value, *, static_manifest=None):
    """Keep model receipts intact; downstream prompt derives from one timeline."""
    effective = deepcopy(value)
    if static_manifest is not None:
        effective['style'] = style_from_manifest(static_manifest)
        # Never serialize the legacy style, even if a caller supplied it.
        style = json.dumps(static_manifest, ensure_ascii=False, sort_keys=True)
    else:
        style = json.dumps(effective['style'], ensure_ascii=False, sort_keys=True)
    for shot in effective['shots']:
        dialogue = json.dumps(shot['dialogue_lock'], ensure_ascii=False)
        shot['prompt'] = (
            f"制作风格与资产锁：{style}\n固定构图：{shot['composition']}\n"
            f"连续机位：{shot['camera']}\n时长：{shot['duration_seconds']}秒\n"
            f"第一帧静态状态：{shot['start_state']}\n"
            f"唯一动作时间轴：{shot['visible_performance']}\n对白锁：{dialogue}\n"
            f"最后一帧状态：{shot['end_state']}"
        )
    return effective


def _save_effective_storyboard(workflow, stage_name, value):
    path = Path(workflow.run_dir) / f'{stage_name}__effective_execution.json'
    record = {'schema': 'creative_effective_execution/v1', 'source_stage': stage_name,
              'binding_version': workflow.state['segmented_director_binding']['version'], 'output': value}
    from .creative_stage_contracts import persist_derived
    persist_derived(workflow, stage_name, path, record)


def _bound_future_context(workflow, stage_name, script, beat_index):
    """Freeze future-body context for new stages; old receipts remain byte-compatible."""
    root = Path(workflow.run_dir)
    binding_path = root / f"{stage_name}__context_binding.json"
    if binding_path.exists():
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        if binding.get("schema") != "creative_segment_future_context/v1" or binding.get("stage") != stage_name:
            raise CreativeContractError("分段后续正文绑定格式或阶段不匹配")
        if binding.get("upcoming_beats") != script["beats"][beat_index + 1:]:
            if workflow.state.get('debug_stage_validity', {}).get(stage_name) not in ('invalidated', 'needs_revision'):
                raise CreativeContractError("已锁后续剧本与分段上下文绑定不一致")
            from .creative_stage_contracts import persist, digest
            persist(root / '.creative_debug/derived' / stage_name / (digest(binding)+'.json'),
                {'source_stage':stage_name, 'path':binding_path.name, 'previous':binding}, immutable=True)
            archive = binding_path.with_name(binding_path.stem + '__superseded_' + digest(binding) + '.json')
            if archive.exists():
                raise CreativeContractError('后续上下文历史归档冲突')
            binding_path.replace(archive)
        else:
            return deepcopy(binding["context"])
    if binding_path.exists():
        return deepcopy(binding["context"])
    if (root / f"{stage_name}.json").exists() and workflow.state.get('debug_stage_validity', {}).get(stage_name) not in ('invalidated', 'needs_revision'):
        return {}
    upcoming = deepcopy(script["beats"][beat_index + 1:])
    context = {
        "upcoming_beats": upcoming,
        "locked_future_instructions": (
            "upcoming_beats是已锁完整剧本的后续节拍正文，不只是event摘要。"
            "本次仅制作当前拍，不提前拍摄后续事件；当前镜尾必须为后续正文的before、"
            "持物/视线/位置与对白顺序保留合法起点。特别核对本拍新增抬眼、转头、放下、"
            "坐下是否会让下拍已锁动作重置或重复；优先修当前分镜中的新增动作，"
            "不得擅改已锁后续剧本。审核同样检查当前段与已锁后续正文的衔接，"
            "但不得因后续分镜尚未生成而报全片缺失。"
        ),
    }
    binding = {"schema": "creative_segment_future_context/v1", "stage": stage_name,
               "upcoming_beats": upcoming, "context": context}
    root.mkdir(parents=True, exist_ok=True)
    with binding_path.open("x", encoding="utf-8") as output:
        json.dump(binding, output, ensure_ascii=False, indent=2)
    return deepcopy(context)


def generate_reviewed_beats(workflow, script, brief, context_ref):
    """Return None at an actual review gate; cached predecessors are replayable."""
    binding_version = workflow.state['segmented_director_binding']['version']
    if binding_version == STATE_PLAN_VERSION:
        return generate_reviewed_state_plan(workflow, script, brief, context_ref)
    authoritative = binding_version in (AUTHORITATIVE_VERSION, STATIC_VISUAL_VERSION, PROJECTED_VISUAL_VERSION)
    static_manifest = None
    if binding_version in (STATIC_VISUAL_VERSION, PROJECTED_VISUAL_VERSION):
        def validate_bound_manifest(value):
            validate_static_manifest(value)
            expected_version = workflow.state['segmented_director_binding'].get('static_manifest_version', 'static_visual_manifest_v1')
            if value['schema'] != expected_version:
                raise CreativeContractError(f'静态清单schema必须为当前绑定 {expected_version}')
            if value['render']['style_option_id'] != brief['selected_style_id']:
                raise CreativeContractError('静态视觉清单必须引用导演已选selected_style_id；不能缓存与后续style_lock冲突的画风')
        manifest_payload = {
            'script': script, 'director_brief': brief,
            'creative_brief': workflow.state['writer_prompt_binding']['creative_brief'],
            'material_ref': context_ref,
        }
        manifest_version = workflow.state['segmented_director_binding'].get('static_manifest_version')
        if manifest_version:
            manifest_payload['static_manifest_version'] = manifest_version
        static_manifest = workflow._stage('static_visual_manifest', 'director', manifest_payload, validate_bound_manifest)
    merged = None
    accepted = []
    outline = [{'id': b['id'], 'event': b['event'], 'duration_seconds': b['duration_seconds']}
               for b in script['beats']]
    for beat_index, beat in enumerate(script['beats']):
        partial = {**deepcopy(script), 'beats': [deepcopy(beat)], 'duration_seconds': beat['duration_seconds']}
        partial['screenplay_markdown'] = compile_beat_screenplay(partial)
        previous = deepcopy(accepted[-1]) if accepted else None
        if authoritative:
            previous = project_previous_execution(previous)
        issues, previous_draft = [], None
        for attempt in range(workflow.max_revisions + 1):
            key = f'beat_{beat_index + 1:02}_{attempt:02}'
            payload = {'material_ref': context_ref, 'script': partial, 'director_brief': brief,
                       'whole_story_outline': outline, 'previous_shot': previous,
                       'style_lock': (style_from_manifest(static_manifest) if static_manifest is not None else merged['style'] if merged else None),
                       'next_shot_number': len(accepted) + 1,
                       'segment_instructions': workflow.state['segmented_director_binding']['prompt'],
                       'issues': issues, 'previous_draft': previous_draft}
            if static_manifest is not None:
                payload['static_visual_manifest'] = deepcopy(static_manifest)
            if binding_version == PROJECTED_VISUAL_VERSION:
                payload['execution_projection_version'] = PROJECTED_VISUAL_VERSION
            def validate_chunk(value):
                if binding_version == PROJECTED_VISUAL_VERSION:
                    value = project_static_style(value, static_manifest)
                if authoritative:
                    validate_execution_contract(value)
                validate_shots(value, brief, partial)
                if payload['style_lock'] is not None and value['style'] != payload['style_lock']:
                    raise CreativeContractError('分段分镜不得改变已绑定style_lock')
                ids = [f'SH{x:02}' for x in range(len(accepted)+1, len(accepted)+len(value['shots'])+1)]
                if [x['id'] for x in value['shots']] != ids:
                    raise CreativeContractError('分段镜号必须从next_shot_number连续编号')
                first = value['shots'][0]
                if previous and first['continuity_mode'] == 'raw_tail_continuation' and first['start_state'] != previous['end_state']:
                    raise CreativeContractError('分段原始尾帧接续必须逐字承接上一已审末态；切镜需适配')
            director_key = 'director_shots__'+key
            future_context = _bound_future_context(workflow, director_key, script, beat_index)
            payload.update(deepcopy(future_context))
            shots = workflow._stage(director_key, 'director', payload, validate_chunk)
            if binding_version == PROJECTED_VISUAL_VERSION:
                projected = project_static_style(shots, static_manifest)
                _save_style_projection(workflow, director_key, shots, projected)
                shots = projected
            if authoritative:
                shots = compile_execution_storyboard(shots, static_manifest=static_manifest)
                validate_shots(shots, brief, partial)
                _save_effective_storyboard(workflow, director_key, shots)
            review_context = {'creative_brief': workflow.state['writer_prompt_binding']['creative_brief'],
                              'script': partial, 'shots': shots, 'previous_shot': previous,
                              'whole_story_outline': outline, 'review_scope': 'storyboard_segment'}
            if static_manifest is not None:
                review_context['static_visual_manifest'] = deepcopy(static_manifest)
            review_context.update(deepcopy(future_context))
            from .creative_review_gate import validate_review
            review_key = 'writer_check__segment_scope_v2_'+key
            review = workflow._stage(review_key, 'writer', review_context,
                                     lambda value: validate_review(value, review_context))
            issues = workflow._verified_review(review_key, review, review_context)
            if issues is None:
                return None
            if not issues:
                if merged is None:
                    merged = {k: deepcopy(v) for k, v in shots.items() if k != 'shots'}
                accepted.extend(deepcopy(shots['shots']))
                break
            reservation = review_key + '_revision'
            committed = workflow.state.setdefault('revision_committed', [])
            if any(i['owner'] == 'writer' for i in issues):
                workflow.state.update(status='needs_revision', unresolved_issues=issues,
                                      blocked_segment=beat['id'], reason='分段实审发现需修改已锁剧本，返回上游，未生成后段')
                workflow._save()
                return None
            if attempt == workflow.max_revisions or (reservation not in committed and workflow.state['revision_rounds'] >= workflow.max_revisions):
                workflow.state.update(status='needs_revision', unresolved_issues=issues, blocked_segment=beat['id'])
                workflow._save()
                return None
            if reservation not in committed:
                if workflow.state['calls_started'] + 2 > workflow.max_calls:
                    raise RuntimeError('当前段返修及复审调用预算不足')
                committed.append(reservation)
                workflow.state['revision_rounds'] += 1
                workflow._save()
            previous_draft = shots
        else:
            raise CreativeContractError('分段审核未完成')
    merged['shots'] = accepted
    validate_shots(merged, brief, script)
    return merged

# Opt-in only; historical bindings and prompt bytes above remain unchanged.
STATE_PLAN_VERSION = 'reviewed_beat_storyboard_v6'


def bind_state_plan_director(*, state_plan_version=None, plan_thinking_mode=None, state_plan_guidance_version=None):
    from .creative_state_plan_v6 import RULES, build_state_plan_prompt
    result = {'version': STATE_PLAN_VERSION, 'prompt': RULES,
              'static_manifest_version': 'static_visual_manifest_v2'}
    if state_plan_version is not None:
        if state_plan_version not in ('whole_film_state_plan_v2','whole_film_state_plan_v3','whole_film_action_plan_v1','whole_film_action_plan_v2'):
            raise CreativeContractError('不支持的state_plan_version')
        result['state_plan_version'] = state_plan_version
        result['prompt'] = build_state_plan_prompt(result)
    if plan_thinking_mode is not None:
        if plan_thinking_mode not in ('disabled', 'adaptive'):
            raise CreativeContractError('不支持的plan_thinking_mode')
        result['plan_thinking_mode'] = plan_thinking_mode
    if state_plan_guidance_version is not None:
        result['state_plan_guidance_version'] = state_plan_guidance_version
        result['prompt'] = build_state_plan_prompt(result)
    return result


def generate_reviewed_state_plan(workflow, script, brief, context_ref):
    """Whole-plan semantic repair loop, using the existing real review gate."""
    from .creative_state_plan_v6 import validate_state_plan, compile_state_plan
    from .creative_review_gate import validate_review
    from .creative_media_capability import audit_creative_executor
    capability = audit_creative_executor({'shots':[
        {'id':f'SH{i+1:02}', 'beat_id':b['id'], 'duration_seconds':b['duration_seconds'],
         'continuity_mode':'planned_cut_requires_adapter'} for i,b in enumerate(script['beats'])]})
    unsupported=[row['shot_id'] for row in capability['shots'] if not row['fits_single_model_request']]
    if unsupported:
        raise CreativeContractError('v6一拍一镜不能映射当前执行器时长，需显式拆镜计划：'+','.join(unsupported))
    selected = brief['selected_style_id']
    manifest_payload = {'script':script,
                        'creative_brief':workflow.state['writer_prompt_binding']['creative_brief'],
                        'director_brief':{'selected_style_id':selected},
                        'static_manifest_version':'static_visual_manifest_v2',
                        'material_ref':context_ref}
    def check_manifest(value):
        validate_static_manifest(value)
        if value['schema']!='static_visual_manifest_v2' or value['render']['style_option_id']!=selected:
            raise CreativeContractError('v6静态清单版本/选定画风不匹配')
    manifest=workflow._stage('static_visual_manifest','director',manifest_payload,check_manifest)
    issues=[]; previous=None
    for attempt in range(workflow.max_revisions+1):
        key=f'director_state_plan__{attempt:02}'
        payload={'script':script,'creative_brief':manifest_payload['creative_brief'],
                 'static_visual_manifest':manifest,'material_ref':context_ref,
                 'issues':issues,'previous_draft':previous}
        plan_version=workflow.state['segmented_director_binding'].get('state_plan_version')
        if plan_version:
            payload['state_plan_version']=plan_version
        thinking_mode=workflow.state['segmented_director_binding'].get('plan_thinking_mode')
        if thinking_mode is not None:
            payload['plan_thinking_mode']=thinking_mode
        guidance_version=workflow.state['segmented_director_binding'].get('state_plan_guidance_version')
        if guidance_version is not None:
            payload['state_plan_guidance_version']=guidance_version
        def check_plan(value):
            from .creative_state_plan_guidance import validate_guided_structure
            validate_guided_structure(value,payload)
            if value.get('schema') != (plan_version or 'whole_film_state_plan_v1'):
                raise CreativeContractError('state_plan与已锁绑定版本不符')
            validate_state_plan(value,script,manifest)
            compiled=compile_state_plan(value,script,manifest)
            validate_shots(compiled,brief,script)
        # Semantic v2 revision adopts one complete model-produced plan and
        # reviews all beats. Only legacy v1 keeps its historical patch route.
        # Technical contract repairs remain separately bounded in _stage.
        if plan_version == 'whole_film_action_plan_v1' and previous is not None:
            payload['plan_patch_base']=previous
            payload['plan_patch_issues']=issues
        plan=workflow._stage(key,'director',payload,check_plan)
        shots=compile_state_plan(plan,script,manifest)
        _save_effective_storyboard(workflow,key,shots)
        context={'creative_brief':payload['creative_brief'],'script':script,'shots':shots,
                 'static_visual_manifest':manifest,'state_plan':plan,
                 'review_scope':'whole_film_state_plan'}
        if plan_version in ('whole_film_action_plan_v1', 'whole_film_action_plan_v2'):
            if plan_version == "whole_film_action_plan_v2":
                from .creative_action_plan_v2 import schedule_action_plan
            else:
                from .creative_action_plan_v1 import schedule_action_plan
            scheduled,timing_report=schedule_action_plan(plan,script,manifest)
            context['scheduled_state_plan']=scheduled
            context['scheduling_report']=timing_report
            for suffix,artifact in [('scheduled_state_plan',scheduled),('scheduling_report',timing_report)]:
                artifact_path=Path(workflow.run_dir)/(key+'__'+suffix+'.json')
                if artifact_path.exists() and json.loads(artifact_path.read_text(encoding='utf-8'))!=artifact:
                    raise CreativeContractError('已绑定程序排时产物变化，拒绝覆盖')
                artifact_path.write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
        review_key=f'writer_check__state_plan_{attempt:02}'
        review=workflow._stage(review_key,'writer',context,lambda value:validate_review(value,context))
        issues=workflow._verified_review(review_key,review,context)
        if issues is None: return None
        if not issues:
            accepted_path=Path(workflow.run_dir)/'STATE_PLAN.json'
            record={'schema':'creative_reviewed_state_plan/v1','source_stage':key,
                    'review_stage':review_key,'plan':plan}
            if accepted_path.exists():
                if json.loads(accepted_path.read_text(encoding='utf-8'))!=record:
                    raise CreativeContractError('已审核STATE_PLAN与当前回执不同，拒绝覆盖')
            else:
                accepted_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            if plan_version in ('whole_film_action_plan_v1', 'whole_film_action_plan_v2'):
                for filename,artifact in [('SCHEDULED_STATE_PLAN.json',scheduled),('SCHEDULING_REPORT.json',timing_report)]:
                    artifact_path=Path(workflow.run_dir)/filename
                    if artifact_path.exists() and json.loads(artifact_path.read_text(encoding='utf-8'))!=artifact:
                        raise CreativeContractError('已审程序排时产物变化，拒绝覆盖')
                    artifact_path.write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
            return shots
        if any(issue['owner']=='writer' for issue in issues):
            workflow.state.update(status='needs_revision',unresolved_issues=issues,
                                  reason='全片计划实审发现已锁剧本问题，返回上游')
            workflow._save(); return None
        reservation=review_key+'_revision'
        committed=workflow.state.setdefault('revision_committed',[])
        if attempt==workflow.max_revisions or (reservation not in committed and workflow.state['revision_rounds']>=workflow.max_revisions):
            workflow.state.update(status='needs_revision',unresolved_issues=issues,
                                  reason='全片计划实审未通过且本轮修订额度已用完')
            workflow._save(); return None
        if reservation not in committed:
            if workflow.state['calls_started']+2>workflow.max_calls:
                raise RuntimeError('全片计划返修及复审预算不足')
            committed.append(reservation); workflow.state['revision_rounds']+=1; workflow._save()
        previous=plan
    raise CreativeContractError('全片计划审核未完成')
