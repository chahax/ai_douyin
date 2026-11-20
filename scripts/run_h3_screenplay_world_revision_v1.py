"""Explicit independent world/script revision; preview never claims or calls.

Uses unchanged one-send runtime/client evidence, inherited consumption and two
original remaining body slots. Does not own the other chat's counted round11.
"""
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_goal_context_dispatch_v7 as runtime7
from scripts import creative_m31_screenplay_role_clients_v1 as clients
from scripts import creative_paired_drama_probe_spend_anchor_v1 as spend
from scripts import creative_paired_drama_probe_v1 as ancestor
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts.creative_fresh_source_session_v1 import Session as NativeSession, Halt
from src.content_factory import creative_screenplay_world_v1 as story

ROOT=PROJECT/'data/video_generation/h3_project_script_20261015/revision_02/text'
PARENT=PROJECT/'data/qa/creative_paired_live_diagnostic_20261015/PROBE636_SPEND_ANCHOR_v1.json'
PROFILE=PROJECT/'config/creative_screenplay_world_profile_v1.json'
SOURCE=PROJECT/'data/production_trials/legal_scoped_text_session_20261015/round_01'
BRIEF=ROOT.parent/'USER_REVISION_BRIEF.json'
CASTING=ROOT.parents[1]/'PRIMARY_CASTING_SELECTION.json'
VERSION='h3_screenplay_world_revision/v1'
LIMITS={'goal_plan':1,'goal_audit':0,'complete_script':2,'full_review':2}
DIRECTOR={'used':7,'limit':7,'remaining':0}
read,write,digest,sha,now=io.read,io.write,io.digest,io.sha_file,io.now


def seed():
    cast=read(CASTING)['refs']
    appearance={'C01':'黑色齐肩中分直发；灰蓝薄针织开衫、白色圆领T恤、深灰直筒裤；本片加深绿腰围裙。保持原人物图的脸，不因十一年工龄改成老年面容。',
                'C02':'棕色短碎发；米驼色卷袖衬衫、深藏蓝裤。保持原人物图的脸、发型和基础衣着。'}
    fixed={}
    for code,name in [('C01','周桂芳'),('C02','马涛')]:
        ref=next(r for r in cast if r['asset_id'].endswith('.'+code))
        if sha(ref['path'])!=ref['sha256']:raise ValueError('fixed actor original hash changed')
        fixed[code]={'name':name,'asset_id':ref['asset_id'],'sha256':ref['sha256'],
                     'appearance_and_clothing':appearance[code],'human_current_casting_approval':None}
    inputs=read(SOURCE/'INPUTS.json')
    old=read(SOURCE/'scripts/version_01/NATIVE_SCRIPT.json')
    receipt=read(SOURCE/'call_635_full_review_semantic_01.json')
    return {'fixed_casting':fixed,'fixed_scene':{'asset_id':'h3.scene.supermarket_backroom.20261015.v2',
        'scope':'既有场景v2是门口可见值班室一角；门、桌椅、暖壶和杯保持。新初态工作用记录/道具可明确计划，但需可见来源/位置和流转；既有空桌不等于剧情道具永远absent。'},
        'original_native_script':old,'old_review635_contract_diagnostics':{k:receipt.get(k) for k in ('status','validation','validation_error','failure')},
        'known_story_faults':['旧B1桂芳门外初态已被用户改变：她已在屋内工作，经理跨门立即开口。',
            '旧B6经理要求她不签换排班没有明确合理动因，须实际演出新刺激、权衡、现实代价和让步。',
            '旧B6排班表/确认单身份和出现混淆；旧B8对白提议带走却动作留桌，文件与打印件反复收/拿矛盾。'],
        'verified_legal_context':inputs.get('verified_legal_context',inputs.get('legal_context',{})),
        'prior_content_and_source_scope':'同一超市劳动争议故事；旧全文机器未通过，不能宣称新剧本用户采用或旧freeze改写。这里只继承故事、真实法律上下文和失败证据；原source freshness不升级。'}


