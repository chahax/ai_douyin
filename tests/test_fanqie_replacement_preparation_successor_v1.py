"""Private SQL lifecycle for the evidenced pre-input failure successor."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import pytest

from src.operations_accounts import fanqie_cleanup_rebind_v1 as runtime
from src.operations_accounts import fanqie_new_publication_backfill_v1 as files
from src.platform_adapter import fanqie_replacement_forms_v1 as flow


def test_known_preparation_successor_late_claim_guard_and_once_are_same_request(tmp_path):
    root=files.ROOT;actual=root/'data/fanqie_account_control/commands/7c0836fdb4164782b9f371657fa5a2e2'
    result=files.read(files.reference(actual/'CLEANUP_REBIND_RESULT.json'));old=files.read(result['request'])
    authority=flow.save(tmp_path/'AUTHORITY.json',files.read(old['authority']));old=dict(old,authority=authority)
    oldref=flow.save(tmp_path/'OLD_REQUEST.json',old);subject=dict(result['subject'],task_id='private-prior',owner_id='private-old-owner',generation=1)
    folder=tmp_path/'commands'/subject['task_id'];blankref=flow.save(folder/'replacement/BLANK_FORM.json',flow.read(flow.reference(actual/'replacement/BLANK_FORM.json')))
    result=dict(result,request=oldref,subject=subject);resultref=flow.save(folder/'CLEANUP_REBIND_RESULT.json',result)
    binding=flow.save(folder/'CLEANUP_REBIND_RESULT_BINDING.json',dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=oldref,subject=subject,result=resultref))
    review=files.read(files.reference(root/'data/qa/fanqie_replacement_blank_form_failure_independent_20261118/ACTUAL_KNOWN_PREPARATION_FAILURE_REVIEW.json'))
    review.update(result=resultref,request=oldref,subject=subject,blank_form=blankref,result_binding=binding)
    reviewref=flow.save(tmp_path/'REVIEW.json',review)
    request=dict(old,known_backfill_preparation_failure=resultref,preparation_failure_review=reviewref,
                 preparation_source_before=files.reference(root/'data/production_trials/fanqie_cleanup_rebind_20261118_v1/first_empty_editor/SOURCE_BEFORE.json'),
                 add_empty_douyin_draft_row=True,empty_douyin_draft_add_limit=1,remove_empty_other_draft_row=False,empty_draft_removal_limit=0)
    ref=flow.save(tmp_path/'NEW_REQUEST.json',request);old_bytes=Path(resultref['path']).read_bytes();dbfile=tmp_path/'private.db'
    with sqlite3.connect(dbfile) as db:
        db.execute('CREATE TABLE browser_control_commands(command_id TEXT,state TEXT,kind TEXT,account_id TEXT,binding_version TEXT,payload TEXT,result TEXT,owner_id TEXT,generation INTEGER,idempotency_key TEXT)')
        db.execute('INSERT INTO browser_control_commands VALUES(?,?,?,?,?,?,?,?,?,?)',(subject['task_id'],'failed',runtime.KIND,old['resource_id'],old['binding_version'],json.dumps(dict(environment_key=old['environment_key'],request=oldref)),json.dumps(dict(result['result'],result_evidence=resultref)),subject['owner_id'],subject['generation'],runtime.idempotency_key(old)))
    class Accounts:
        def folder(self,cid):return tmp_path/'commands'/cid
        @contextmanager
        def connection(self):
            db=sqlite3.connect(dbfile);db.row_factory=sqlite3.Row
            try:yield db
            finally:db.close()
    accounts=Accounts();check=lambda **kw:runtime._known_backfill_preparation_failure(request,accounts,request_ref=ref,**kw)
    check();runtime.require_unclaimed(request)
    assert runtime.idempotency_key(old)!=runtime.idempotency_key(request)
    current=dict(subject,task_id='private-successor',owner_id='private-new-owner',generation=2)
    target={k:request[k] for k in ('book_id','book_name','alias','publish_type')}
    proof=flow.save(accounts.folder(current['task_id'])/'replacement/PREFLIGHT.json',dict(schema='fanqie_replacement_backfill_preflight/v1',target=target,request=ref,subject=current,new_publication=request['new_publication'],native_identity=request['new_native_identity']))
    claim_path=tmp_path/'REPLACEMENT_BACKFILL_SUBMIT_CLAIM.json'
    claim=files.once(claim_path,dict(schema='fanqie_replacement_backfill_claim/v1',target=target,request=ref,subject=current,preflight=proof))
    check(active_subject=current)  # Actual repeated guard after late creation.
    with pytest.raises(Exception,match='original_replacement_claim_preserved'):runtime.require_unclaimed(request)
    with pytest.raises(FileExistsError):files.once(claim_path,dict(no_replay=True))
    with accounts.connection() as db:
        db.execute('INSERT INTO browser_control_commands VALUES(?,?,?,?,?,?,?,?,?,?)',(current['task_id'],'running',runtime.KIND,old['resource_id'],old['binding_version'],json.dumps(dict(environment_key=old['environment_key'],request=ref)),'{}',current['owner_id'],current['generation'],runtime.idempotency_key(request)));db.commit()
    check()  # Idempotent public queue lookup accepts only this consumed slot.
    with pytest.raises(Exception,match='other_preparation_submission_claim'):check(active_subject=dict(current,owner_id='foreign'))
    assert files.reference(claim_path)==claim and Path(resultref['path']).read_bytes()==old_bytes
