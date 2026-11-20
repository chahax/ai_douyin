"""New whole-flow run. Old sources, failures, spend and media stay unchanged.

MiniMax writes complete script, whole direction and local acting. DeepSeek
reviews the same complete candidate. Program derives IDs/hashes/state/timing
and outgoing coverage. First media establishes casting; continuations require
explicit human approval and actual role-to-image mapping, never an inferred one.
"""
from pathlib import Path
from copy import deepcopy
import argparse
import json
import subprocess
import sys
from jsonschema import Draft202012Validator

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_json_document_transport_v1 as transport
from scripts import run_selected_script_video_trial_v6 as prior
from scripts import run_selected_script_continuation_v8 as parent
from scripts.creative_bounded_format_role_clients_v1 import BoundedFormatRoleClients
from src.content_factory import creative_video_trial_contract_v1 as source
from src.content_factory import creative_shared_production_contract_v1 as shared
from src.content_factory import creative_complete_production_pipeline_v1 as pipeline
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig
from src.content_factory.creative_legal_short_seedance_execution_v1 import reserve_media_attempt
from src.content_factory.media_review_policy import mark_saved_candidate
from src.content_factory.creative_stage_contracts import persist
from scripts.run_legal_current_production_v10_20261010 import validate_saved_metadata

ROOT = PROJECT / 'data/production_revisions/shared_full_production_20261012/run_01'
OUT = PROJECT / 'data/video_generation/shared_full_production_20261012/run_01/opening_01'
BRIEF_SOURCE = PROJECT / 'data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_15/INPUT.json'
OLD_SCRIPT = BRIEF_SOURCE.parent / 'versions/07/FULL_SCRIPT.json'
OLD_DECISION = BRIEF_SOURCE.parent / 'versions/07/AUTOMATIC_DECISION.json'
USER_REQUEST = '这个问题整个流程应该修复然后再生产跑一轮，整个需要从头开始吧'
SID = 'SHARED_FULL_20261012_OPENING01'
MODEL, LOGICAL = prior.MODEL, prior.LOGICAL
MAX_CONTENT_REVISIONS = 2


def obj(fields):
    return {'type': 'object', 'additionalProperties': False, 'properties': fields, 'required': list(fields)}


TEXT = {'type': 'string', 'minLength': 1}


def script_schema(brief):
    step = obj({'kind': {'enum': ['action', 'dialogue']}, 'speaker': {'enum': ['', *brief['constraints']['allowed_character_ids']]}, 'text': TEXT})
    step['allOf'] = [
        {'if': {'properties': {'kind': {'const': 'action'}}}, 'then': {'properties': {'speaker': {'const': ''}}}},
        {'if': {'properties': {'kind': {'const': 'dialogue'}}}, 'then': {'properties': {'speaker': {'enum': brief['constraints']['allowed_character_ids']}}}}]
    beat = obj({'id': TEXT, 'trigger': TEXT, 'event': TEXT, 'steps': {'type': 'array', 'minItems': 1, 'maxItems': 10, 'items': step}})
    return obj({'title': TEXT, 'premise': TEXT,
                'beats': {'type': 'array', 'minItems': 3, 'maxItems': 9, 'items': beat},
                'selected_candidate_id': {'const': brief['selected_candidate_id']}})


def validate_script(value, brief):
    Draft202012Validator(script_schema(brief)).validate(value)
    if len({b['id'] for b in value['beats']}) != len(value['beats']):
        raise ValueError('duplicate beat IDs')
    rows = source.catalog(value)
    if {x['speaker'] for x in rows.values() if x['kind'] == 'dialogue'} != set(brief['constraints']['allowed_character_ids']):
        raise ValueError('exact closed dialogue cast required')
    if any(source.spoken_seconds(x) + .3 > 15 for x in rows.values()):
        raise ValueError('one full utterance exceeds 15 seconds at normal speed; complete revision required')
    return {'script_sha256': control.digest(value), 'source_steps': len(rows), 'structure_only': True, 'creative_quality_passed': False}


SCRIPT_CHECKS = ['confirmed_facts_and_no_new_business_claims', 'initial_physical_state',
                 'company_pressure_then_first_refusal_then_private_request_then_second_refusal',
                 'single_paper_push_and_ending_causality', 'natural_spoken_language_and_referents',
                 'information_emotion_and_visible_conflict', 'closed_cast_scene_and_complete_story']
PRODUCTION_CHECKS = ['exact_whole_source_and_dialogue_coverage', 'all_segments_shared_identity_projection',
                     'cross_segment_state_and_prop_preconditions', 'stimulus_response_and_actor_objectives',
                     'normal_speech_action_overlap_and_reaction_windows', 'whole_direction_and_cut_reasons',
                     'current_prompt_future_isolation', 'casting_and_actual_provider_limitations']