def sources():
    paths=[Path(__file__),Path(story.__file__),PROFILE,PARENT,BRIEF,CASTING,
        SOURCE/'INPUTS.json',SOURCE/'scripts/version_01/NATIVE_SCRIPT.json',SOURCE/'call_635_full_review_semantic_01.json',
        PROJECT/'docs/H3_SCREENPLAY_WORLD_REVISION_PLAN_20261015.md']
    for module in tuple(sys.modules.values()):
        p=getattr(module,'__file__',None)
        if p:
            p=Path(p).resolve()
            if p.suffix=='.py' and any(p.is_relative_to(PROJECT/d) for d in ('src','scripts')):paths.append(p)
    return sorted(set(paths))


def preview():
    parent=read(PARENT)
    checked=spend.verify_anchor(parent,expected_anchor_sha256=digest(parent))
    if checked['inherited']!={'calls_started':636,'reported_tokens':13408816,'calls_with_known_usage':634,
        'pending_ordinals':[70,160],'unknown_token_reservations':93117}:raise ValueError('latest636 inherited anchor changed; review new global consumption first')
    brief=read(BRIEF)
    if sha(brief['parent_native_script_path'])!=brief['parent_native_script_sha256']:
        raise ValueError('old native body identity changed')
    native_seed=seed(); first=story.prepare_world(brief,native_seed,read(PROFILE))
    clients.expected_wire_request(first['request'])
    successor=[str(p) for p in policy.successor_paths(PROJECT,parent,digest(parent))]
    return {'schema':VERSION+'/preview','created_at':now(),'root':str(ROOT),'parent_anchor_path':str(PARENT),
        'parent_anchor_sha256':digest(parent),'parent_identity':parent['parent_identity'],'inherited':checked['inherited'],
        'brief':brief,'seed':native_seed,'first_request':first,
        'source_files':{str(p):sha(p) for p in sources()},'parent_integrity_files':ancestor.inherited_files(parent),
        'stage_limits':LIMITS,'total_new_calls_limit':5,
        'capacity_binding':{'world_framework':{'limit':1,'source':'new explicit user world-framework request; not whole_plan5'},
            'complete_script':{'old_used':1,'old_limit':3,'old_remaining':2,'this_run_limit':2},
            'full_review':{'old_used':1,'old_limit':6,'old_remaining':5,'this_run_limit':2},'old_director':DIRECTOR},
        'successor_claim_paths':successor,'successor_already_exists':[p for p in successor if Path(p).exists()],
        'counter_round11':'owned by separate active development session; this local user revision does not mutate its rounds',
        'human_video_review_required':True,'media_calls_authorized':False,'old_budget_reset':False,'provider_calls':0}


def preview_identity(value):
    value=deepcopy(value);value.pop('created_at',None);value.pop('primary_review_identity',None)
    return digest(value)


def prepare(approved_preview_sha):
    value=preview()
    if preview_identity(value)!=approved_preview_sha:raise ValueError('primary-reviewed preview differs; no claim or dispatch')
    if (ROOT/'RUN_CLAIM.json').exists() or (ROOT/'PREPARED.json').exists():raise FileExistsError('existing run/prepared claim cannot restart')
    if value['successor_already_exists']:raise FileExistsError('636 already consumed by another successor; no regrant')
    ROOT.mkdir(parents=True,exist_ok=True)
    write(ROOT/'PREVIEW.json',value,True)
    scope={'schema':VERSION+'/scope','source_user_message':value['brief']['source_user_message'],
        'brief_sha256':digest(value['brief']),'preview_sha256':preview_identity(value),'inherited':value['inherited'],
        'stage_limits':LIMITS,'old_director_capacity':DIRECTOR,'body_revisions_limit':1,'world_limit':1,
        'full_review_limit':2,'automatic_retry':False,'media_calls_authorized':False,'old_budget_reset':False,
        'same_story_failures_reset':False,'other_round11_modified':False}
    write(ROOT/'USER_SCOPE.json',scope,True)
    binding={'schema':VERSION+'/successor_claim','root':str(ROOT),'parent_anchor_sha256':value['parent_anchor_sha256'],
        'parent_identity':value['parent_identity'],'authorization_sha256':sha(ROOT/'USER_SCOPE.json'),'old_budget_reset':False}
    for p in value['successor_claim_paths']:policy.new_claim(p,binding)
    write(ROOT/'PREPARED.json',{'schema':VERSION+'/prepared','preview_identity':preview_identity(value),
        'binding':binding,'source_files':value['source_files'],'successor_claim_paths':value['successor_claim_paths']},True)
    rt=runtime();rt.prepare();state(rt,'prepared')
    return {'status':'prepared','provider_calls':0,'preview_identity':preview_identity(value)}


