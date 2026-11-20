"""One explicit original-bound read of an agent-observed native work URL.

The observation chooses a target only. Fresh identity and the unchanged native
detail verifier supply every success field; only core.settle can settle it.
"""
import hashlib
import json
import math
from pathlib import Path
import re

from .browser_control import BrowserCommandResult, BrowserControlRejected, _json
from . import publication_verification_recovery as core

ROOT=Path(__file__).resolve().parents[2]
SCHEMA='publication_known_link_request/v1'
OBSERVATION='publication_native_link_observation/v1'
PURPOSE='explicit_known_native_link'
LIMITS=dict(max_new_known_link_reads=1,upload_allowed=False,publish_click_allowed=False,
            automatic_MAX_ATTEMPTS_changed=False,observation_is_target_seed_only=True)


def require(ok,code):
    if not ok:raise BrowserControlRejected(code,'原提交、已见链接或只读授权不匹配；保留原未知记录，不重传。')


def reference(path):
    path=Path(path).resolve()
    require(path.is_relative_to(ROOT/'data') and path.is_file(),'known_link_project_evidence_required')
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(path),sha256=sha)


def read(ref):
    require(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,
            'known_link_evidence_changed')
    raw=Path(ref['path']).read_bytes();require(len(raw)<=2*1024*1024,'known_link_evidence_too_large')
    value=json.loads(raw);require(isinstance(value,dict),'known_link_evidence_object_required')
    return value


def services(store,runtime):
    from . import browser_control_runtime as managed
    return (store if store is not None else managed._store(),runtime if runtime is not None else managed._runtime())


def _observation(ref):
    value=read(ref)
    require(value.get('schema')==OBSERVATION and value.get('observation_source')=='agent_native_CUA_AX',
            'agent_native_link_observation_required')
    for key in ('original_publish_command_id','account_uuid','account_key','binding_version','platform_identity_key',
                'observed_public_uid','observed_title','canonical_url'):
        require(isinstance(value.get(key),str) and 0<len(value[key])<=4000,'known_link_exact_subject_required')
    require(re.fullmatch(r'https://www\.douyin\.com/video/[0-9]{10,24}',value['canonical_url']) is not None,
            'observed_canonical_native_link_required')
    require(type(value.get('observed_at')) in (int,float) and math.isfinite(value['observed_at'])
        and value['observed_at']>0,'known_link_observation_time_required')
    require(isinstance(value.get('evidence'),list) and 1<=len(value['evidence'])<=10,
            'native_UI_observation_evidence_required')
    for ref in value['evidence']:require(reference(ref['path'])==ref,'native_UI_observation_changed')
    return value


def _context(observation,runtime):
    from .browser_control_runtime import binding_version
    context=runtime.resolve(observation['account_key'],require_healthy=False)
    require(context.account_uuid==observation['account_uuid'] and context.account_key==observation['account_key']
        and binding_version(context)==observation['binding_version']
        and context.binding.platform_identity_key==observation['platform_identity_key']
        and context.binding.public_uid==observation['observed_public_uid'],'known_link_original_identity_binding_changed')
    return context


def _candidate(candidate_id):
    from src.services.fanqie_h3_candidate_v1 import CandidateLedger
    from src.services.fanqie_review_service import CLOSED_LOOP_DB_PATH
    return CandidateLedger(CLOSED_LOOP_DB_PATH).get(candidate_id)


def _candidate_subject(candidate_id,original,context,media,reader=None):
    candidate=(reader or _candidate)(candidate_id);frozen=json.loads(candidate['frozen_json'])
    require(candidate['command_id']==original['command_id'] and frozen['media']==media
        and frozen['account']==dict(account_uuid=context.account_uuid,account_key=context.account_key,binding_version=original['binding_version']),
        'known_link_candidate_original_mismatch')
    provenance=read(frozen['provenance']);assembly=read(provenance['assembly_result']);clock=assembly.get('clock',{})
    require(assembly.get('file')==media and type(clock.get('frames')) is int and clock['frames']>0
        and type(clock.get('fps')) is int and clock['fps']>0,'known_link_original_frame_clock_required')
    return frozen,dict(assembly_result=provenance['assembly_result'],clock=clock,seconds=clock['frames']/clock['fps'])


def _parent(ref,media,context):
    authority=read(ref)
    require(authority.get('schema')=='fanqie_production_trial_user_authorization/v1'
        and authority.get('user_statement') and authority.get('authorized_target',{}).get('media')==media
        and authority['authorized_target'].get('douyin_account_key')==context.account_key,
        'known_link_parent_publication_scope_changed')
    return authority


