from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.narrative_revision import validate, diagnose

SOURCE={'chapters':[{'index':2,'text':'甲把书交给乙。'},{'index':3,'text':'第二天乙离开。'}]}
PACKET={'entities':[{'id':x,'kind':'character'} for x in ('a','b')]}
DESIGN={'target_chapters':[2],'places':[{'id':'room'}],'scenes':[{'id':'S1','place':'room'}]}
VALUE={'title':'交书','world_and_relationships':'两人同屋','visual_direction':'日光',
 'scenes':[{'id':'S1','place':'room','entry_continuity':'两人同屋',
 'segments':[{'id':'B1','seconds':8,'visible_people':['a','b'],'action':'甲递书，乙接住。',
 'expression':'专注','camera':'中景','audio':[{'kind':'dialogue','speaker':'a','text':'给你。'}],
 'source_ids':['CH2-P001'],'visual_additions':['日光'],'continuity_obligations':['书从甲到乙']}],
 'exit_continuity':'乙持书'}],'condensation_notes':[]}

def check(v):return validate(v,SOURCE,PACKET,DESIGN,30)

def test_narrative_without_inventory_schema_is_only_structural_pass():
    assert check(VALUE)['status']=='structure_only_not_content_acceptance'

@pytest.mark.parametrize('text',['……','   ','！？'])
def test_nonverbal_pause_is_not_a_speech_track(text):
    v=deepcopy(VALUE);v['scenes'][0]['segments'][0]['audio'][0]['text']=text
    with pytest.raises(ValueError,match='nonverbal_pause_encoded_as_speech'):check(v)

def test_short_spoken_interjection_remains_valid():
    v=deepcopy(VALUE);v['scenes'][0]['segments'][0]['audio'][0]['text']='嗯。'
    assert check(v)['seconds']==8


def test_simultaneous_failures_are_addressed_without_rewriting_candidate():
    v=deepcopy(VALUE);b=v['scenes'][0]['segments'][0]
    b['seconds']=45;b['audio'][0]['text']='……';b['visible_people']=['b']
    original=deepcopy(v)
    report=diagnose(v,SOURCE,PACKET,DESIGN,30)
    assert {i['code'] for i in report['issues']}=={
        'nonverbal_pause_encoded_as_speech','dialogue_speaker_not_present','editorial_duration_limit_exceeded'}
    assert report['issues'][0]['path']=='/scenes/0/segments/0/audio/0/text'
    assert report['issues'][-1]['actual_seconds']==45
    assert report['semantic_acceptance'] is False
    assert v==original


def test_short_labels_cannot_hide_excessive_spoken_content():
    v=deepcopy(VALUE);b=v['scenes'][0]['segments'][0]
    b['seconds']=1;b['audio'][0]['text']='这是一段需要完整说完不能靠压低时长数字通过的对白。'*6
    report=diagnose(v,SOURCE,PACKET,DESIGN,30)
    assert report['seconds']==1
    assert 'estimated_duration_exceeds_brief' in {x['code'] for x in report['issues']}
    with pytest.raises(ValueError,match='estimated_duration_exceeds_brief'):check(v)

@pytest.mark.parametrize('mutation', ['absent','narrator','future','duration','missing','duplicate'])
def test_real_failure_classes_are_rejected(mutation):
    v=deepcopy(VALUE);b=v['scenes'][0]['segments'][0]
    if mutation=='absent':b['visible_people']=['b']
    elif mutation=='narrator':b['audio'][0]['speaker']='NARRATOR'
    elif mutation=='future':b['source_ids']=['CH3-P001']
    elif mutation=='duration':b['seconds']=31
    elif mutation=='missing':v['scenes']=[]
    elif mutation=='duplicate':v['scenes'][0]['segments'].append(deepcopy(b))
    with pytest.raises(ValueError):
        check(v)