def review_schema(checks, refs):
    checkrows = [obj({'check': {'const': key}, 'status': {'enum': ['pass', 'fail', 'unknown']},
        'source_refs': {'type': 'array', 'items': {'enum': refs}, 'uniqueItems': True}, 'reason': TEXT}) for key in checks]
    schema = obj({'checks': {'type': 'array', 'prefixItems': checkrows, 'items': False, 'minItems': len(checks), 'maxItems': len(checks)},
        'revision_requirements': {'type': 'array', 'maxItems': 12, 'items': TEXT},
        'review_limitations': {'type': 'array', 'maxItems': 8, 'items': TEXT}})
    schema['allOf'] = [
        {'if': {'properties': {'checks': {'items': {'properties': {'status': {'const': 'pass'}}, 'required': ['status']}}}},
         'then': {'properties': {'revision_requirements': {'maxItems': 0}}}},
        {'if': {'properties': {'checks': {'contains': {'properties': {'status': {'enum': ['fail','unknown']}}, 'required': ['status']}}}},
         'then': {'properties': {'revision_requirements': {'minItems': 1}}}}]
    return schema


def validate_review(value, schema):
    Draft202012Validator(schema).validate(value)
    failures = any(x['status'] != 'pass' for x in value['checks'])
    if not failures and value['revision_requirements']:
        raise ValueError('limitations cannot masquerade as content revisions')
    if failures and not value['revision_requirements']:
        raise ValueError('failed/unknown checks need concrete revision requirements')
    return {'needs_revision': failures, 'has_explicit_fail': any(x['status']=='fail' for x in value['checks']),
            'has_unknown': any(x['status']=='unknown' for x in value['checks']),
            'full_same_candidate_review': True, 'actual_media_quality_passed': False}


def runtime():
    a = control.read(ROOT / 'ANCHOR.json')
    return control.ContinuationRuntime(PROJECT, ROOT, [PROJECT / p for p in a['runtime_sources']],
        a['inherited'], a['models'], inherited_guard=lambda: prior.verify_files(a['parent_files']),
        client_factory=BoundedFormatRoleClients, quota_state=None)


def prepare():
    if not (ROOT / 'ANCHOR.json').exists():
        ledger = control.read(parent.ROOT / 'CALL_LEDGER.json')
        parent.runtime().check(ledger)
        inherited, receipts = prior.inherited_known_parent(ledger, parent.ROOT)
        if [r['ordinal'] for r in receipts] != [510, 511]:
            raise ValueError('latest exact known text lineage required')
        rejection = control.read(parent.OUT / 'receipt.human_review.json')
        if rejection.get('decision') != 'rejected' or rejection.get('decision_source') != 'explicit_user_statement':
            raise ValueError('original identity-failure human feedback required')
        original = control.read(BRIEF_SOURCE)
        inp = {'brief': original['brief'], 'reference_fulltext': original['reference_fulltext'],
            'old_script': control.read(OLD_SCRIPT), 'old_automatic_decision': control.read(OLD_DECISION),
            'old_video_rejection': rejection, 'old_script_as_diagnostic_only': True,
            'casting': {'status': 'creative_choice_not_visual_approval', 'user_preference_reply': '采用这个选角，重拍首段',
                'assumption': '本轮从首段重新选角，不把旧画面未知人物强行命名',
                'xiaolin': {'gender_presentation': '男性', 'age_presentation': '二十多岁',
                    'appearance': '东亚面孔，黑色短发，无胡须，自然五官', 'wardrobe': '浅蓝长袖衬衫，深灰长裤，蓝色挂绳工牌'},
                'zhou': {'gender_presentation': '女性', 'age_presentation': '四十岁左右',
                    'appearance': '东亚面孔，黑色齐肩直发，自然妆容', 'wardrobe': '米色西装外套，白色内搭，深色长裤'}},
            'environment': '同一小会议室，深灰长桌，两把椅子，浅色墙与玻璃隔断，柔和中性办公室光线，门在周姐离开的动线上',
            'prop_appearance': {'application': '一张白色A4自愿离职申请，原因栏预填个人原因，签名栏空白',
                'pen': '一支黑色签字笔', 'folder': '黑色文件夹'},
            'provider_evidence': {'url': 'https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh',
                'checked_date': '2026-10-12', 'text': 'Seedance 2.0系列支持文生视频与首帧生视频；Seedance 2.0 mini支持480p、720p；return_last_frame返回尾帧。能力声明不保证人物身份或声线一致。'},
            'production_preferences': control.read(parent.ROOT / 'INPUT.json')['production_preferences']}
        scope = {'schema': 'shared_full_production_user_scope/v1', 'user_statement': USER_REQUEST,
            'complete_new_script_required': True, 'complete_whole_direction_and_performance_required': True,
            'max_script_content_revisions': MAX_CONTENT_REVISIONS, 'max_new_video_submissions': 1,
            'max_known_complete_stage_content_revisions': MAX_CONTENT_REVISIONS,
            'opening_only_before_human_review': True, 'batch_authorized': False, 'publishing_authorized': False,
            'automatic_retry': False, 'budget_reset': False, 'old_unknown_and_failure_history_preserved': True,
            'first_video_role': 'new_casting_baseline_awaiting_human_review', 'subsequent_requires_actual_identity_mapping': True,
            'casting_confirmation': '采用这个选角，重拍首段'}
        control.write(ROOT / 'INPUT.json', inp, True); control.write(ROOT / 'USER_SCOPE.json', scope, True)
        claim_key = control.digest({'user_statement': USER_REQUEST, 'parent_ledger_sha256': control.sha_file(parent.ROOT/'CALL_LEDGER.json'),
            'rejected_candidate': rejection['candidate_identity_sha256'], 'stage': 'new_shared_whole_production_v1'})
        claim_path = PROJECT / 'data/creative_continuation_stages' / claim_key / 'CLAIM.json'
        control.write(claim_path, {'stage_key': claim_key, 'root': str(ROOT), 'scope': scope, 'parent_spend': inherited}, True)
        files = [parent.ROOT / n for n in ['CALL_LEDGER.json','AUTHORIZATION.json','ANCHOR.json','INPUT.json']]
        files += [parent.ROOT/r['receipt'] for r in ledger['calls']]
        files += [Path(p) for p in control.read(parent.ROOT/'ANCHOR.json')['parent_files']]
        files += [parent.OUT/n for n in ['receipt.json','receipt.human_review.json','PLAN.json','PROMPT.txt']]
        files += [BRIEF_SOURCE, OLD_SCRIPT, OLD_DECISION, claim_path]
        sources = [p for folder in [PROJECT/'src',PROJECT/'scripts'] for p in folder.rglob('*.py')]
        sources += [ROOT/n for n in ['INPUT.json','USER_SCOPE.json','ANCHOR.json']]
        control.write(ROOT/'ANCHOR.json', {'inherited': inherited, 'models': ledger['model_configs'],
            'parent_files': {str(p): control.sha_file(p) for p in files},
            'runtime_sources': [p.relative_to(PROJECT).as_posix() for p in sources]}, True)
    return runtime().prepare()


