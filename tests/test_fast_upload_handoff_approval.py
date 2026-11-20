"""Only the frozen v4 26/27 film continuation extends the v3 idle handoff."""
import hashlib
import json
import sqlite3

import pytest

from test_active_quota_idle_handoff import active, assert_writer_fenced
from test_idle_browser_control_handoff import isolated


def save_ref(root,name,value):
    path=root/name;path.write_text(json.dumps(value),encoding='utf8')
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def fast_approval(active):
    m,service,store,command,args,root,path,approval=active
    for key in ('operator_close_unknown_publication','archive_submission_lock','original_outcome_known','original_command_id'):
        approval.pop(key)
    same_film={'prepared':{'path':str(root/'prepared.json'),'sha256':'1'*64},
               'video':{'path':str(root/'film.mp4'),'sha256':'2'*64}}
    previous=dict(schema='publication_single_retry/20261019/v3',scope='publish_only',
        account_uuid='review:A',account_key='A',utc_day='2026-10-19',
        baseline_daily_runs=25,max_daily_runs=26,active_control_revision=42,**same_film)
    approval.update(schema='publication_fast_upload_retry_user_authorization/20261019/v1',
        user_statement='允许',approval_question='是否允许再追加本视频发布1次，部署修复后继续？',
        baseline_daily_runs=26,max_daily_runs=27,previous_command_id='previous-known-failed',**same_film,
        previous_authorization=save_ref(root,'V3.json',previous),
        previous_command=save_ref(root,'previous.json',{'command_id':'previous-known-failed',
            'account_id':'review:A','kind':'publish','state':'failed','result':{'status':'upload_failed'}}),
        previous_journal=save_ref(root,'previous-journal.json',{'stage':'upload_failed'}),
        previous_final_state=save_ref(root,'previous-final.json',{'status':'failed'}))
    path.write_text(json.dumps(approval,ensure_ascii=False),encoding='utf8')
    args[args.index('--approval-sha256')+1]=hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(root/'data/douyin.db') as db:db.execute('UPDATE account_runtime_state SET daily_runs=26')
    return active


def test_v4_26_idle_keeps_both_fences_and_leaves_control_quota_and_queue_untouched(active):
    m,service,store,command,args,root,path,approval=fast_approval(active)
    stop=service.terminate
    def checked_stop():
        assert_writer_fenced(root/'data/account_refresh.db')
        assert_writer_fenced(root/'data/account_browser_control.db')
        stop()
    service.terminate=checked_stop
    m.main()
    assert service.terminated==1 and store.get(command['command_id'])==command
    with sqlite3.connect(root/'data/douyin.db') as db:
        assert db.execute('SELECT daily_runs FROM account_runtime_state').fetchone()[0]==26
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        assert db.execute('SELECT state,revision FROM account_controls').fetchone()==('active',42)
    receipt=json.loads((root/'handoff.json').read_text())
    assert receipt['active_quota_idle_snapshot']['daily_runs']==26


@pytest.mark.parametrize('change',['wrong_daily','wrong_cap','extra_recovery','other_v3_film','unknown_previous','changed_evidence'])
def test_v4_refuses_other_quota_scope_or_previous_chain(active,change):
    m,service,store,command,args,root,path,approval=fast_approval(active)
    if change=='wrong_daily':
        with sqlite3.connect(root/'data/douyin.db') as db:db.execute('UPDATE account_runtime_state SET daily_runs=25')
    elif change=='wrong_cap':approval['max_daily_runs']=28
    elif change=='extra_recovery':approval['additional_recovery_runs']=1
    elif change=='other_v3_film':approval['video']['sha256']='3'*64
    elif change=='unknown_previous':
        approval['previous_command']=save_ref(root,'unknown-previous.json',{'command_id':'previous-known-failed',
            'account_id':'review:A','kind':'publish','state':'outcome_unknown','result':{'status':'upload_failed'}})
    else:(root/'previous-journal.json').write_text('changed',encoding='utf8')
    if change not in ('wrong_daily','changed_evidence'):
        path.write_text(json.dumps(approval),encoding='utf8')
        args[args.index('--approval-sha256')+1]=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError):m.main()
    assert service.terminated==0 and store.snapshot('review:A')['owner']['state']=='active'


def test_original_v3_25_approval_still_valid(active):
    m,service,store,command,args,root,path,approval=active
    value,_=m.active_quota_approval(path,args[args.index('--approval-sha256')+1],'review:A')
    assert value['baseline_daily_runs']==25 and value['max_daily_runs']==26