def guard():
    prepared=read(ROOT/'PREPARED.json');value=read(ROOT/'PREVIEW.json')
    if preview_identity(value)!=prepared['preview_identity']:raise ValueError('reviewed source preview changed')
    for p in prepared['successor_claim_paths']:
        if read(p)!=prepared['binding']:raise ValueError('unique successor binding changed')
    for name,expected in {**value['parent_integrity_files'],**prepared['source_files']}.items():
        if sha(name)!=expected:raise ValueError('source/parent byte identity changed: '+name)
    if digest(read(BRIEF))!=digest(value['brief']):raise ValueError('new user brief changed')
    return True


def runtime(client_factory_builder=None):
    value=read(ROOT/'PREVIEW.json')
    return ScreenplayRuntime(PROJECT,ROOT,[Path(p) for p in value['source_files']],value['inherited'],
        profile=read(PROFILE),stage_limits=LIMITS,inherited_guard=guard,quota_state=None,
        shared_lock=ROOT/'DISPATCH.lock',admission=lambda *args:guard(),client_factory_builder=client_factory_builder or clients.make_client_factory)


class ScreenplayRuntime(runtime7.GoalContextRuntime):
    def _request_gate(self,wire):
        from jsonschema import Draft202012Validator
        stage=wire.get('stage');role=wire.get('role')
        expected_roles={'goal_plan':'writer','complete_script':'writer','full_review':'director'}
        if expected_roles.get(stage)!=role or wire.get('model')!=self.models[role]['model']:
            raise ValueError('independent screenplay stage/model/role differs')
        parameters=deepcopy(self.profile[role]['parameters']);parameters.update(self.profile['stage_parameters'].get(stage,{}))
        if wire.get('parameters')!=parameters:raise ValueError('independent exact stage output profile differs')
        clients.expected_wire_request(wire)
        Draft202012Validator.check_schema(wire['structured_schema'])


def state(rt,status,**details):
    spend_value=rt.summary()
    value={'schema':VERSION+'/state','at':now(),'status':status,'spend':spend_value,
        'spend_verification_pending':False,'text_ready_for_director':False,'local_screenplay_review_accepted':status=='text_review_accepted_for_local_trial',
        'human_quality_approved':False,'creative_quality_passed':False,'media_authorized':False,
        'old_director_capacity':DIRECTOR,'old_budget_reset':False,'same_story_failures_reset':False,**details}
    write(ROOT/'STATE.json',value);return value


def invoke(rt,label,prepared,validator):
    guard()
    write(ROOT/'requests'/f'{label}.json',prepared,True)
    return rt.dispatch(label,prepared['request'],validator)


