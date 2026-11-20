import pytest
from src.content_factory import video_campaign as c
from test_video_campaign import setup_campaign, candidate, generated_review


def new_story(tmp_path, dialogue='new dialogue'):
    path = tmp_path / (dialogue.replace(' ', '_')+'.json')
    c.write(path, {'schema':'script_screenplay/v1','characters':[{'name':'A','identity':'owner'}],
                  'version':{'shots':[{'shot_id':s,'duration_seconds':5,'dialogue_speaker':'A',
                                      'dialogue':dialogue,'action':'points to own paper'} for s in ['S01','S02']]}})
    return path


def old_failed_campaign(tmp_path):
    path=setup_campaign(tmp_path)
    for n in range(1,11):
        folder,manifest,record=candidate(path,n)
        c.reserve(folder,manifest,record)
        c.review(folder,'S01',generated_review(folder,record,False))
    return path


def new_candidate(path, story, number):
    folder=path.parent/f'new_{number}'; folder.mkdir()
    c.write(folder/'production.json',{'shots':['S01','S02'],'api_model':'test-model','provider':'ark_api',
                                     'source_screenplay':str(story),'script_sha256':f'new-{number}'})
    c.attach(folder,path)
    return folder,c.read(folder/'production.json'),{'shot':'S01','script_sha256':f'new-{number}','prompt_sha256':f'new-prompt-{number}'}


def test_new_script_starts_zero_preserves_history_and_stops_at_own_tenth(tmp_path):
    path=old_failed_campaign(tmp_path); old=c.read(path)['attempts']
    story=new_story(tmp_path)
    result=c.start_revision(path,authorization='user: each new script resets',reason='new script trial',new_script=story)
    assert result['failed_outputs']==0
    assert c.read(path)['attempts']==old
    assert c.lifetime_failed_count(c.read(path))==10
    for n in range(1,11):
        folder,m,r=new_candidate(path,story,n); c.reserve(folder,m,r)
        assert c.review(folder,'S01',generated_review(folder,r,False))['failed_outputs']==n
    assert c.lifetime_failed_count(c.read(path))==20
    folder,m,r=new_candidate(path,story,11)
    with pytest.raises(ValueError,match='Ten failed'): c.reserve(folder,m,r)
    with pytest.raises(ValueError,match='already has a budget'):
        c.start_revision(path,authorization='retry',reason='same',new_script=story)


def test_reformat_cannot_reset_and_unresolved_task_still_blocks(tmp_path):
    path=old_failed_campaign(tmp_path); story=new_story(tmp_path)
    c.start_revision(path,authorization='new script allowed',reason='new',new_script=story)
    other=tmp_path/'reformatted.json'; other.write_text(story.read_text().replace('\n',''),encoding='utf-8')
    with pytest.raises(ValueError,match='already has a budget'):
        c.start_revision(path,authorization='retry',reason='same content',new_script=other)
    folder,m,r=new_candidate(path,story,1); c.reserve(folder,m,r)
    before=path.read_bytes()
    with pytest.raises(ValueError,match='outstanding'):
        c.start_revision(path,authorization='new again',reason='new story',new_script=new_story(tmp_path,'different'))
    assert path.read_bytes()==before


def test_wrong_script_cannot_join_budget(tmp_path):
    path=old_failed_campaign(tmp_path); story=new_story(tmp_path)
    c.start_revision(path,authorization='new script',reason='trial',new_script=story)
    with pytest.raises(ValueError,match='differs'):
        new_candidate(path,new_story(tmp_path,'unrelated'),1)


def test_pacing_revision_retains_failure_count_and_binds_new_script(tmp_path):
    path=setup_campaign(tmp_path); story=new_story(tmp_path)
    candidate(path,0)  # Register the initial campaign shot order.
    c.start_revision(path,authorization='new story',reason='trial',new_script=story)
    folder,m,r=new_candidate(path,story,1); c.reserve(folder,m,r)
    c.review(folder,'S01',generated_review(folder,r,False))
    old=c.read(path); old_key=old['series'][-1]['script_budget_key']
    revised=tmp_path/'pacing.json'; value=c.read(story)
    value['version']['shots'][0]['duration_seconds']=7
    value['version']['shots'][0]['action']='wait before asking'
    c.write(revised,value)
    result=c.start_revision(path,authorization='revise pacing and generate',reason='reaction timing',revised_script=revised)
    assert result['failed_outputs']==1
    current=c.read(path)
    assert current['series'][-1]['script_budget_key']==old_key
    assert current['attempts']==old['attempts']
    assert c._failed_count(current)==1
    assert c.lifetime_failed_count(current)==1
    with pytest.raises(ValueError,match='already has a budget'):
        c.start_revision(path,authorization='retry',reason='cannot reset revised story',new_script=revised)
    folder,m,r=new_candidate(path,revised,2); c.reserve(folder,m,r)
    assert c.read(path)['attempts'][-1]['status']=='awaiting_generation_or_review'


def test_pacing_revision_cannot_evade_limit(tmp_path):
    path=old_failed_campaign(tmp_path); story=new_story(tmp_path)
    with pytest.raises(ValueError,match='Ten failed'):
        c.start_revision(path,authorization='revise pacing',reason='timing',revised_script=story)


def test_pacing_revision_rejects_changed_dialogue(tmp_path):
    path=setup_campaign(tmp_path); story=new_story(tmp_path)
    candidate(path,0)
    c.start_revision(path,authorization='new story',reason='trial',new_script=story)
    before=path.read_bytes()
    with pytest.raises(ValueError,match='preserve characters'):
        c.start_revision(path,authorization='pacing',reason='timing',revised_script=new_story(tmp_path,'different'))
    assert path.read_bytes()==before
