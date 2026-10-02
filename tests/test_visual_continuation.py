import pytest
from src.content_factory import video_campaign as c
from test_video_campaign import setup_campaign, candidate, generated_review


def test_visual_only_review_requires_explicit_authorization(tmp_path):
    path=setup_campaign(tmp_path); folder,m,r=candidate(path,1)
    c.reserve(folder,m,r)
    review=generated_review(folder,r,True); value=c.read(review)
    value['decision']='visual_passed_audio_pending'
    for k in c.AUDIO_CHECKS:value['checks'][k]=None
    value['creative_checks']={'visual_storytelling':True}
    value['observations']=[o for o in value['observations'] if o['check'] in c.VISUAL_CHECKS]
    value['observations'].append({'check':'visual_storytelling','time_seconds':1,'notes':'Actual visible reaction observed','evidence':['observed.txt']})
    c.write(review,value)
    with pytest.raises((ValueError,KeyError)):
        c.review(folder,'S01',review)
    proof=tmp_path/'authorization.json'
    c.write(proof,{'schema':'visual_continuation_authorization/v1','allow_visual_continuation':True,
                   'user_quote':'允许先完成画面，声音口型留待整片审查','deferred_checks':list(c.AUDIO_CHECKS)})
    # Test an explicitly scoped series, without rewriting the pending media evidence.
    with c.ledger(path) as data:
        data['current_series_id']='series_test'
        data['series']=[{'id':'series_test','runs':[str(folder)],'visual_continuation_authorization':{'path':str(proof),'sha256':c.file_sha(proof)}}]
        data['attempts'][0]['series_id']='series_test'
    m=c.read(folder/'production.json');m['campaign_series_id']='series_test';c.write(folder/'production.json',m)
    result=c.review(folder,'S01',review)
    assert result['decision']=='visual_passed_audio_pending'
    data=c.read(path); attempt=data['attempts'][0]
    assert set(attempt['uninspected_checks'])==set(c.AUDIO_CHECKS)
    assert c.attempt_allows_continuation(data,attempt)
    assert not c.read(review)['checks']['lip_sync']
    value['checks']['action_pace']=False
    assert not c.review_allows_continuation(data,'series_test',value)
    value['checks']['action_pace']=True;value['checks']['speaker_voice']=False
    assert not c.review_allows_continuation(data,'series_test',value)
    proof.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='authorization changed'):
        c.attempt_allows_continuation(data,attempt)
