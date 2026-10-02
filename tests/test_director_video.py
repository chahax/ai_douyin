import copy
import json
import pytest
from scripts import run_director_video as d
from src.content_factory import video_campaign as c
from test_video_campaign import setup_campaign,candidate

def test_pending_text_cannot_enter_video(tmp_path):
    d.save(tmp_path/'trial.json',{'status':'in_progress','protocol':d.protocol()})
    d.save(tmp_path/'final.review.json',{})
    with pytest.raises(ValueError,match='accepted'):d.build_script(tmp_path)

def test_bundle_cannot_swap_reviewed_projection(tmp_path,monkeypatch):
    review=tmp_path/'review.json';d.save(review,{'decision':'passed'})
    source={'source_review':d.identity(review),'shots':[{'dialogue':'unchanged'}]}
    monkeypatch.setattr(d,'build_script',lambda _:copy.deepcopy(source))
    folder=tmp_path/'bundle';d.make_bundle(tmp_path,folder)
    changed=d.read(folder/'script.json');changed['shots'][0]['dialogue']='changed'
    d.save(folder/'script.json',changed)
    # Updating only the bundle's file hash cannot disguise a different script.
    bundle=d.read(folder/'bundle.json');bundle['script']=d.identity(folder/'script.json');d.save(folder/'bundle.json',bundle)
    with pytest.raises(ValueError,match='projection'):d.verify_bundle(folder)

def test_existing_unknown_receipt_never_resubmits(tmp_path):
    d.save(tmp_path/'production.json',{'test_shot':'S01'})
    d.save(tmp_path/'S01.json',{'status':'submission_unknown'})
    with pytest.raises(ValueError,match='query only'):d.submit(tmp_path)

def test_new_verified_director_order_preserves_history(tmp_path,monkeypatch):
    path=setup_campaign(tmp_path);candidate(path,1)
    script=tmp_path/'new.json';c.write(script,{'schema':'director_video_script/v1'})
    identity={'path':str(script),'sha256':c.file_sha(script),'key':'new-director','shots':['S01','S02','S03','S04']}
    monkeypatch.setattr(c,'script_budget_identity',lambda _:identity)
    c.start_revision(path,authorization='try this new story',reason='different complete story',new_script=script)
    data=c.read(path)
    assert data['series'][0]['shots']==['S01','S02']
    assert data['shots']==data['series'][-1]['shots']==identity['shots']
    assert data['failed_outputs']==0

def test_spatial_repair_changes_composition_only_and_binds_raw(tmp_path):
    from pathlib import Path
    import json
    values={'previous_manifest':{'script_sha256':'source-sha','test_shot':'S01'},
      'failed_review':{'decision':'failed','checks':{'spatial_layout':False}},
      'model_candidate':{'composition':'corrected static camera'},'model_run':{'model_calls':1}}
    bindings={}
    for key,value in values.items():
        path=tmp_path/(key+'.json');d.save(path,value);bindings[key]=d.identity(path)
    raw=tmp_path/'raw.txt';raw.write_text(json.dumps(values['model_candidate']),encoding='utf-8');bindings['model_raw']=d.identity(raw)
    repair=tmp_path/'repair.json';d.save(repair,{'schema':'director_composition_repair/v1','shot_id':'S01',**bindings})
    manifest={'script_sha256':'source-sha','execution_repair':d.identity(repair)}
    shot={'shot_id':'S01','model_prompt_zh':'dialogue unchanged\n【composition】old\n【beats】unchanged\n【end_state】unchanged'}
    revised=d.execution_prompt(manifest,shot)
    assert revised=='dialogue unchanged\n【composition】corrected static camera\n【beats】unchanged\n【end_state】unchanged'
    raw.write_text('{"composition":"unreviewed"}',encoding='utf-8')
    with pytest.raises(ValueError):d.execution_prompt(manifest,shot)

