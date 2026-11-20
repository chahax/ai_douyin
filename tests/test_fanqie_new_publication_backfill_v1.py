"""Private durable owner/CLI/late-claim integration; platform IO is the only stub."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

from src.operations_accounts import fanqie_new_publication_backfill_v1 as new
from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlStore,BrowserTaskContext
from src.operations_accounts.fanqie_account_control import FanqieAccounts
from src.operations_accounts.fanqie_managed_promotion_v1 import make_handlers


def package(folder):
    folder.mkdir(parents=True)
    def put(name,value):return new.once(folder/name,value)
    store=BrowserControlStore(folder/'control.db')
    with sqlite3.connect(folder/'douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid,account_key,platform_identity_key,browser_environment_key,browser_profile_dir,created_at,platform,status)')
        db.execute('INSERT INTO account_runtime_bindings VALUES(?,?,?,?,?,?,?,?)',('privateuuid','novel','public_uid:12345','privateenv','privateprofile','fixed','douyin','active'))
    a=FanqieAccounts(folder/'control.db',folder/'profiles',folder/'evidence',folder/'douyin.db');a.install();env=a.create('private','novel')
    probe=dict(schema='platform_identity_probe/v1',platform='fanqie',verified=True,challenge=False,platform_identity_key='uid:54321',
        environment_key=env['environment_key'],observed_at=time.time(),identity_source='platform_account_id')
    probe_ref=put('evidence/probe.json',probe)
    a.bindings().confirm(put('evidence/confirmation.json',dict(schema='platform_identity_confirmation/v1',platform='fanqie',
        decision_source='explicit_user_confirmation',user_statement='private fixture confirmation',probe_evidence=probe_ref,
        **{k:env[k] for k in ('resource_id','binding_version','environment_key','profile_dir')},platform_identity_key='uid:54321')))
    media=put('media.json',dict(synthetic=True))
    authority=put('AUTHORITY.json',dict(schema='explicit_republication_intent/v1',account_uuid='privateuuid',account_key='novel',expected_public_uid='12345',
        new_backfill_limit=1,old_records_unchanged=True,old_post_id='10001',media=media))
    operator=put('OPERATOR.json',dict(parent_authority=authority))
    metadata=put('METADATA.json',dict(media=media,description='根据《测试书》制作，搜索测试别名'))
    claim=put('PUBLICATION_CLAIM.json',dict(authority=authority,metadata=metadata))
    plan_config=put('PUBLICATION_CONFIG.json',dict(authority=authority,operator_authority=operator,metadata=metadata,account_id='privateuuid'))
    plan=put('PUBLICATION_PLAN.json',dict(config=plan_config))
    candidate=put('CANDIDATE.json',dict(candidate=dict(aweme_id='10002'),native_created_epoch=1794942450,expected_duration_seconds=120.66666666666667))
    evidence=put('CAPTION.json',dict(verified=True,full_caption_verified=True,hashtags_verified=True,ai_label_visible=True,fiction_notice_visible=True,
        expected_post_id='10002',url='https://www.douyin.com/video/10002'))
    video=put('PLAYER.json',dict(duration=120.68,visible_video_count=1,origin='https://www.douyin.com',path='/video/10002'))
    result_value=dict(schema='manual_republication_runtime_result/v10',status='current_caption_verified',external_publication_verified=True,full_metadata_verified=True,
        scoped_evidence=evidence,caption=dict(published_evidence=evidence,video_probe=video,post_verified=True,full_metadata_verified=True,full_caption_verified=True,numeric_duration_verified=True),
        plan=plan,claim=claim,prior_submission_claim=claim,post_id='10002',canonical_url='https://www.douyin.com/video/10002')
    result=put('PUBLICATION_RESULT.json',result_value)
    receipt=put('PUBLICATION_RECEIPT.json',dict(schema='manual_republication_result_binding/v10',plan=plan,claim=claim,result=result))
    verified=put('VERIFIED.json',dict(schema='verified_declared_publication/v1',authority=authority,metadata=metadata,candidate=candidate,submission_claim=claim,
        account_uuid='privateuuid',account_key='novel',expected_public_uid='12345',post_verified=True,full_metadata_verified=True,numeric_duration_verified=True,
        native_AI_statement_verified=True,old_records_retained=True,media=media,verification_result=result,verification_receipt=receipt,scoped_evidence=evidence,native_video_probe=video,
        post_id='10002',canonical_url='https://www.douyin.com/video/10002',native_created_epoch=1794942450,published_at='2026-11-18T03:07:30+08:00',duration_seconds=120.68))
    target=dict(book_id='20001',book_name='测试书',alias='测试别名')
    scope=dict(**{k:env[k] for k in ('resource_id','binding_version','environment_key')},platform_identity_key='uid:54321')
    editor=put('EDITOR.json',dict(schema='fanqie_backfill_editor_inspection/v1',status='editor_controls_observed',target=target,managed_subject=scope,
        fields_written=False,files_selected=False,submitted=False,deleted=False,old_ledger_changed=False))
    seal=put('SOURCE_SEAL.json',dict(schema='fanqie_new_backfill_source_seal/v1',sources=[new.reference(p) for p in new.SOURCE_PATHS]))
    request=dict(schema='fanqie_new_publication_backfill_request/v1',draft_only=False,source_seal=seal,authority=authority,operator_authority=operator,
        verified_publication=verified,metadata=metadata,candidate=candidate,submission_claim=claim,editor_observation=editor,
        **scope,**target,douyin_account_uuid='privateuuid',new_publication=dict(post_id='10002',canonical_url='https://www.douyin.com/video/10002',publish_date='2026-11-18',native_created_epoch=1794942450),
        retained_publication=dict(canonical_url='https://www.douyin.com/video/10001',publish_date='2026-11-17'),new_backfill_limit=1,
        native_mode='create_new_post_in_blank_backfill_form',preserve_existing_records=True,no_delete_or_replace_actions=True,
        submit_claim_path=str(folder/'NEW_BACKFILL_SUBMIT_CLAIM.json'))
    return a,env,store,probe,request,put('REQUEST.json',request)


def test_public_cli_owner_late_claim_and_unknown_are_once(tmp_path,monkeypatch,capsys):
    """Real queue, owner, identity guard and durable CAS; only native adapter IO is fake."""
    import src.platform_adapter.fanqie_new_post_backfill_v1 as adapter
    for status in ('confirmed','submission_unknown'):
        a,env,store,probe,request,request_ref=package(tmp_path/status)
        spec=importlib.util.spec_from_file_location('private_fanqie_cli',new.ROOT/'scripts/run_fanqie_account.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        monkeypatch.setattr(cli,'FanqieAccounts',lambda:a)
        launched=[]
        monkeypatch.setattr(cli,'launch_worker',lambda command,accounts:launched.append(command) or dict(status='private_queued',command_id=command['command_id']))
        monkeypatch.setattr(sys,'argv',['run_fanqie_account.py','backfill-new-publication','--resource',env['resource_id'],'--request',request_ref['path']])
        cli.main();assert json.loads(capsys.readouterr().out)['status']=='private_queued'
        command=launched[0];assert command['kind']==new.KIND and command['payload']==dict(environment_key=env['environment_key'],request=request_ref)
        calls=[];contexts=[]
        def native(page,*,request,request_ref,subject,guard,evidence_directory,claim_submission):
            calls.append(subject);guard();assert not Path(request['submit_claim_path']).exists()
            evidence_directory.mkdir(parents=True)
            form=dict(schema='fanqie_new_post_form/v1',location=dict(origin='https://kol.fanqieopen.com',path='/page/promotion-list'),scope_count=1,
                identity=dict(book_name=request['book_name'],alias=request['alias'],aigc=True),input_count=4,link_count=1,row_date_count=1,row_input_count=2,eligible=True,
                date=dict(value=request['new_publication']['publish_date']),link=dict(value=request['new_publication']['canonical_url']),other_inputs=[dict(value=''),dict(value='')],
                submit=dict(unique_count=1,tag='button',type='button',text='提交',enabled=True),add_delete_actions_performed=False)
            preflight=new.once(evidence_directory/'SUBMIT_PREFLIGHT.json',dict(schema='fanqie_new_post_backfill_preflight/v1',request=request_ref,subject=subject,
                target={k:request[k] for k in ('book_id','book_name','alias')},retained_records=[request['retained_publication']],new_publication=request['new_publication'],
                actual_form=form,observed_at=time.time(),submission_limit=1,no_add_delete_actions=True))
            claim=claim_submission(preflight);guard()  # The post-claim guard must accept this exact current execution.
            with pytest.raises(FileExistsError):claim_submission(preflight)
            records=[request['retained_publication'],{k:request['new_publication'][k] for k in ('canonical_url','publish_date')}]
            return dict(schema='fanqie_new_post_backfill/v1',status=status,submitted=True,submission_claim=claim,records=records,preflight=preflight)
        monkeypatch.setattr(adapter,'run_action',native)
        page=SimpleNamespace(_session=SimpleNamespace(worker_failure=lambda:None),tab_id='private-tab')
        handlers=make_handlers(a,env,page_provider=lambda ctx,url:SimpleNamespace(page=page),probe_provider=lambda ctx:dict(probe,observed_at=time.time()))
        def capture(ctx,payload):contexts.append(ctx);return handlers[new.KIND](ctx,payload)
        actor=BrowserControlActor(store,env['resource_id'],env['binding_version'],'private-owner',{new.KIND:capture})
        try:
            outcome=actor.run_next();assert outcome['state']=='succeeded';assert outcome['result']['confirmed']==(status=='confirmed')
            assert outcome['result']['requires_read_only_reconciliation']==(status=='submission_unknown')
            original_claim=Path(request['submit_claim_path']).read_bytes()
            again=handlers[new.KIND](contexts[0],command['payload']);assert again.result['status']==status and len(calls)==1
            assert a.queue(env['resource_id'],new.KIND,promotion_request=request_ref)['command_id']==command['command_id']
            changed_request=new.once(tmp_path/status/'REQUEST_OTHER_DIRECTORY.json',dict(request,at_epoch=time.time()))
            assert a.queue(env['resource_id'],new.KIND,promotion_request=changed_request)['command_id']==command['command_id']
            assert len(calls)==1 and Path(request['submit_claim_path']).read_bytes()==original_claim
        finally:actor.close()