def wire(role, rule, value, schema, cap=7000):
    result = {'role': role, 'model': runtime().models[role]['model'], 'operator_version': 'shared_complete_production/v1',
        'parameters': {'temperature': .4, 'thinking': 'disabled', 'max_completion_tokens': cap},
        'messages': [{'role':'system','content':rule}, {'role':'user','content':json.dumps(value,ensure_ascii=False)}], 'structured_schema':schema}
    if role == 'writer':
        result.update(output_transport=transport.VERSION, inner_document_schema=deepcopy(schema),
            structured_schema=transport.build_envelope_schema(), messages=transport.build_messages(result['messages'],schema))
    return result


def dispatch(label, role, rule, inp, schema, validate, cap=7000):
    control.write(ROOT / (label.upper()+'_INPUT.json'), inp, True)
    return runtime().dispatch(label, wire(role,rule,inp,schema,cap), validate)


def known_complete_rejected_native(receipt):
    """Original failed JSON for feedback only; never a converted accepted result."""
    m=receipt.get('response_metadata',{})
    if (receipt.get('status')!='contract_rejected' or receipt.get('failure',{}).get('category') not in ('state_contract','validation')
        or m.get('response_body_complete') is not True or m.get('finish_reason') not in ('tool_calls','stop')
        or type(m.get('total_tokens')) is not int or m['total_tokens']<0): return None
    try:
        value=receipt.get('document_output') or control.strict_json(receipt['output']['payload_json'])
    except (ValueError,KeyError,TypeError): return None
    if value.get('availability')=='unknown': return None
    return value


def complete_stage(label, rule, inp, schema, validate, cap=7000):
    """Bounded new content revisions, never SDK/unknown transport retries."""
    failures=[]
    for index in range(MAX_CONTENT_REVISIONS+1):
        value=deepcopy(inp)
        if failures: value['previous_complete_rejected_versions']=deepcopy(failures)
        result=dispatch(label+f'_r{index}','writer',rule+' 若收到旧完整失败稿，提交完整新原生版本，不拼接、不回填。',value,schema,validate,cap)
        if result['status']=='contract_valid': return result
        native=known_complete_rejected_native(result)
        if native is None: return result
        failures.append({'ordinal':result['ordinal'],'complete_rejected_native':native,'validation_error':result.get('validation_error'),
            'adopted':False,'reported_tokens':result['response_metadata']['total_tokens']})
    return result


def document(receipt):
    if receipt['status'] != 'contract_valid':
        raise ValueError('original stage unresolved/rejected; not reused or automatically retried')
    return prior.received_document(receipt)


def source_text(script):
    lines = ['# '+script['title'], '', script['premise'], '']
    for b in script['beats']:
        lines += ['## '+b['id']+' '+b['event'], '', '触发：'+b['trigger'], '']
        for s in b['steps']:
            label = {'xiaolin':'小林','zhou':'周姐'}.get(s['speaker'],s['speaker'])
            lines += [('**'+label+'**：'+s['text']) if s['kind']=='dialogue' else s['text'], '']
    return '\n'.join(lines)


