"""Ordinary publish comments receive the actual same-journal full proof only."""
from contextlib import nullcontext
from dataclasses import asdict
import hashlib,json
from types import SimpleNamespace

import pytest

from src.operations_accounts import browser_control_runtime as module
from src.operations_accounts import publication_comment
from src.platform_adapter import douyin_adapter
from src.platform_adapter.models import PublishRequest,PublishResult


@pytest.fixture
def publication(tmp_path,monkeypatch):
    video=tmp_path/'original.mp4';video.write_bytes(b'local frozen video fixture')
    request=PublishRequest(str(video),'冻结原标题',hashtags=[' #劳动法 ','普法知识'])
    payload={'authorization':{'explicit_user_statement':'Publish and explain this exact work','comment':'原授权评论'},
        'request':asdict(request),'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest()}
    context=SimpleNamespace(account_key='account01',account_uuid='review:A')
    resource=SimpleNamespace(account_key=context.account_key,account_uuid=context.account_uuid,context=context,ensure_session=lambda:None)
    session=SimpleNamespace(stop=lambda:None)
    ctx=SimpleNamespace(resource=resource)
    journal=tmp_path/'same-publish.jsonl';comments=[]
    full={'verified':True,'expected_post_id':'123456789','post_id':'123456789',
        'expected_title':request.title,'expected_hashtags':request.normalized_hashtags(),
        'actual_nested_proof':{'scope':'observed public UI','player_verified':True}}
    def write(evidence=None,*,last=None):
        rows=[{'stage':'prepared','title':request.title,'hashtags':request.normalized_hashtags(),
               'video_path':str(video.resolve()),'video_sha256':payload['video_sha256']},
              {'stage':'ai_declaration_verified','set_selected':True,'evidence':{'verified':True}},
              {'stage':'post_publish_checked','evidence':full if evidence is None else evidence}]
        if last is not None:rows.append({'stage':'post_publish_checked','evidence':last})
        journal.write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)+'\n',encoding='utf8')
    write()
    class Adapter:
        def __init__(self,**kwargs):self.publish_workflow=SimpleNamespace(_journal_path=journal)
        def publish_video(self,request):
            return PublishResult(True,'published',post_id='123456789',publish_url='https://www.douyin.com/video/123456789')
    def comment(adapter,frozen_command,post_id):
        comments.append((frozen_command,post_id));return {'status':'sent_visible'}
    monkeypatch.setattr(douyin_adapter,'DouyinAdapter',Adapter)
    monkeypatch.setattr(module,'BorrowedSession',lambda resource,role:session)
    monkeypatch.setattr(module,'_publication_lease',lambda resource:nullcontext())
    monkeypatch.setattr(module,'_admission',lambda ctx,phase:None)
    monkeypatch.setattr(publication_comment,'post_authorized_publication_comment',comment)
    return ctx,payload,full,write,comments


def test_full_same_source_proof_is_forwarded_unchanged_and_no_comment_path_stays_unchanged(publication):
    ctx,payload,full,write,comments=publication
    result=module._publish(ctx,payload)
    assert isinstance(result,dict) and result['comment_pending'] is False
    frozen,post_id=comments[0]
    assert post_id=='123456789' and frozen['title']=='冻结原标题'
    assert frozen['hashtags']==['劳动法','普法知识']
    assert frozen['publish_evidence']==full
    assert result['comment_publish_evidence']==full
    # The pre-existing summary stays a summary, not fabricated full verification.
    assert result['publish_evidence']['post_verified'] is True
    assert 'expected_title' not in result['publish_evidence']
    payload['authorization'].pop('comment')
    write(dict(full,expected_title='Unrelated title'))
    normal=module._publish(ctx,payload)
    assert isinstance(normal,dict) and normal['comment_pending'] is False
    assert len(comments)==1 and 'comment_publish_evidence' not in normal


def test_wrong_id_title_tags_missing_proof_or_failed_final_check_never_calls_comment(publication):
    ctx,payload,full,write,comments=publication
    missing=dict(full);missing.pop('expected_title')
    variants=[dict(full,expected_post_id='987654321'),dict(full,expected_title='Wrong title'),
        dict(full,expected_hashtags=['Different']),missing]
    for evidence in variants:
        write(evidence)
        result=module._publish(ctx,payload)
        assert result.state=='outcome_unknown' and result.result['comment_pending'] is True
        assert result.result['comment']=={'status':'publish_evidence_unbound','submitted':False}
    write(last=dict(full,verified=False))
    result=module._publish(ctx,payload)
    assert result.state=='outcome_unknown' and comments==[]


def test_authorized_but_unsubmitted_comment_keeps_publication_unknown_and_pending(publication,monkeypatch):
    ctx,payload,full,write,comments=publication
    def unsubmitted(adapter,command,post_id):
        comments.append(command);return {'status':'work_scope_unverified','submitted':False}
    monkeypatch.setattr(publication_comment,'post_authorized_publication_comment',unsubmitted)
    result=module._publish(ctx,payload)
    assert result.state=='outcome_unknown'
    assert result.result['comment_pending'] is True
    assert result.result['comment']['status']=='work_scope_unverified'
    assert comments[0]['publish_evidence']==full
