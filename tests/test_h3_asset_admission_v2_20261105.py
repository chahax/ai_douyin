from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest

from src.content_factory import h3_asset_admission_v2 as g


def file(root,name,data):
    (root/name).write_bytes(data)
    return dict(path=name,sha256=hashlib.sha256(data).hexdigest())


def approve(root,name,value,**extra):
    payload=dict(approved=True,reviewer='test-review-node',target=g.fingerprint(value),**extra)
    return file(root,name,json.dumps(payload).encode())


def card(root,name,kind):
    slots=g.PERSON_VIEWS if kind=='person' else g.PLACE_VIEWS
    views={s:file(root,name+s+'.png',(name+s).encode()) for s in slots}
    c=dict(id=name,kind=kind,views=views,canonical_sha256=views['canonical']['sha256'],age_source='chapter1',appearance_design='short',
           layout_design='table',origin='individual_turnaround' if kind=='person' else 'empty_scene_plate',status='approved')
    c['review']=approve(root,name+'.json',c)
    return c


@pytest.fixture
def bundle(tmp_path):
    text='低声开口：「好了。」'
    word='好了。'
    u=dict(id='u',start=0,parent='p',text=text,sha256=hashlib.sha256(text.encode()).hexdigest(),audio_items=[
        dict(parent='p',channel='对白',speaker='老六',start=text.index(word),end=text.index(word)+len(word),text=word)])
    s=dict(id='a',visible=['甲'],visual='孩子抬头。',place='家',units=['u'],source_hash=g.fingerprint([u]),voice_placement=['on_screen'])
    s['review']=approve(tmp_path,'shot.json',s)
    p=dict(people={'甲':card(tmp_path,'甲','person')},places={'家':card(tmp_path,'家','place')},aliases={'老六':'甲'},shots=[s])
    return p,s,[u]


def resign(root,s):
    s.pop('review',None)
    s['review']=approve(root,s['id']+'.json',s)


def test_spoken_text_and_actual_cast_only(bundle,tmp_path):
    p,s,u=bundle
    p['people']['旁人']=None
    out=g.compile_shot(tmp_path,p,s,u,'pilot')
    assert [a['subject'] for a in out['visual']['refs']]==['家','甲']
    assert out['audio']==[dict(speaker='老六',role_ids=['甲'],text='好了。',channel='dialogue',delivery='on_screen')]
    assert out['visual']['render_text'] is False and out['subtitles']['lines']==['好了。']


def test_generic_unknown_stays_offscreen(bundle,tmp_path):
    p,s,u=bundle
    u[0]['audio_items'][0].update(speaker='未署名',channel='画外童声')
    s.update(source_hash=g.fingerprint(u),voice_placement=['off_screen'],visible=[])
    resign(tmp_path,s)
    result=g.compile_shot(tmp_path,p,s,u,'pilot')
    assert result['audio'][0]['role_ids']==[] and len(result['visual']['refs'])==1
    s['voice_placement']=['on_screen']
    resign(tmp_path,s)
    with pytest.raises(ValueError):g.compile_shot(tmp_path,p,s,u,'pilot')


@pytest.mark.parametrize('change',['missing','drift','hash','angles','review','foreign_speaker','source_text','unknown_stage'])
def test_asset_and_source_fail_closed(bundle,tmp_path,change):
    p,s,u=bundle
    c=p['people']['甲']
    if change=='missing':c['views']['side_full']=None
    elif change=='drift':c['origin']='unreviewed_previous_frame'
    elif change=='hash':(tmp_path/c['views']['front_full']['path']).write_bytes(b'edited')
    elif change=='angles':c['views']['back_full']=c['views']['side_full']
    elif change=='review':c['appearance_design']='changed'
    elif change=='foreign_speaker':s['visible']=[];resign(tmp_path,s)
    elif change=='source_text':u[0]['audio_items'][0]['text']='低声开口';s['source_hash']=g.fingerprint(u);resign(tmp_path,s)
    with pytest.raises(ValueError):g.compile_shot(tmp_path,p,s,u,'other' if change=='unknown_stage' else 'pilot')


def test_gate_requires_current_reviewed_transition(bundle,tmp_path):
    p,s,u=bundle
    with pytest.raises(ValueError):g.compile_shot(tmp_path,p,s,u,'batch')
    then=deepcopy(s);then.update(id='b',place='街')
    resign(tmp_path,then);p['shots'].append(then);p['places']['街']=card(tmp_path,'街','place')
    clips=[dict(shot=x['id'],place=x['place'],file=file(tmp_path,x['id']+'.mp4',x['id'].encode())) for x in (s,then)]
    p['pilot_review']=approve(tmp_path,'pilot.json',p,clips=clips,checks={k:True for k in g.QUALITY})
    assert g.compile_shot(tmp_path,p,then,u,'batch')['visual']['place']=='街'
    p['aliases']['新别称']='甲'
    with pytest.raises(ValueError):g.compile_shot(tmp_path,p,then,u,'batch')


def test_offline_proposal_covers_exact_source():
    root=Path(__file__).resolve().parents[1]
    pl=json.loads((root/'data/video_generation/h3_asset_proposal_v2_20261105/PROPOSAL.json').read_text(encoding='utf8'))
    cov=json.loads(Path(pl['coverage_path']).read_text(encoding='utf8'))
    assert len(pl['people'])==9 and len(pl['places'])==11 and len(pl['shots'])==122
    assert all(c['canonical_sha256'] is None for c in pl['people'].values())
    assert [u for s in pl['shots'] for u in s['units']]==[u['id'] for s in cov['segments'] for u in s['units']]
    shots={s['id']:s for s in pl['shots']}
    assert shots['F0001']['visible']==['苏墨'] and shots['F0001']['voice_placement']==['off_screen','off_screen']
    assert shots['F0047']['visible']==['叶东','叶南','苏墨'] and shots['F0063']['place']=='kitchen'
    assert len(shots['F0073']['visible'])==7 and len({s['place'] for s in pl['shots'] if s['segment']=='F0095'})==3
