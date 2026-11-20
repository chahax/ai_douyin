from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import fact_locked_scene as f, contracts as c, prose_patch

def review(value,source,**extra):
    return dict(reviewer='primary_assistant',artifact_sha256=c.digest(value),source_sha256=c.digest(source),verdict='approved',open_issues=[],**extra)

@pytest.fixture
def sample():
    source={'chapters':[{'index':1,'text':'哥哥挣了十块。\n孩子六七岁的样子。'}]}
    keys=list(c.catalog(source))
    registry={'source_sha256':c.digest(source),'characters':[
        {'id':'a','name':'叶南','age':None,'source_ids':[keys[0]]},
        {'id':'b','name':'叶西决','age':{'text':'六七岁的样子','source_id':keys[1]},'source_ids':[keys[1]]}]}
    scene={'id':'s','registry_sha256':c.digest(registry),'time_label':'当日','place_label':'屋内','places':['room'],
        'previous_locations':{'a':'room','b':'room'},'presence':{'place_id':'room','initial_locations':{},'transitions':[],'end_cast':['a','b']},
        'lines':[{'id':'D','kind':'dialogue','speaker':'a','listener':'b','evidence':f.source_span(source,keys[0]),'styles':['轻声说']}]}
    return source,registry,scene

def render(sample):
    s,r,t=sample
    return f.render(t,r,s,review(r,s),review(t,s),{'D':'轻声说'})

def test_locked_names_age_and_original_words(sample):
    s,r,t=sample; result=render(sample)
    assert f.cast_header(r,['a','b'],True)=='在场：叶南、叶西决（六七岁的样子）'
    assert result['lines'][0]['text']=='叶南（轻声说）：哥哥挣了十块。'
    assert result['end_locations']==t['previous_locations']

@pytest.mark.parametrize('output',[{'D':'妈，你记得吗'},{'D':'轻声说','age':14},{'D':'自然表达'},{'D':'轻声说','speaker':'b'}])
def test_writer_cannot_change_facts_or_restricted_style(sample,output):
    s,r,t=sample
    with pytest.raises(c.ContractError):f.render(t,r,s,review(r,s),review(t,s),output)

def test_stale_registry_review(sample):
    s,r,t=sample; rr=review(r,s);r['characters'][0]['name']='老大'
    with pytest.raises(ValueError):f.validate_registry(r,s,rr)

def test_source_words_cannot_be_replaced_even_with_new_attestation(sample):
    s,r,t=sample;t['lines'][0]['evidence']['text']='已经交钱。'
    with pytest.raises(ValueError,match='source_text_changed'):f.validate_contract(t,r,s,review(t,s))

def test_age_requires_literal_evidence(sample):
    s,r,t=sample;r['characters'][1]['age']['text']='十四岁'
    with pytest.raises(ValueError,match='age_not_literal'):f.validate_registry(r,s,review(r,s))

def test_silent_disappearance_rejected(sample):
    s,r,t=sample;t['presence']['end_cast']=['a']
    with pytest.raises(c.ContractError):f.validate_contract(t,r,s,review(t,s))

def test_changed_speaker_invalidates_review(sample):
    s,r,t=sample;tr=review(t,s);t['lines'][0]['speaker']='b'
    with pytest.raises(ValueError):f.validate_contract(t,r,s,tr)

def test_handoff_needs_current_scene_review_and_complete_episode(sample):
    s,r,t=sample;out=render(sample)
    with pytest.raises(ValueError):f.release_handoff(out,t,r,s,{})
    rv=review(out,s,scope='scene',scene_id='s');h=f.release_handoff(out,t,r,s,rv)
    assert f.episode_ready(['s'],[h],{'s':out})
    assert not f.episode_ready(['s','next'],[h],{'s':out})
    altered=deepcopy(out);altered['screenplay']+='新情节'
    assert not f.episode_ready(['s'],[h],{'s':altered})
    with pytest.raises(ValueError):f.release_handoff(altered,t,r,s,rv)

def test_scoped_patch_preserves_unselected_text():
    original={'screenplay':'前文\n错误段\n后文','other':1}
    plan=prose_patch.prepare(original['screenplay'],[{'quote':'错误段','reason':'test'}])
    fixed=f.repair_spans(original,plan,{'edit_0':'原文段'})
    assert fixed=={'screenplay':'前文\n原文段\n后文','other':1}
    assert original['screenplay']=='前文\n错误段\n后文'

def test_age_field_repair_keeps_posture_and_other_descriptions():
    old={'screenplay':'叶东（十一岁，瘦高）、叶西决（跪坐在地）'}
    new,patch=f.repair_literal_fields(old,[{'before':'叶东（十一岁，瘦高）','after':'叶东（瘦高）','reason':'年龄无据'}])
    assert new['screenplay']=='叶东（瘦高）、叶西决（跪坐在地）'