def run():
    guard()
    if (ROOT/'RUN_CLAIM.json').exists():raise FileExistsError('original RUN claim exists; no automatic restart or redispatch')
    policy.new_claim(ROOT/'RUN_CLAIM.json',{'schema':VERSION+'/run_claim','pid':os.getpid(),'started_at':now(),'automatic_restart':False})
    rt=runtime()
    if read(rt.ledger)['calls']:raise RuntimeError('nonempty ledger cannot restart')
    value=read(ROOT/'PREVIEW.json');brief=value['brief'];native_seed=value['seed'];profile=read(PROFILE)
    try:
        receipt=invoke(rt,'world_framework_01',value['first_request'],lambda doc:story.validate_world(doc,brief,native_seed['fixed_casting']))
        world=NativeSession.known(receipt,'new_world_framework')
        write(ROOT/'WORLD_NATIVE.json',world,True)
        (ROOT/'WORLD_FRAMEWORK.md').write_text(story.render_world(world),encoding='utf-8')
        previous=diagnostics=None
        for index in (1,2):
            prepared=story.prepare_script(brief,world,native_seed,profile,previous,diagnostics)
            receipt=invoke(rt,f'complete_script_{index:02}',prepared,lambda doc:story.validate_script(doc,brief,world))
            body=NativeSession.known(receipt,'complete_native_script',require_valid=False)
            folder=ROOT/'scripts'/f'version_{index:02}'
            write(folder/'NATIVE_SCRIPT.json',body,True)
            if receipt['status']!='contract_valid':
                previous=body;diagnostics=receipt.get('validation_error',receipt.get('validation'))
                if index==2:return state(rt,'halt_body_capacity_exhausted',receipt_ordinal=receipt['ordinal'])
                continue
            (folder/'FULL_SCRIPT.md').write_text(story.render_script(body,world),encoding='utf-8')
            prepared=story.prepare_review(brief,world,body,native_seed,profile)
            review_receipt=invoke(rt,f'full_review_{index:02}',prepared,lambda doc:story.validate_review(doc,brief,world,body))
            review=NativeSession.known(review_receipt,'same_source_full_review')
            write(folder/'NATIVE_FULL_REVIEW.json',review,True)
            decision=review_receipt['validation'];write(folder/'DECISION.json',decision,True)
            if decision['uncertain']:return state(rt,'halt_review_unknown',receipt_ordinal=review_receipt['ordinal'])
            if decision['accepted']:
                write(ROOT/'TEXT_HANDOFF.json',{'schema':VERSION+'/text_handoff','world_path':str(ROOT/'WORLD_NATIVE.json'),
                    'world_file_sha256':sha(ROOT/'WORLD_NATIVE.json'),'world_native_sha256':digest(world),
                    'script_path':str(folder/'NATIVE_SCRIPT.json'),'script_file_sha256':sha(folder/'NATIVE_SCRIPT.json'),
                    'script_native_sha256':digest(body),'review_path':str(folder/'NATIVE_FULL_REVIEW.json'),
                    'review_file_sha256':sha(folder/'NATIVE_FULL_REVIEW.json'),'brief_sha256':digest(brief),
                    'native_documents_modified':False,'user_adopted':False,'video_approved':False,
                    'old_director_capacity':DIRECTOR,'full_frozen_pipeline_passed':False},True)
                return state(rt,'text_review_accepted_for_local_trial',script_version=index,script_ordinal=receipt['ordinal'],review_ordinal=review_receipt['ordinal'])
            previous=body;diagnostics=review
        return state(rt,'halt_body_capacity_exhausted',receipt_ordinal=review_receipt['ordinal'])
    except Halt as error:
        return state(rt,error.status,**error.details)
    except Exception as error:
        write(ROOT/'EXECUTION_ERROR.json',{'at':now(),'error_type':type(error).__name__,'error':str(error),
            'automatic_restart':False,'original_id_reconciliation_required':True},True)
        try:state(rt,'halt_execution_exception_requires_reconciliation',error_type=type(error).__name__,error=str(error))
        except Exception:pass
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preview','prepare','run','status'])
    parser.add_argument('--output');parser.add_argument('--approve-preview-sha')
    args=parser.parse_args()
    if args.action=='preview':result=preview();result['primary_review_identity']=preview_identity(result)
    elif args.action=='prepare':result=prepare(args.approve_preview_sha)
    elif args.action=='run':result=run()
    else:result=read(ROOT/'STATE.json')
    if args.output:write(args.output,result)
    print(json.dumps({'saved':args.output,'primary_review_identity':result.get('primary_review_identity'),
        'status':result.get('status'),'provider_calls':result.get('provider_calls')},ensure_ascii=False) if args.output else json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
