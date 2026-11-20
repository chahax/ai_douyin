from types import SimpleNamespace

from src.platform_adapter.publish_verification import wait_for_published_video

URL='https://www.douyin.com/video/123456'


class LoadingPage:
    url=URL
    def __init__(self,states):self.states=states;self.reads=0;self.shots=0;self.waits=[]
    def inspect_published_video(self,*_a,**_k):
        state=self.states[min(self.reads,len(self.states)-1)];self.reads+=1;return state
    def wait_for_timeout(self,ms):self.waits.append(ms)
    def screenshot(self,**_):self.shots+=1


def state(ready,**changes):
    return dict(verified=ready,player={'ready':ready,'error':False,'duration':ready},**changes)


def test_unready_then_ready_uses_same_exact_work_guard_and_one_final_screenshot():
    page=LoadingPage([state(False),state(False),state(True)])
    guards=[]
    result=wait_for_published_video(page,'123456',dispatch_guard=lambda:guards.append(True),evidence_path='fixture.png')
    assert result['verified'] and result['verification_wait']['attempts']==3
    assert result['verification_wait']['stop_reason']=='verified'
    assert page.reads==3 and page.shots==1 and page.waits==[2000,2000]
    assert len(guards)>=3


def test_always_unready_stays_pending_after_bounded_eight_reads_one_screenshot():
    page=LoadingPage([state(False)])
    result=wait_for_published_video(page,'123456',evidence_path='fixture.png')
    assert not result['verified'] and result['verification_wait']['attempts']==8
    assert page.reads==8 and page.shots==1 and len(page.waits)==7


def test_moderation_blocked_service_stops_immediately_without_comment(tmp_path,monkeypatch):
    # Replay the real frozen pre-click AI chronology via the existing service
    # fixture, but make the native public UI return a moderation rejection.
    import src.operations_accounts.publication_reconciliation as module
    import src.operations_accounts.publication_reconciliation_authorization as auth
    import src.operations_accounts.publication_comment as comments
    from pathlib import Path
    import json
    rows=[json.loads(s)for s in (Path(__file__).resolve().parents[1]/'data/development_checkpoints/publication_reconciliation_browser_20261019/ORIGINAL_JOURNAL.jsonl').read_text(encoding='utf-8').splitlines()]
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(auth,'get_verified_reconciliation_inputs',lambda _:dict(prepared={'title':'原片','hashtags':['劳动法'],'comment':'原批准评论'},
        authorization={},journal_rows=rows,original_command={'payload':{'authorization':{'original':True}}}))
    monkeypatch.setattr(comments,'post_authorized_publication_comment',lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('must not comment')))
    page=LoadingPage([state(False,moderation_markers=['审核不通过'],review_status='not_clear')])
    page.discover_published_work=lambda _:dict(verified=True,post_id='123456',publish_url=URL)
    page.goto=lambda _:None;page._cmd=lambda *_a,**_k:None
    session=SimpleNamespace(open_page=lambda _:page)
    resource=SimpleNamespace(account_uuid='account',account_key='account01',reconciliation_session=session,
        context=SimpleNamespace(),runtime=SimpleNamespace(verify_identity=lambda *_a,**_k:SimpleNamespace(healthy=True)))
    result=module.run_reconciliation(SimpleNamespace(task_id='a'*32,resource=resource,check_dispatch=lambda:None),
        {'account_uuid':'account','account_key':'account01','original_command_id':'b'*32})
    assert result['status']=='verification_pending' and result['comment']['status']=='not_submitted'
    assert result['publish_evidence']['verification_wait']['attempts']==1 and page.reads==1