SCRIPT_RULE = ('从冻结brief的事实和初态生成完整可制作新稿，旧稿只作已知错误诊断，不改旧稿、不拼接旧新句子。'
    '先公司立场劝签，小林发现个人原因与公司决定矛盾并明确第一次拒绝，周姐才从公司立场转为体谅她帮交差，小林回应再拒绝。'
    '纸笔只一次送到小林近桌沿，停止在那里直到周姐收回；周姐独自出门，小林留坐，门关后短呼一口气，争议未解决。'
    '不新增今天上午/手续今天走完等办理时限、法律结论、承诺、人物或道具。对白自然日常，称谓施事明确；不用流程/省心/核对等空泛口号。'
    '借鉴R01信息反差、行动目的、刺激后反应，不照搬剧情；动作和说话可同时进行，不拆机械微表情清单。单句在3.3发音字/秒下留反应不超过15秒。'
    '保持源初态：申请在周姐面前桌面朝上，笔在申请旁无人持，文件夹在周姐一侧；位置关系不等于人物所有权。'
    '只提交完整JSON正文，不复制SHA或来源引用清单，不长篇自我分析。')


REVIEW_RULE = ('全文审查同一完整新稿，每项给实际source_refs与理由。冻结brief事实/初态优先，按steps发生判断，不把摘要声称当作演出。'
    '严格检查公司劝签→发现矛盾/质问→第一次明确拒绝→私人求助→第二次拒绝→收未签纸笔→周姐独自出门→门关小林短呼气。'
    '检查一次推纸到近桌沿、纸不越推越远；初态桌面位置和无持有人不混成所有权；不要求剧本填技术anchor类型常量。'
    '新增办理日期、业务承诺、合同事实、赔偿结论或含混口号是必修。私人交差求助不是公司后续承诺，不把个人现场请求误判法律规定。'
    '只对真实当前内容错误给fail或unknown+具体返修；无模型声线绑定、未看视频等边界写review_limitations，不能据此否定文本。'
    '全部pass时revision_requirements为空，不宣称视频或用户审美通过。')


def draft():
    prepare(); x=control.read(ROOT/'INPUT.json'); brief=x['brief']; prior_feedback=[]
    for index in range(MAX_CONTENT_REVISIONS+1):
        label=f'full_script_{index}'
        inp={k:deepcopy(x[k]) for k in ['brief','reference_fulltext','casting','production_preferences']}
        inp.update(previous_complete_candidates=prior_feedback, user_goal='完整导演表演视频生产验证，从全流程生成新正文',
            old_failed_source_diagnostics=x['old_automatic_decision']['revision_requirements'] if index==0 else [])
        r=dispatch(label,'writer',SCRIPT_RULE,inp,script_schema(brief),lambda v:validate_script(v,brief),6500)
        if r['status']!='contract_valid':
            native=known_complete_rejected_native(r)
            if native is not None and index<MAX_CONTENT_REVISIONS:
                prior_feedback.append({'complete_rejected_native':native,'validation_error':r.get('validation_error'),'writer_ordinal':r['ordinal'],'adopted':False})
                continue
            return stop('script_response_needs_attention',r)
        s=document(r); p=ROOT/f'script_versions/{index:02d}'; control.write(p/'FULL_SCRIPT.json',s,True)
        (p/'FULL_SCRIPT.md').write_text(source_text(s),encoding='utf-8')
        schema=review_schema(SCRIPT_CHECKS,list(source.catalog(s)))
        review=dispatch(f'full_script_review_{index}','director',REVIEW_RULE,
            {'brief':brief,'full_script':s,'script_sha256':control.digest(s),'source_catalog':source.catalog(s),
             'reference_fulltext':x['reference_fulltext'],'casting':x['casting']},schema,lambda v:validate_review(v,schema),5500)
        if review['status']!='contract_valid': return stop('script_review_response_needs_attention',review)
        q=document(review); control.write(p/'FULL_REVIEW.json',q,True)
        if not review['validation']['needs_revision']:
            control.write(ROOT/'ADOPTED_SOURCE.json',{'script':s,'script_sha256':control.digest(s),
                'writer_ordinal':r['ordinal'],'review_ordinal':review['ordinal'],'machine_text_review_passed':True,
                'user_adopted':False,'original487_decision_unchanged':True,'actual_media_quality_passed':False},True)
            return {'status':'complete_source_ready_for_director',**runtime().summary()}
        if review['validation']['has_unknown'] and not review['validation']['has_explicit_fail']:
            return stop('script_review_unknown_no_redispatch',review)
        prior_feedback.append({'complete_native_script':s,'full_review':q,'writer_ordinal':r['ordinal'],'review_ordinal':review['ordinal']})
    return stop('bounded_complete_script_revision_exhausted',review)


def stop(status, receipt=None):
    result={'status':status,'new_video_calls':0,'actual_media_quality_passed':False,**runtime().summary()}
    if receipt: result.update(last_ordinal=receipt['ordinal'],last_response_status=receipt['status'],failure=receipt.get('failure'))
    control.write(ROOT/('STOP_'+status.upper()+'.json'),result,True)
    return result