def _baseline(store,db,observation,context,current_id=None):
    original=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
        (observation['original_publish_command_id'],)).fetchone())
    require(original and original['kind']=='publish' and original['state']=='outcome_unknown'
        and original['account_id']==context.account_uuid and original['binding_version']==observation['binding_version']
        and original['payload'].get('account_key')==context.account_key
        and original['payload']['request']['title']==observation['observed_title'],
        'known_link_original_publication_changed')
    source=core._source(context,original)
    all_reads=core._attempts(store,db,original['command_id'])
    automatic=[r for r in all_reads if r['idempotency_key'].startswith('publication-verify:'+original['command_id']+':')]
    require(len(automatic)==core.MAX_ATTEMPTS==3 and all(r['state']=='failed' and r['account_id']==original['account_id']
        and r['binding_version']==original['binding_version'] and r['payload'].get('attempt')==index
        and r['idempotency_key']=='publication-verify:'+original['command_id']+':'+str(index)
        and r['payload'].get('source')==source and r['payload'].get('original_snapshot_sha256')==core._digest(original)
        for index,r in enumerate(automatic,1)),'three_original_auto_reads_must_be_known_failed')
    from .publication_autonomous_reconciliation import unresolved
    pending=unresolved(store,db,context.account_uuid,('running','paused','waiting_human','outcome_unknown'))
    require(all(r['command_id'] in {original['command_id'],current_id} for r in pending),
            'other_original_work_unresolved')
    return original,source,automatic


def _key(original,source,prior):
    baseline=dict(original=core._digest(original),source=source,prior=[core._digest(r) for r in prior])
    return 'known-link:'+original['command_id']+':'+hashlib.sha256(_json(baseline).encode()).hexdigest()


def _payload(value,ref):
    return dict(account_uuid=value['account_uuid'],account_key=value['account_key'],
        original_command_id=value['original']['command_id'],original_snapshot_sha256=core._digest(value['original']),
        source=value['source'],attempt=4,known_link_read_index=1,verification_purpose=PURPOSE,known_link_verification=ref)


def prepare(observation_ref,*,authority_ref,candidate_id,output_directory,store=None,runtime=None,candidate_reader=None):
    observation=_observation(observation_ref)
    store,runtime=services(store,runtime);context=_context(observation,runtime)
    with store._db() as db:
        original,source,prior=_baseline(store,db,observation,context)
        require(not any(r['state'] in {'queued','running','paused','waiting_human','outcome_unknown'} for r in core._attempts(store,db,original['command_id'])),
                'original_verification_still_live')
    media=dict(path=str(Path(original['payload']['request']['video_path']).resolve()),sha256=original['payload']['video_sha256'])
    _parent(authority_ref,media,context)
    require(reference(media['path'])==media,'known_link_original_media_changed')
    require(isinstance(candidate_id,str) and candidate_id,'known_link_candidate_required')
    frozen,expected=_candidate_subject(candidate_id,original,context,media,candidate_reader)
    require(original['created_at']<=observation['observed_at']<=store.clock()+5,'known_link_observation_not_current_work')
    value=dict(schema=SCHEMA,verification_purpose=PURPOSE,observation=observation_ref,observation_content=observation,
        parent_authority=authority_ref,account_uuid=context.account_uuid,account_key=context.account_key,
        binding_version=original['binding_version'],original=original,source=source,prior_automatic_reads=prior,
        candidate_id=candidate_id,candidate_frozen_sha256=core._digest(frozen),media=media,
        expected_native_video=expected,
        target_url=observation['canonical_url'],idempotency_key=_key(original,source,prior),
        limits=LIMITS)
    directory=Path(output_directory).resolve();require(directory.is_relative_to(ROOT/'data'),'known_link_project_directory_required')
    directory.mkdir(parents=True,exist_ok=True);path=directory/'REQUEST.json';raw=(_json(value)+'\n').encode()
    if path.exists():require(path.read_bytes()==raw,'existing_known_link_request_preserved')
    else:
        with path.open('xb') as out:out.write(raw)
    return reference(path)


def validate_request(ref,*,store,context,command=None,db=None):
    value=read(ref);observation=_observation(value['observation'])
    require(value.get('schema')==SCHEMA and value.get('verification_purpose')==PURPOSE
        and value.get('limits')==LIMITS
        and observation==value['observation_content'] and value['target_url']==observation['canonical_url']
        and value['idempotency_key']==_key(value['original'],value['source'],value['prior_automatic_reads'])
        and context.account_uuid==value['account_uuid'] and context.account_key==value['account_key'],
        'known_link_request_subject_changed')
    from .browser_control_runtime import binding_version
    require(binding_version(context)==value['binding_version']
        and context.binding.platform_identity_key==observation['platform_identity_key']
        and context.binding.public_uid==observation['observed_public_uid'],'known_link_current_binding_changed')
    def check(connection):
        original,source,prior=_baseline(store,connection,observation,context,command['command_id'] if command else None)
        require(original==value['original'] and source==value['source'] and prior==value['prior_automatic_reads'],
                'known_link_original_baseline_changed')
        _parent(value['parent_authority'],value['media'],context)
        require(reference(value['media']['path'])==value['media'],'known_link_original_media_changed')
        frozen,expected=_candidate_subject(value['candidate_id'],original,context,value['media'])
        require(core._digest(frozen)==value['candidate_frozen_sha256'] and expected==value['expected_native_video'],
                'known_link_candidate_or_frame_clock_changed')
        if command is not None:
            require(command['kind']==core.KIND and command['state'] in {'queued','running'}
                and command['account_id']==value['account_uuid'] and command['binding_version']==value['binding_version']
                and command['idempotency_key']==value['idempotency_key'] and command['payload']==_payload(value,ref),
                'known_link_command_changed')
        return dict(request=value,original=original,source=source,target_url=value['target_url'])
    if db is not None:return check(db)
    with store._db() as connection:return check(connection)


