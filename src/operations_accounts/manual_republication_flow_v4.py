"""Named preparation continuation: current UID, commit navigation, late file claim.

Frozen v2 leaves/RPC gate are privately compiled and reused. The old v2 upload
claim is never cleared. No declaration selection or publication is performed.
"""
import hashlib
import json
import marshal
import os
from pathlib import Path
import threading
import time
import types
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
SAFE_REASONS=frozenset({"resume_request_invalid","resume_binding_changed","resume_claim_changed",
    "resume_output_changed","resume_session_changed","resume_budget_exhausted","resume_identity_unconfirmed",
    "resume_upload_surface_unconfirmed","resume_prior_selection_exists","resume_post_selection_unknown"})


class ResumePrepareBlocked(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def need(ok,code):
    if not ok:raise ResumePrepareBlocked(code)


def reference(path):
    p=Path(path).resolve();need(p.is_relative_to(ROOT) and p.is_file(),"resume_binding_changed")
    with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(p),sha256=sha)


def read(ref):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,"resume_binding_changed")
    return json.loads(Path(ref['path']).read_text(encoding='utf8'))


def once(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:
        stream.write((json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
    return reference(path)


def _load_base(config):
    ref=config['sources']['flow_v2'];path=ROOT/'src/operations_accounts/manual_republication_flow_v2.py'
    need(reference(path)==ref,"resume_binding_changed")
    module=types.ModuleType('src.operations_accounts._manual_resume_base_'+ref['sha256'][:16])
    module.__file__,module.__package__=str(path),'src.operations_accounts'
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module


def location(url):
    p=urlsplit(url);return dict(origin=p.scheme+'://'+(p.hostname or ''),path=p.path)


def run_action(actor,resource,config,request,outdir):
    from . import manual_republication_runtime_v4 as runtime
    from src.platform_adapter.browser_session import BrowserNavigationTimeout
    fields={'schema','config','action','prior_upload_claim','prior_failure','observation'}
    need(isinstance(request,dict) and set(request)==fields and request['schema']=='manual_republication_operator_request/v4'
         and request['action']=='resume_prepare_upload',"resume_request_invalid")
    need(read(request['config'])==config,"resume_binding_changed")
    folder=Path(outdir).resolve();need(folder.is_relative_to(ROOT/'data') and folder.name=='preparation',"resume_output_changed")
    action_ref=reference(folder.parent/'ACTION_CLAIM.json');action=read(action_ref);plan=read(action['plan'])
    need(action.get('schema')=='manual_republication_resume_action_claim/v4'
         and action.get('action')=='resume_prepare_upload' and action.get('config')==request['config']
         and read(action['request'])==request and action.get('owner_id')==actor.owner_id
         and action.get('generation')==actor.generation and action.get('tab_id')==config['tab_id']
         and action.get('actor_thread_id')==threading.get_ident() and action.get('file_selection_limit')==1
         and action.get('submit_allowed') is False and all(action.get(k)==request[k] for k in ('prior_upload_claim','prior_failure','observation'))
         and plan.get('config')==request['config'] and plan.get('request')==action['request']
         and folder==Path(action['plan']['path']).resolve().parent/'preparation',"resume_claim_changed")
    need(not (folder/'FILE_SELECTION_INTENT.json').exists(),"resume_prior_selection_exists")
    base=_load_base(config);reader,Workflow=base._load_leaves(config);metadata,authority=base._metadata(config)
    original=resource.session;deadline=time.monotonic()+300
    folder.mkdir(parents=True,exist_ok=True);trace_path=folder/'NAVIGATION_TRACE.jsonl'
    with trace_path.open('xb'):pass
    def trace(stage,**evidence):
        with trace_path.open('a',encoding='utf8') as stream:
            stream.write(json.dumps(dict(stage=stage,at_epoch=time.time(),**evidence),ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
    def guard():
        reserve=max(15,float(getattr(original.config,'timeout_ms',30000))/1000+15)
        need(time.monotonic()+reserve<=deadline,"resume_budget_exhausted")
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,"resume_session_changed")
        runtime.validate_live(actor,resource,config)
        b=resource.runtime.bindings.get(config['account_key']);p=resource.runtime.profiles.get(config['account_key'])
        need(b.account_uuid==p.account_uuid==config['account_id'] and reader._binding_version(SimpleNamespace(binding=b,profile=p))==config['binding_version']
             and str(b.public_uid)==authority['expected_public_uid'],"resume_binding_changed")
        need(reference(action_ref['path'])==action_ref,"resume_claim_changed")
    guard();raw=original.get_page(config['tab_id']);guard()
    need(raw.tab_id==config['tab_id'] and raw._session is original,"resume_session_changed")
    identity=None
    class LateGate(base.GuardedOwner):
        file_claim=None
        navigation_calls=0
        def cmd(self,kind,**kwargs):
            if kind=='goto':
                need(not self.selected and kwargs.get('url')==reader.SITES['upload']
                     and kwargs.get('wait_until')=='commit' and self.navigation_calls==0,"resume_request_invalid")
                self.navigation_calls+=1
            if kind=='set_input_files':
                need(self.selection_armed and not self.selected,"resume_prior_selection_exists")
                need(reference(metadata['media']['path'])==metadata['media'],"resume_binding_changed")
                probe=self.read('evaluate',selector='',index=-1,js=base.UPLOAD_PROBE).get('value',{})
                need(_ready(probe),"resume_upload_surface_unconfirmed")
                proof=once(folder/'FILE_SELECTION_PREFLIGHT.json',dict(schema='manual_file_selection_preflight/v4',
                    action_claim=action_ref,media=metadata['media'],identity=identity,preselection=probe,observed_at=time.time(),
                    owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],actor_thread_id=threading.get_ident()))
                self.file_claim=runtime.claim_file_selection(actor,resource,config,request,folder,metadata['media'],proof)
                need(isinstance(self.file_claim,dict) and reference(self.file_claim['path'])==self.file_claim,"resume_claim_changed")
                self.claim=self.file_claim
            return super().cmd(kind,**kwargs)
    def _ready(p):
        return (p.get('origin')=='https://creator.douyin.com' and p.get('path')=='/creator-micro/content/upload'
            and p.get('file_count')==p.get('visible_file_count')==1 and p.get('file_disabled') is False
            and p.get('upload_button_count')==1 and p.get('editor_count')==0)
    gate=LateGate(original,raw,guard,metadata,folder,action_ref);page=base.Page(gate,raw.tab_id)
    try:
        uid_samples=[];trace('current_identity_read_started',location=location(page._cmd('current_url')['url']))
        for _ in range(8):
            before=location(page._cmd('current_url')['url'])
            need(before['origin'] in {'https://www.douyin.com','https://creator.douyin.com'},"resume_identity_unconfirmed")
            uid_script="() => {if(!['https://www.douyin.com','https://creator.douyin.com'].includes(location.origin))return {origin:location.origin,path:location.pathname,public_uids:[],truncated:true};return ("+reader.UID_JS+")();}"
            uid=page.evaluate(uid_script)
            current=location(page._cmd('current_url')['url']);uid_samples.append(uid)
            matched=(before==current=={'origin':uid.get('origin'),'path':uid.get('path')}
                and current['origin'] in {'https://www.douyin.com','https://creator.douyin.com'}
                and uid.get('truncated') is False and uid.get('public_uids')==[authority['expected_public_uid']])
            if matched and len(uid_samples)>=2 and uid_samples[-2].get('public_uids')==uid['public_uids']:
                identity=dict(verified=True,actual_public_uid=authority['expected_public_uid'],observed_at=time.time(),
                    source='current_same_page_rendered_uid_no_navigation',location=current,samples=uid_samples,creator_identity_independently_verified=False)
                break
            page.wait_for_timeout(250)
        need(identity is not None,"resume_identity_unconfirmed")
        trace('current_identity_verified',location=current,actual_public_uid=identity['actual_public_uid'])
        native_location=location(page._cmd('current_url')['url']);target={'origin':'https://creator.douyin.com','path':'/creator-micro/content/upload'}
        navigation_timeout=None
        if native_location!=target:
            trace('upload_navigation_dispatched',wait_until='commit',requested_location=target)
            try:page.goto(reader.SITES['upload'],wait_until='commit',timeout=10000)
            except BrowserNavigationTimeout as error:
                navigation_timeout=error.navigation_evidence
                once(folder/'NAVIGATION_TIMEOUT.json',dict(schema='manual_resume_navigation_timeout/v4',native_navigation_evidence=navigation_timeout))
                trace('upload_navigation_timeout',native_navigation_evidence=navigation_timeout)
            else:trace('upload_navigation_commit_returned')
        else:trace('already_upload_location_no_navigation')
        probes=[];ready=False
        for _ in range(80):
            probe=page.evaluate(base.UPLOAD_PROBE);probes.append(probe)
            if _ready(probe):ready=True;break
            page.wait_for_timeout(250)
        need(ready,"resume_upload_surface_unconfirmed")
        surface=once(folder/'PRESELECTION_SURFACE.json',dict(schema='manual_resume_surface/v4',samples=probes,navigation_timeout=navigation_timeout))
        trace('actual_upload_surface_ready')
        workflow=Workflow(None);journal=folder/'UPLOAD_JOURNAL.jsonl'
        with journal.open('xb'):pass
        workflow._journal_path=journal;workflow._record('named_resume_bound',action_claim=action_ref,metadata=config['metadata'],media=metadata['media'])
        gate.selection_armed=True
        workflow._upload_video_file(page,metadata['media']['path'])
        need(workflow._wait_for_upload_complete(page,timeout=min(120,max(1,int(deadline-time.monotonic()-90)))),"resume_upload_surface_unconfirmed")
        post=once(folder/'POST_UPLOAD_EDITOR.json',page.evaluate(base.declaration_inventory_script()))
        title_selector=base._unique_field(page,base.TITLE_SELECTORS);editor_selector=base._unique_field(page,base.EDITORS)
        gate.fields={title_selector:metadata['title'],editor_selector:metadata['description']}
        workflow._fill_title(page,metadata['title']);workflow._fill_description(page,metadata['description'])
        description_read=page.locator(editor_selector).evaluate(base.FIELD_PROBE)
        need(''.join(description_read.get('content','').split())==''.join(metadata['description'].split()),"resume_upload_surface_unconfirmed")
        workflow._add_hashtags(page,metadata['hashtags'],expected_description=metadata['description'])
        workflow._confirm_hashtag_form(page,metadata['hashtags'],metadata['description'])
        need(page.locator(title_selector).count()==page.locator(editor_selector).count()==1,"resume_upload_surface_unconfirmed")
        title=page.locator(title_selector).evaluate(base.FIELD_PROBE);editor=workflow._hashtag_snapshot(page)
        need(title.get('content')==metadata['title'] and workflow._description_preserved(editor,metadata['description'])
             and all(t in editor['tokens'] for t in metadata['hashtags']),"resume_upload_surface_unconfirmed")
        form=once(folder/'FORM_READBACK.json',dict(title=title,editor_text=editor['text'],hashtag_tokens=list(editor['tokens']),
            expected_hashtags=metadata['hashtags'],description_preserved=True))
        inventory=page.evaluate(base.declaration_inventory_script())
        need(inventory.get('schema')=='manual_editor_declaration_inventory/v1' and inventory.get('input_values_read') is False
             and inventory.get('hidden_state_read') is False and inventory.get('submission_performed') is False
             and inventory.get('location',{}).get('origin')=='https://creator.douyin.com',"resume_upload_surface_unconfirmed")
        editor_ref=once(folder/'EDITOR_DECLARATIONS.json',inventory);guard()
        result=dict(schema='manual_republication_prepare_upload/v4',action='resume_prepare_upload',status='prepared_not_submitted',
            metadata=config['metadata'],media=metadata['media'],action_claim=action_ref,file_selection_claim=gate.file_claim,
            file_selection_intent=reference(folder/'FILE_SELECTION_INTENT.json'),identity=identity,preselection_surface=surface,
            navigation_trace=reference(trace_path),post_upload_editor=post,form_readback=form,editor_inventory=editor_ref,
            title_readback=title,description_readback=description_read,hashtag_readback_verified=True,
            upload_ready=True,upload_completion_verified=True,metadata_readback_matched=True,uploaded=True,upload_attempted=True,
            submitted=False,declaration_selected=False,declaration_entry_expanded=False,publication_ready=False,
            journal=reference(journal),tab_id=raw.tab_id,
            loaded_helpers=dict(base_source=config['sources']['flow_v2'],isolated_compile=True,module=Workflow.__module__,
                upload_code_sha256=hashlib.sha256(marshal.dumps(Workflow._upload_video_file.__code__)).hexdigest()),
            limits=['Current SELF UID was read without reload. Creator identity is not independently verified.',
                'Navigation commit or a timeout is not readiness; actual unique upload DOM was required.',
                'Old UPLOAD_CLAIM and old failure remain unchanged. File claim is first written at selection boundary.',
                'Declaration controls are inventoried only. No selection or publish click.'])
        once(folder/'PREPARED_RESULT.json',result);return result
    except Exception as error:
        selected=gate.selected or gate.file_claim is not None
        code='resume_post_selection_unknown' if selected else error.code if type(error) is ResumePrepareBlocked else 'resume_upload_surface_unconfirmed'
        failure=dict(schema='manual_resume_failure/v4',reason_code=code,
            cause_code=getattr(error,'code',None) if getattr(error,'code',None) in SAFE_REASONS|base.SAFE_REASONS else None,
            error_type=type(error).__name__,file_claim_created=gate.file_claim is not None,file_selection_dispatched=gate.selected,
            upload_attempted=gate.selected,submitted=False,automatic_file_reselection_allowed=False,
            navigation_trace=reference(trace_path))
        if not (folder/'PREPARE_FAILURE.json').exists():once(folder/'PREPARE_FAILURE.json',failure)
        raise ResumePrepareBlocked(code) from error