def build_manifest(script, x):
    def bank(sid, kind, value):
        text=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')) if not isinstance(value,str) else value
        return {'source_id':sid,'kind':kind,'text':text,'sha256':shared.text_sha256(text)}
    evidence=[bank('current_casting','source_brief',x['casting']),bank('current_environment','source_brief',x['environment']),
        bank('current_props','source_brief',x['prop_appearance']),bank('provider_documentation','provider_documentation',x['provider_evidence']['text']),
        bank('full_current_script','source_script',script)]
    def refs(sid): return [{'source_id':sid,'quote':next(v['text'] for v in evidence if v['source_id']==sid)}]
    policy={'status':'verified','provider_id':'ark_api','model':MODEL,'identity_reference_mode':'first_frame',
        'allowed_reference_modes':['text_to_video_bootstrap','first_frame'],'allows_actor_asset_mapping':None,
        'sources':refs('provider_documentation'),'reason':'文生首段和首帧模式已核对；具体双人视觉对应仍须人工确认，声线无绑定'}
    context={k:deepcopy(x['brief'][k]) for k in ['characters','scenes','initial_state']}
    manifest=shared.build_pending_manifest(script,context,policy,evidence)
    for actor in manifest['actors']:
        actor['profile']={field:shared.known(x['casting'][actor['id']][field],refs('current_casting')) for field in shared.PROFILE_FIELDS}
    for scene in manifest['scenes']: scene['appearance']=shared.known(x['environment'],refs('current_environment'))
    for prop in manifest['props']: prop['appearance']=shared.known(x['prop_appearance'][prop['id']],refs('current_props'))
    shared.validate_shared_manifest(manifest,script)
    return manifest


def bootstrap_dynamic_state(manifest, x):
    # Initial projection from the same frozen source, no inferred frame pixels.
    bank=next(v for v in manifest['provenance_catalog'] if v['source_id']=='frozen_source_context')
    refs=[{'source_id':bank['source_id'],'quote':bank['text']}]
    initial=x['brief']['initial_state']
    state={'global_manifest_sha256':control.digest(manifest),'scene_id':initial['scene_id'],'previous_scene_id':None,
        'completed_source_refs':[], 'actors':[], 'props':[]}
    for actor in initial['character_states']:
        state['actors'].append({'id':actor['id'],'pose':shared.known(actor['expected_state'],refs),
            'emotion':shared.unknown('源初态未指定具体表情，不把当前知识状态充当已审面部情绪')})
    for prop in initial['prop_states']:
        state['props'].append({'id':prop['id'],'holder':shared.known(prop['holder_character_id'],refs),
            'support':shared.known({'entity_type':'scene','entity_id':initial['scene_id']},refs),
            'orientation':shared.known('面朝上',refs) if '面朝上' in prop['expected_state'] else shared.unknown('源初态未指定具体朝向，按当前源动作和共用道具规格建立')})
    return state


