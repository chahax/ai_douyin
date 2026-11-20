import pytest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.patching import bind_patches,retime_beats

def test_program_owns_hash_and_rejects_changed_base():
    old={'beats':[{'id':'a','action':'站着'},{'id':'b','action':'坐着'}]}
    proposal=[{'id':'a','replacement':{'id':'a','action':'走动'}}]
    bound=bind_patches(old,proposal,{'a'},c.digest(old))
    new=c.apply_record_patches(old,bound,{'a'},c.digest(old),lambda _:None)
    assert new['beats'][1]==old['beats'][1]
    with pytest.raises(ValueError,match='stale'):bind_patches(old,proposal,{'a'},'bad')
    with pytest.raises(ValueError,match='scope'):bind_patches(old,proposal,{'b'},c.digest(old))


def test_retiming_moves_audio_but_preserves_unselected_prose_and_original():
    old={'beats':[{'id':'a','start':0,'end':4,'action':'新时长','audio':[]},
        {'id':'b','start':10,'end':18,'action':'这段文字必须原样保持','audio':[{'start':12,'end':15,'text':'你好','speaker':'甲'}]}]}
    result,duration=retime_beats(old)
    assert duration==12
    assert result['beats'][1]['action']==old['beats'][1]['action']
    assert result['beats'][1]['audio']==[{'start':6,'end':9,'text':'你好','speaker':'甲'}]
    assert old['beats'][1]['start']==10


def test_audio_scheduler_preserves_story_and_accounts_for_all_lines():
    from src.content_factory.novel_adaptation.patching import schedule_audio
    old={'beats':[{'id':'b1','start':0,'end':3,'action':'孩子跑了出去',
      'audio':[{'speaker':'a','kind':'dialogue','text':'这句台词有十二个字左右。','start':0,'end':1}]},
      {'id':'b2','start':3,'end':6,'action':'独自在屋里','audio':[]}]}
    new,report=schedule_audio(old)
    assert new['beats'][0]['action']==old['beats'][0]['action']
    assert new['beats'][0]['audio'][0]['text']==old['beats'][0]['audio'][0]['text']
    a=new['beats'][0]['audio'][0]
    assert len(a['text'])/(a['end']-a['start'])<=6
    assert old['beats'][0]['audio'][0]['end']==1 and report['changed_beats']==['b1']