def enqueue(ref,*,store=None,runtime=None):
    value=read(ref);observation=_observation(value['observation']);store,runtime=services(store,runtime)
    context=_context(observation,runtime)
    require(value.get('schema')==SCHEMA and value.get('verification_purpose')==PURPOSE and value.get('limits')==LIMITS,
            'known_link_request_scope_changed')
    _parent(value['parent_authority'],value['media'],context)
    with store._db() as db:
        existing=store._command(db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
            (context.account_uuid,value['idempotency_key'])).fetchone())
    if existing:
        require(existing['payload']==_payload(value,ref),'known_link_slot_already_used')
        return dict(command_id=existing['command_id'],state=existing['state'],reused=True)
    validate_request(ref,store=store,context=context)
    command=store.submit(value['account_uuid'],value['binding_version'],core.KIND,value['idempotency_key'],_payload(value,ref),400)
    require(command['payload']==_payload(value,ref),'known_link_slot_already_used')
    return dict(command_id=command['command_id'],state=command['state'],reused=False)


def run(ctx,session):
    """Only called by the original managed actor; never upload or discover cards."""
    ref=ctx.command['payload'].get('known_link_verification')
    proof=validate_request(ref,store=ctx.actor.store,context=ctx.resource.context,command=ctx.command)
    original,_=core.inputs(ctx.actor.store,ctx.command,ctx.resource.context)
    require(original==proof['original'],'known_link_core_original_changed')
    ctx.check_dispatch()
    identity=ctx.resource.runtime.verify_identity(ctx.resource.context,session=session)
    if not identity.healthy:return BrowserCommandResult('failed',dict(status='human_required',reason='original_identity_unverified'))
    ctx.check_dispatch();page=session.open_page(proof['target_url'])
    from src.platform_adapter.publish_verification import wait_for_published_video,video_id
    post_id=video_id(proof['target_url']);request=original['payload']['request']
    evidence=wait_for_published_video(page,post_id,ai_required=request.get('ai_generated',True),
        fiction_required=request.get('fictional_story',True),required_hashtags=[v.strip().lstrip('#') for v in request.get('hashtags',[]) if v.strip().lstrip('#')],
        expected_title=request['title'],dispatch_guard=ctx.check_dispatch)
    if evidence.get('human_required'):return BrowserCommandResult('failed',dict(status='human_required',reason='platform_verification_required'))
    if evidence.get('verified') is not True:return BrowserCommandResult('failed',dict(status='verification_pending',reason=evidence.get('reason','detail_unverified')))
    ctx.check_dispatch()
    technical=page.locator('html').evaluate(r'''()=>{
        const visible=e=>e.isConnected&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
        const videos=Array.from(document.querySelectorAll('video')).filter(visible);
        const nodes=Array.from(document.querySelectorAll('div,span,p'));
        const pattern=/^发布时间[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}(?::[0-9]{2})?)$/;
        const matches=nodes.length<=4000?nodes.filter(e=>visible(e)&&e.innerText.length<160&&pattern.test(e.innerText.trim())):[];
        const leaves=matches.filter(e=>!matches.some(other=>other!==e&&e.contains(other)));
        return {origin:location.origin,path:location.pathname,visible_video_count:videos.length,
          actual_seconds:videos.length===1&&Number.isFinite(videos[0].duration)?videos[0].duration:null,
          publication_time_candidates:leaves.length,publication_time_raw:leaves.length===1?leaves[0].innerText.trim():null,
          publication_time_native_field_verified:false};
    }''')
    seconds=technical.get('actual_seconds');expected=proof['request']['expected_native_video']['seconds']
    if (technical.get('origin')!='https://www.douyin.com' or technical.get('path')!='/video/'+post_id
        or technical.get('visible_video_count')!=1 or type(seconds) not in (int,float) or not math.isfinite(seconds)
        or abs(seconds-expected)>2):
        return BrowserCommandResult('failed',dict(status='verification_pending',reason='full_media_duration_unverified'))
    evidence.update(actual_seconds=seconds,expected_seconds=expected,numeric_duration_verified=True,
        public_page_time_text_observation=technical)
    # Text uniqueness alone cannot distinguish a native timestamp from caption
    # or comment text. Without an observed native field contract, retain this
    # diagnostic only and let the existing metadata/time-evidence path verify.
    evidence.update(post_id=post_id,publish_url=proof['target_url'],known_link_target_observation=proof['request']['observation'])
    session.stop();ctx.check_dispatch()
    return core.settle(ctx,original,evidence,proof['source'])
