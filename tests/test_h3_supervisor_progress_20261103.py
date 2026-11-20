import json
from src.web.h3_manifest_progress import load_supervisor


def test_fresh_heartbeat_requires_process_identity(tmp_path):
    (tmp_path/'STATE.json').write_text(json.dumps(dict(status='monitoring',heartbeat_epoch=1000,supervisor={'pid':123})),encoding='utf-8')
    assert load_supervisor(tmp_path,now=1030,process_alive=lambda row:True)['protected']
    assert not load_supervisor(tmp_path,now=1030,process_alive=lambda row:False)['protected']


def test_stale_heartbeat_does_not_claim_alive(tmp_path):
    (tmp_path/'STATE.json').write_text(json.dumps(dict(status='monitoring',heartbeat_epoch=1000)),encoding='utf-8')
    result=load_supervisor(tmp_path,now=1100,process_alive=lambda row:True)
    assert not result['protected'] and '心跳已过期' in result['label']


def test_backoff_and_blocked_are_distinct(tmp_path):
    file=tmp_path/'STATE.json'
    file.write_text(json.dumps(dict(status='backoff',heartbeat_epoch=1000,next_retry_epoch=1090)),encoding='utf-8')
    result=load_supervisor(tmp_path,now=1030,process_alive=lambda row:True)
    assert result['protected'] and result['next_retry_epoch']==1090
    file.write_text(json.dumps(dict(status='blocked',heartbeat_epoch=1000,reason='unknown_claim_without_id')),encoding='utf-8')
    result=load_supervisor(tmp_path,now=1030,process_alive=lambda row:True)
    assert not result['protected'] and result['reason']=='unknown_claim_without_id'


def test_missing_or_unreadable_monitor_not_normal(tmp_path):
    assert not load_supervisor(tmp_path)['protected']
    (tmp_path/'STATE.json').write_text('{',encoding='utf-8')
    assert load_supervisor(tmp_path)['status']=='unavailable'
