import copy
import pytest
from scripts.run_cohort_video import pack_segments,natural


def fixture():
    counts=[22,23,14,29,15,25,25,0,12]
    fixed=[0,.5,.5,2,0,.2,.4,3.5,1.7]
    pauses=[.4,.2,.3,.6,.4,.5,.2,.2,.4]
    rates=[4.6,5,4.4,4.8,4.5,4.7,4.9,5,4.6]
    rows=[];scenes=[]
    for i,(n,action,pause,cps) in enumerate(zip(counts,fixed,pauses,rates)):
        rows.append({'beat':{'id':f'B{i+1:02d}','speakers':['A'] if n else [],'pause':pause,'cps':cps,'ops':[]},
            'minimum_action_seconds':action,'duration':action+pause+n/cps,'before':{'props':{'P':'A:left'}},'after':{'props':{'P':'A:left'}}})
        scenes.append({'lines':[{'speaker':'A','text':'甲'*n}] if n else []})
    return {'kind':'short','transactions':{}},scenes,{'beats':rows,'duration':45}


def test_native_integer_groups_preserve_every_beat_and_action_time():
    c,d,t=fixture();before=copy.deepcopy(t);packed=pack_segments(c,d,t)
    assert sum(s['duration'] for _,s in packed)==45
    assert [j for group,_ in packed for j in group]==list(range(9))
    assert all(4<=s['duration']<=15 and s['duration']==int(s['duration']) for _,s in packed)
    assert t==before
    assert packed[-1][1]['beats'][0]['minimum_action_seconds']==pytest.approx(4.3)
    for group,segment in packed:
        for j,row in zip(group,segment['beats']):assert row['before']==t['beats'][j]['before'] and row['after']==t['beats'][j]['after']


def test_pack_refuses_to_fake_an_impossible_duration():
    c,d,t=fixture();d[0]['lines'][0]['text']='甲'*200
    with pytest.raises(ValueError,match='No valid'):pack_segments(c,d,t)


def test_reference_locations_are_rendered_without_changing_ownership():
    c={'characters':{'T':{'name':'租客'},'L':{'name':'房东'}},'props':{'P1':{'name':'钥匙'}}}
    assert natural('P1 T:right -> L:left',c)=='钥匙 租客右手 -> 房东左手'


def test_integer_extension_does_not_squeeze_longer_dialogue():
    c,d,t=fixture();d[0]['lines'][0]['text']='甲'*31
    with pytest.raises(ValueError,match='No valid'):pack_segments(c,d,t)
    packed=pack_segments(c,d,t,allow_integer_extension=True)
    assert 45<sum(s['duration'] for _,s in packed)<=48
    assert packed[0][1]['duration']>=6
    assert packed[-1][1]['beats'][0]['minimum_action_seconds']==pytest.approx(4.3)


def test_execution_repair_rejects_duplicate_dialogue_and_changed_model_output(tmp_path):
    from scripts.run_cohort_video import execution_prompt,save,identity
    shot={'shot_id':'S03','model_prompt_zh':'原始动作和唯一对白','dialogue':'租客：你自己看。'}
    def manifest(constraints):
        candidate={'execution_constraints':constraints}
        save(tmp_path/'candidate.json',candidate)
        save(tmp_path/'raw.txt',candidate)
        save(tmp_path/'model_run.json',{'model_calls':1})
        save(tmp_path/'failed_review.json',{'decision':'failed'})
        save(tmp_path/'previous_manifest.json',{'test_shot':'S03'})
        save(tmp_path/'repair.json',dict(shot_id='S03',**{key:identity(tmp_path/file) for key,file in [('model_candidate','candidate.json'),('model_raw','raw.txt'),('model_run','model_run.json'),('failed_review','failed_review.json'),('previous_manifest','previous_manifest.json')]}))
        return {'execution_repair':identity(tmp_path/'repair.json')}
    m=manifest('屏幕朝房东，从房东肩后同侧拍摄。')
    assert execution_prompt(m,shot).startswith(shot['model_prompt_zh'])
    save(tmp_path/'candidate.json',{'execution_constraints':'换成另一个未经审核的动作'})
    with pytest.raises(ValueError):execution_prompt(m,shot)
    m=manifest('先说你自己看，再展示屏幕。')
    with pytest.raises(ValueError,match='repeat authored dialogue'):execution_prompt(m,shot)
    m=manifest('侧面见手机背壳；肩后拍屏幕。')
    from scripts.run_cohort_video import read
    repair=read(tmp_path/'repair.json');repair['recipe']='replace_camera/v2';save(tmp_path/'repair.json',repair)
    m['execution_repair']=identity(tmp_path/'repair.json')
    shot['model_prompt_zh']='本段内3.76-12.00秒：手机屏幕亮起朝向镜头\n仅租客说一次：你自己看。\n手机仍女左手'
    result=execution_prompt(m,shot)
    assert '屏幕亮起朝向镜头' not in result
    assert '仅租客说一次：你自己看。' in result and '手机仍女左手' in result