def test_identity_restore_only_repeats_locked_appearance(tmp_path):
    shot={'shot_id':'S02','model_prompt_zh':'unchanged dialogue and actions'}
    script=tmp_path/'script.json'
    d.save(script,{'schema':'reference_director_video_script/v1','shots':[shot],'characters':[{'name':'父亲','appearance':'灰夹克，花白短发'}]})
    sha=d.identity(script)['sha256']
    previous=tmp_path/'previous.json';d.save(previous,{'script_sha256':sha,'test_shot':'S02'})
    review=tmp_path/'review.json';d.save(review,{'script_sha256':sha,'decision':'failed','checks':{'identity':False}})
    repair=tmp_path/'repair.json'
    value={'schema':'reference_identity_restore/v1','shot_id':'S02','source_script':d.identity(script),'previous_manifest':d.identity(previous),'failed_review':d.identity(review)}
    d.save(repair,value)
    manifest={'script_sha256':sha,'execution_repair':d.identity(repair)}
    result=d.execution_prompt(manifest,shot)
    assert result.startswith(shot['model_prompt_zh']+'\n') and '父亲：灰夹克，花白短发' in result
    d.save(review,{'script_sha256':sha,'decision':'pending','checks':{'identity':None}})
    value['failed_review']=d.identity(review);d.save(repair,value);manifest['execution_repair']=d.identity(repair)
    with pytest.raises(ValueError,match='identity failure'):d.execution_prompt(manifest,shot)
    manifest['script_sha256']='changed'
    with pytest.raises(ValueError,match='changed source'):d.execution_prompt(manifest,shot)

@pytest.mark.parametrize('version', ['v1','v2'])
def test_action_visibility_repair_preserves_story_and_requires_actual_failure(tmp_path,version):
    shot={'shot_id':'S04','model_prompt_zh':'original header\n摄影时间表（本段局部秒数，只规定观察与构图）：\nold camera\n人物动作时间表：\noriginal timed actions and silence'}
    script=tmp_path/'script.json'
    d.save(script,{'schema':'reference_director_video_script/v1','shots':[shot],'characters':[{'name':'父亲','appearance':'灰夹克'}]})
    sha=d.identity(script)['sha256']
    values={'previous_manifest':{'script_sha256':sha,'test_shot':'S04'},
            'failed_review':{'script_sha256':sha,'decision':'failed','checks':{'action_pace':False}},
            'model_candidate':{'composition':'hard cut to full body; show both feet crossing'},
            'model_run':{'model_calls':1}}
    bindings={'source_script':d.identity(script)}
    for key,value in values.items():
        path=tmp_path/(key+'.json');d.save(path,value);bindings[key]=d.identity(path)
    raw=tmp_path/'raw.txt';raw.write_text(json.dumps(values['model_candidate']),encoding='utf-8');bindings['model_raw']=d.identity(raw)
    repair=tmp_path/'repair.json'
    def manifest():
        d.save(repair,{'schema':'reference_action_visibility_repair/'+version,'shot_id':'S04',**bindings})
        return {'script_sha256':sha,'execution_repair':d.identity(repair)}
    result=d.execution_prompt(manifest(),shot)
    if version=='v1':
        assert result.startswith(shot['model_prompt_zh']+'\n')
    else:
        assert result.startswith('original header\n摄影时间表（本段局部秒数，只规定观察与构图）：\n')
        assert 'old camera' not in result
        assert '\n人物动作时间表：\noriginal timed actions and silence\n' in result
    assert '父亲：灰夹克' in result and values['model_candidate']['composition'] in result
    with pytest.raises(ValueError,match='changed source'):
        d.execution_prompt({**manifest(),'script_sha256':'changed'},shot)
    review=tmp_path/'failed_review.json'
    d.save(review,{'script_sha256':sha,'decision':'pending','checks':{'action_pace':None}})
    bindings['failed_review']=d.identity(review)
    with pytest.raises(ValueError,match='Actual action failure'):d.execution_prompt(manifest(),shot)
    d.save(review,values['failed_review']);bindings['failed_review']=d.identity(review)
    raw.write_text('{"composition":"changed without original"}',encoding='utf-8')
    bindings['model_raw']=d.identity(raw)
    with pytest.raises(ValueError,match='original model text'):d.execution_prompt(manifest(),shot)

