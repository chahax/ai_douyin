from types import SimpleNamespace


def test_reconciliation_full_display_challenge_returns_human_without_comment(tmp_path,monkeypatch):
    import src.operations_accounts.publication_reconciliation as module
    import src.operations_accounts.publication_autonomous_reconciliation as router
    import src.operations_accounts.publication_comment as comments
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(router,'get_verified_reconciliation_inputs',lambda _:dict(
        prepared={'title':'冻结原标题','hashtags':['劳动法'],'comment':'原批准评论'},authorization={}))
    monkeypatch.setattr(comments,'post_authorized_publication_comment',lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('no comment under challenge')))
    reads=[]
    def inspect(*_a,**_k):
        reads.append(True);return {'verified':False,'human_required':True,'reason':'native_challenge_visible'}
    url='https://www.douyin.com/video/123456'
    page=SimpleNamespace(url=url,wait_for_timeout=lambda _:None,goto=lambda _:None,_cmd=lambda *_a,**_k:None,
        inspect_published_video=inspect,discover_published_work=lambda _:dict(verified=True,post_id='123456',publish_url=url))
    resource=SimpleNamespace(account_uuid='account',account_key='account01',context=SimpleNamespace(),
        reconciliation_session=SimpleNamespace(open_page=lambda _:page),
        runtime=SimpleNamespace(verify_identity=lambda *_a,**_k:SimpleNamespace(healthy=True)))
    result=module.run_reconciliation(SimpleNamespace(task_id='a'*32,resource=resource,check_dispatch=lambda:None),
        {'account_uuid':'account','account_key':'account01','original_command_id':'b'*32})
    assert result['status']=='human_required'and result['comment']['status']=='not_submitted'
    assert result['publish_evidence']['post_verified']is False and len(reads)==1