def text():
    prepare()
    if not (ROOT/'ADOPTED_SOURCE.json').exists():
        result=draft()
        if result['status']!='complete_source_ready_for_director': return result
    x=control.read(ROOT/'INPUT.json'); adopted=control.read(ROOT/'ADOPTED_SOURCE.json'); script=adopted['script']
    manifest=build_manifest(script,x); control.write(ROOT/'SHARED_MANIFEST.json',manifest,True)
    context={k:deepcopy(x['brief'][k]) for k in ['characters','scenes','initial_state']}
    initial=pipeline.build_initial_state(context,manifest)
    control.write(ROOT/'PLANNED_INITIAL_STATE.json',initial,True)
    inp={'full_current_script':script,'source_catalog':source.catalog(script),'shared_manifest':manifest,
        'planned_initial_state':initial,'reference_fulltext':x['reference_fulltext'],'production_preferences':x['production_preferences']}
    schema=pipeline.whole_direction_schema(script,manifest)
    r=complete_stage('whole_direction',pipeline.RULE+'本阶段只提交整片导演segments及其终点，不提交表演或state；首段须包含公司宣布决定的原对白，建立双人及冲突。',
        inp,schema,lambda v:pipeline.compile_direction(v,script,manifest),6500)
    if r['status']!='contract_valid': return stop('whole_direction_needs_attention',r)
    direction=pipeline.compile_direction(document(r),script,manifest)
    control.write(ROOT/'WHOLE_DIRECTION.json',direction,True)
    performances=[]; state=initial; completed=[]
    for segment in direction['segments']:
        refs=segment['source_refs']; label='performance_'+segment['segment_id'].lower()
        schema=pipeline.performance_schema(script,manifest,segment,state,completed)
        perf_input={'current_direction':segment,'current_sources':{ref:source.catalog(script)[ref] for ref in refs},
            'completed_stimulus_catalog':{ref:source.catalog(script)[ref] for ref in completed},
            'shared_manifest':manifest,'planned_initial_state':state,'completed_source_refs':completed,
            'reference_fulltext':x['reference_fulltext'],'production_preferences':x['production_preferences'],
            'actual_future_tail_not_created':True,'planned_state_is_not_pixel_approval':True}
        def compile_local(v): return pipeline.compile_performance(v,script,manifest,segment,state,completed)
        r=complete_stage(label,pipeline.RULE+'本阶段只提交当前segment的完整演法、排时与ending_state。state中knowledge/emotion用不复抄对白的概括；未知字段保留null，不能补写未来动作。',perf_input,schema,compile_local,7500)
        if r['status']!='contract_valid': return stop(label+'_needs_attention',r)
        compiled=compile_local(document(r)); performances.append(compiled)
        control.write(ROOT/'performances'/ (segment['segment_id']+'.json'),compiled,True)
        state=compiled['planned_ending_state']; completed+=refs
    complete=pipeline.compile_complete(direction,performances,script,manifest,initial)
    control.write(ROOT/'COMPLETE_PRODUCTION_COMPILED.json',complete,True)
    planned_prompts=[pipeline.render_prompt(p,script,manifest) for p in performances]
    bootstrap_state=bootstrap_dynamic_state(manifest,x)
    projection=shared.compile_segment_context(manifest,script,bootstrap_state,direction['segments'][0]['source_refs'],bootstrap=True)
    first_prompt=pipeline.render_prompt(performances[0],script,manifest,shared_context=projection)
    coverage=shared.validate_provider_request_coverage(projection,first_prompt,[], 'ark_api',MODEL)
    control.write(ROOT/'BOOTSTRAP_CONTEXT.json',projection,True)
    control.write(ROOT/'FINAL_PROMPTS.json',{'all_planned_prompts':planned_prompts,'opening_actual_prompt':first_prompt,
        'opening_shared_request_coverage':coverage,'later_actual_tail_projection_pending_human_review':True},True)
    schema=review_schema(PRODUCTION_CHECKS,list(source.catalog(script)))
    review_in={'brief':x['brief'],'full_current_script':script,'source_catalog':source.catalog(script),
        'shared_manifest':manifest,'whole_direction':direction,'complete_compilation':complete,'all_local_performances':performances,
        'all_planned_video_prompts':planned_prompts,'opening_actual_video_prompt':first_prompt,'opening_shared_projection':projection,
        'reference_fulltext':x['reference_fulltext'],'source_full_review_binding':{'writer_ordinal':adopted['writer_ordinal'],'review_ordinal':adopted['review_ordinal']},
        'scope':control.read(ROOT/'USER_SCOPE.json'),'voice_binding':'unbound','pixel_identity_verified':False}
    review=dispatch('whole_production_review','director',
        '全文审查同源完整正文、整片导演、所有段表演、状态连续、确定性排时和全部实际计划prompt，不能只审首段。'
        '逐段核对source完整一次、原对白不改、动作与对白自然重叠不提速、观察对象/新增信息/刺激反应/切点和反应窗口。'
        '每段共用双人性别年龄外貌服装一致，演法不能改身份或加人换座；从上一段planned_ending_state接下一段planned_initial_state，道具holder/support/orientation真实变化须当段动作授权。'
        'state_changes原文quote真实不等于语义支持：确认每个变化的source确实足以成立；没有变化就保留原值，未定义值可明确unknown。'
        '首段实际视频prompt已绑定完整共用档案，后段仍只是计划，需要用户批准前段原尾帧和确认双人视觉对应后才能派发，不能以缺未来tail否定全部文字。'
        '本次新的创作选角只有人类性别年龄方向同意，没有画面批准或声线绑定；第一段可建立人物基准，并需人工审查。'
        '媒体边界和声线风险写review_limitations；真实正文/调度矛盾写fail/unknown与必修改，不把接口成功当质量通过。',
        review_in,schema,lambda v:validate_review(v,schema),6500)
    if review['status']!='contract_valid' or review['validation']['needs_revision']: return stop('whole_production_review_needs_attention',review)
    handoff={'schema':'shared_whole_production_handoff/v1','script_sha256':control.digest(script),
        'global_manifest_sha256':control.digest(manifest),'complete_compilation_sha256':control.digest(complete),
        'whole_source_coverage_complete':True,'whole_film_performance_complete':True,
        'text_full_review_passed':True,'user_creative_quality_passed':False,'actual_media_quality_passed':False,
        'source_writer_ordinal':adopted['writer_ordinal'],'source_review_ordinal':adopted['review_ordinal'],
        'production_review_ordinal':review['ordinal'],'review_limitations':document(review)['review_limitations'],
        'global_actor_profiles_projected_into_opening':coverage,'new_media_authorized':1,
        'formal_continuations_blocked_until_human_identity_mapping_and_tail_approval':True,
        'historical_accounting_not_reset':True,'automatic_retry':False,'old487_quality_decision_unchanged':True}
    control.write(ROOT/'VIDEO_HANDOFF.json',handoff,True)
    deliver=ROOT/'DELIVERABLE'; deliver.mkdir(parents=True,exist_ok=True)
    (deliver/'FULL_SCRIPT.md').write_text(source_text(script),encoding='utf-8')
    rows=[source_text(script),'\n# 整片导演与实际表演计划\n', '说明：以下是完整文本制作交接，视频尚未人工审核。']
    for segment,prompt in zip(direction['segments'],planned_prompts):
        rows += ['\n## '+segment['segment_id'],json.dumps(segment,ensure_ascii=False,indent=2),'\n'+prompt]
    rows+=['\n# 本次实际首段提示词\n',first_prompt,'\n# 未解决边界\n','首段双人人物需用户核对；尚无稳定声线输入；后段原尾帧与视觉映射未产生，不能自动续段。']
    (deliver/'DIRECTOR_PERFORMANCE_HANDOFF.md').write_text('\n\n'.join(rows),encoding='utf-8')
    return {'status':'complete_text_production_handoff_ready','segments':len(performances),'total_seconds':complete['total_duration_seconds'],**runtime().summary()}