def test_blocking_repair_changes_only_reviewed_father_and_camera(tmp_path):
    original_end={'父亲':'old gaze to wall','女儿':'unchanged inside floor'}
    shot={'shot_id':'S04','model_prompt_zh':'header\n摄影时间表（本段局部秒数，只规定观察与构图）：\nold camera\n人物动作时间表：\n0—1.5秒，父亲：old action\n2—3秒，女儿：unchanged step\n本段无对白。\n末态：'+json.dumps(original_end,ensure_ascii=False)+'\nunchanged closing'}
    script=tmp_path/'script.json'
    d.save(script,{'schema':'reference_director_video_script/v1','shots':[shot],'characters':[{'name':'父亲','appearance':'灰夹克'}]})
    sha=d.identity(script)['sha256']
    authored={'composition':'fixed wide shot','father_action':'step aside and lower gaze','father_end_state':'look at open floor'}
    values={'previous_manifest':{'script_sha256':sha,'test_shot':'S04'},
        'failed_review':{'script_sha256':sha,'source_sha256':'video-sha','decision':'failed','checks':{'action_pace':False}},
        'user_rejection':{'source_sha256':'video-sha','decision':'rejected'},
        'model_candidate':authored,'model_run':{'model_calls':1}}
    bindings={'source_script':d.identity(script)}
    for key,value in values.items():
        path=tmp_path/(key+'.json');d.save(path,value);bindings[key]=d.identity(path)
    raw=tmp_path/'raw.txt';raw.write_text(json.dumps(authored),encoding='utf-8');bindings['model_raw']=d.identity(raw)
    repair=tmp_path/'repair.json'
    def manifest():
        d.save(repair,{'schema':'reference_blocking_repair/v1','shot_id':'S04',**bindings})
        return {'script_sha256':sha,'execution_repair':d.identity(repair)}
    result=d.execution_prompt(manifest(),shot)
    assert '0—1.5秒，父亲：step aside and lower gaze' in result
    assert '2—3秒，女儿：unchanged step\n本段无对白。' in result
    end=json.loads(next(row for row in result.splitlines() if row.startswith('末态：'))[3:])
    assert end=={'父亲':authored['father_end_state'],'女儿':original_end['女儿']}
    assert 'old action' not in result and 'old gaze' not in result and 'old camera' not in result
    assert result.startswith('header\n') and '\nunchanged closing\n' in result
    anchor=tmp_path/'user_rejected_review.json';d.save(anchor,values['failed_review'])
    bindings['user_rejected_review']=d.identity(anchor)
    latest=tmp_path/'failed_review.json'
    d.save(latest,{'script_sha256':sha,'source_sha256':'later-video','decision':'failed','checks':{'spatial_layout':False}})
    bindings['failed_review']=d.identity(latest)
    assert d.execution_prompt(manifest(),shot)==result
    changed={**values['failed_review'],'script_sha256':'other-script'}
    d.save(anchor,changed);bindings['user_rejected_review']=d.identity(anchor)
    with pytest.raises(ValueError,match='source-bound user rejection'):d.execution_prompt(manifest(),shot)
    d.save(anchor,values['failed_review']);bindings['user_rejected_review']=d.identity(anchor)
    rejection=tmp_path/'user_rejection.json'
    d.save(rejection,{'decision':'rejected','source_sha256':'other-video'})
    bindings['user_rejection']=d.identity(rejection)
    with pytest.raises(ValueError,match='source-bound user rejection'):d.execution_prompt(manifest(),shot)