def make_plan():
    rt=runtime(); rt.check(control.read(rt.ledger))
    h=control.read(ROOT/'VIDEO_HANDOFF.json'); s=control.read(ROOT/'ADOPTED_SOURCE.json')['script']
    m=control.read(ROOT/'SHARED_MANIFEST.json'); complete=control.read(ROOT/'COMPLETE_PRODUCTION_COMPILED.json')
    if h.get('text_full_review_passed') is not True or h.get('new_media_authorized')!=1:
        raise ValueError('complete same-source production review required')
    expected=pipeline.compile_complete(complete['direction'],complete['performances'],s,m,complete['initial_state'])
    if expected!=complete or h['complete_compilation_sha256']!=control.digest(complete):
        raise ValueError('whole source/performance/state changed')
    x=control.read(ROOT/'INPUT.json'); first=complete['performances'][0]
    state=bootstrap_dynamic_state(m,x)
    context=shared.compile_segment_context(m,s,state,first['source_refs'],bootstrap=True)
    if context!=control.read(ROOT/'BOOTSTRAP_CONTEXT.json'):
        raise ValueError('actual shared projection changed')
    prompt=pipeline.render_prompt(first,s,m,shared_context=context)
    if prompt!=control.read(ROOT/'FINAL_PROMPTS.json')['opening_actual_prompt']:
        raise ValueError('actual video prompt changed after full text review')
    coverage=shared.validate_provider_request_coverage(context,prompt,[],'ark_api',MODEL)
    files=[ROOT/n for n in ['INPUT.json','USER_SCOPE.json','ADOPTED_SOURCE.json','SHARED_MANIFEST.json',
        'WHOLE_DIRECTION.json','COMPLETE_PRODUCTION_COMPILED.json','VIDEO_HANDOFF.json','BOOTSTRAP_CONTEXT.json','FINAL_PROMPTS.json','CALL_LEDGER.json']]
    files += [ROOT/r['receipt'] for r in control.read(rt.ledger)['calls']]
    return {'schema':'shared_whole_production_opening_plan/v1','logical_task_id':LOGICAL,'source_run':None,
        'segment_id':SID,'script_content_sha256':control.digest(s),'global_manifest_sha256':control.digest(m),
        'completed_source_refs':[],'source_refs':first['source_refs'],'provider':'ark_api','model':MODEL,
        'resolution':'480p','ratio':'9:16','duration_seconds':first['duration_seconds'],'generate_audio':True,
        'return_last_frame':True,'input_mode':'text_to_video_bootstrap','references':[],
        'shared_context':context,'shared_request_coverage':coverage,'prompt':prompt,
        'sources':{str(p):{'path':str(p),'sha256':control.sha_file(p)} for p in files},
        'authorization':control.read(ROOT/'USER_SCOPE.json'),'new_submissions':1,'automatic_retry':False,
        'budget_reset':False,'batch_authorized':False,'whole_film_text_planning_complete':True,
        'actual_media_quality_passed':False,'future_continuation_requires_current_human_approval':True,
        'future_continuation_requires_confirmed_actor_mapping':True}


def build_request(client,plan):
    if plan['input_mode']!='text_to_video_bootstrap' or plan['references']:
        raise ValueError('this new series opening may only establish a fresh cast')
    req=client.build_task_payload(plan['prompt'],duration=plan['duration_seconds'],ratio='9:16',resolution='480p',
        generate_audio=True,return_last_frame=True,watermark=False,seed=20261012,references=[],task_type='text')
    if req['model']!=MODEL or len(req['content'])!=1 or req['content'][0].get('type')!='text' or req['content'][0].get('text')!=plan['prompt']:
        raise ValueError('actual request text/model/mode differs from the reviewed plan')
    shared.validate_provider_request_coverage(plan['shared_context'],req['content'][0]['text'],[],'ark_api',req['model'])
    return req


def media(operation):
    OUT.mkdir(parents=True,exist_ok=True); pp=OUT/'PLAN.json'; rp=OUT/'receipt.json'; lock=OUT/'.execution.lock'
    with lock.open('x',encoding='utf-8') as f:f.write('single new casting baseline, no automatic retry')
    try:
        with SeedanceClient(SeedanceConfig.from_env('ark_api',require_key=True)) as client:
            if client.config.model!=MODEL: raise ValueError('unverified media model change')
            if operation=='media_prepare':
                if rp.exists(): raise ValueError('original request exists; query only')
                plan=make_plan(); req=build_request(client,plan)
                control.write(pp,plan,True); control.write(OUT/'REQUEST.preview.json',req,True)
                (OUT/'PROMPT.txt').write_text(plan['prompt']+'\n',encoding='utf-8')
                return {'status':'prepared','duration_seconds':plan['duration_seconds'],'new_paid_calls':0}
            if operation=='media_submit':
                if rp.exists(): raise ValueError('original request exists; never redispatch')
                plan=control.read(pp)
                if plan!=make_plan(): raise ValueError('current handoff/identity/source changed')
                prior.verify_files({q['path']:q['sha256'] for q in plan['sources'].values()})
                req=build_request(client,plan)
                if req!=control.read(OUT/'REQUEST.preview.json'): raise ValueError('request preview changed')
                r={'schema':'shared_whole_production_opening_receipt/v1','status':'submitting','technical_status':'running',
                    'content_status':'not_available','logical_task_id':LOGICAL,'segment_id':SID,'model':MODEL,'provider':'ark_api',
                    'created_at':control.now(),'plan_snapshot':plan,'plan':str(pp),'plan_path':str(pp),'plan_sha256':control.sha_file(pp),
                    'source_bindings':plan['sources'],'request':req,'request_sha256':control.digest(req),'new_submissions':1,'automatic_retry':False}
                control.write(rp,r,True)
                try: reserve_media_attempt(pp,plan,rp)
                except Exception as exc:
                    r.update(status='blocked_before_submit',technical_status='not_submitted',new_submissions=0,error=str(exc));persist(rp,r);raise
                try:
                    created=client.create_task(req)
                    if not created.get('id'): raise ValueError('missing original task ID; result unknown')
                except Exception as exc:
                    code=getattr(exc,'status_code',None);known=type(code) is int and 400<=code<500
                    r.update(status='request_rejected' if known else 'submit_outcome_unknown',technical_status='failed' if known else 'unknown',http_status=code,error=str(exc));persist(rp,r);raise
                r.update(task_id=created['id'],created=created,status='submitted');persist(rp,r)
            elif operation=='media_query':
                r=control.read(rp)
                if not r.get('task_id'): raise ValueError('original outcome unknown; do not redispatch')
            else: raise ValueError('explicit media operation required')
            if r.get('technical_status')=='succeeded':
                prior.verify_files({r['video_path']:r['video_sha256']})
                if r.get('last_frame'): prior.verify_files({r['last_frame']:r['last_frame_sha256']})
                return {k:r.get(k) for k in ['technical_status','content_status','task_id','video_path']}
            t=client.get_task(r['task_id']);r.update(latest_response=t,status=t['status'],last_queried_at=control.now());persist(rp,r)
            if t['status'] in ('failed','expired','cancelled'):
                r.update(technical_status='failed',final=t);persist(rp,r)
            elif t['status']=='succeeded':
                r.update(final=t,provider_task_status='succeeded');persist(rp,r);stage='video_download'
                try:
                    video=client.download_video(t,OUT/(SID+'.mp4'))
                    if not video.stat().st_size: raise ValueError('empty saved video')
                    r.update(video_path=str(video),video_sha256=control.sha_file(video),video_bytes=video.stat().st_size);persist(rp,r)
                    stage='technical_probe'
                    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)],text=True,encoding='utf-8'))
                    r['technical_metadata']=validate_saved_metadata(probe,r['plan_snapshot']);persist(rp,r)
                    stage='tail_download'
                    if t.get('content',{}).get('last_frame_url'):
                        tail=client.download_last_frame(t,OUT/(SID+'.provider_last.png'))
                        if not tail.stat().st_size: raise ValueError('empty provider original tail')
                        r.update(last_frame=str(tail),last_frame_sha256=control.sha_file(tail),last_frame_source='generation_service_original',tail_status='saved_unapproved')
                    else:r.update(last_frame=None,tail_status='not_returned; continuation blocked')
                    r.update(human_decision=None,next_segment_dispatch_allowed=False,assistant_content_inspected=False,
                        actor_subject_mapping_status='awaiting_user_confirmation',voice_identity_binding='unbound',completed_at=control.now())
                    mark_saved_candidate(r);persist(rp,r)
                except Exception as exc:
                    r.update(status='artifact_save_pending',failure_stage=stage,artifact_error=str(exc));persist(rp,r);raise
            return {k:r.get(k) for k in ['technical_status','content_status','status','task_id','video_path','tail_status']}
    finally:lock.unlink()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(); parser.add_argument('operation',choices=['prepare','draft','text','status','media_prepare','media_submit','media_query'])
    op=parser.parse_args().operation
    result=prepare() if op=='prepare' else draft() if op=='draft' else text() if op=='text' else runtime().summary() if op=='status' else media(op)
    print(json.dumps(result,ensure_ascii=False),flush=True)
