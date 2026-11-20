import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import pytest

from src.content_factory.visual_repair_flow_v1 import sha,plan,apply


def project():
    artifacts={k:dict(path=k+'.png',sha256=k,eligible=True) for k in
               ['first_frame','video','audio','subtitle','delivery']}
    return dict(schema='visual_repair_v1',revision=0,paused=True,
                assets={'adult':dict(kind='person',version='v1',status='approved'),
                        'room':dict(kind='place',version='v1',status='approved')},
                shots=[dict(id=s,asset_versions={'adult':'v1','room':'v1'},
                            artifacts=deepcopy(artifacts)) for s in ['s1','s2']])


def review(p,kind,**extra):
    return dict(target=sha(p),reviewer='acceptance',issues=[
        dict(kind=kind,shot='s1',evidence='specific observed defect',**extra)])


@pytest.mark.parametrize('kind,asset,invalid,stage,scope',[
    ('asset_identity','adult',['first_frame','video','delivery'],'repair_asset',2),
    ('asset_layout','room',['first_frame','video','delivery'],'repair_asset',2),
    ('composition',None,['first_frame','video','delivery'],'compose_first_frame',1),
    ('staging',None,['first_frame','video','delivery'],'repair_shot_mapping',1),
    ('video_motion',None,['video','delivery'],'generate_video',1),
    ('video_deformation',None,['video','delivery'],'generate_video',1),
    ('subtitle',None,['subtitle','delivery'],'repair_subtitle',1),
    ('baked_text',None,['video','delivery'],'generate_video',1),
])
def test_defect_routes_preserve_unrelated_artifacts(kind,asset,invalid,stage,scope):
    p=project(); before=deepcopy(p)
    route=plan(p,review(p,kind,asset=asset));out=apply(p,route)
    assert p==before and len(route['actions'])==scope
    assert route['dispatch']=='blocked_manual_pause' and out['paused'] is True
    for i,s in enumerate(out['shots']):
        assert [k for k,v in s['artifacts'].items() if not v['eligible']]==(invalid if i<scope else [])
        for k,v in s['artifacts'].items():
            assert v['path']==p['shots'][i]['artifacts'][k]['path']
        if i<scope:assert s['required_work']==[stage]


@pytest.mark.parametrize('sync,video',[(False,False),(True,True),(None,True)])
def test_audio_requires_known_offscreen_to_reuse_picture(sync,video):
    p=project();r=plan(p,review(p,'audio',lip_sync=sync));o=apply(p,r)
    assert o['shots'][0]['artifacts']['video']['eligible'] is not video
    assert o['shots'][0]['artifacts']['first_frame']['eligible']


def test_reject_stale_review_and_replay():
    p=project();r=plan(p,review(p,'subtitle'));out=apply(p,r)
    with pytest.raises(ValueError):apply(out,r)
    with pytest.raises(ValueError):plan(out,review(p,'subtitle'))


def test_changed_plan_even_with_rehashed_digest_rejected():
    p=project();r=plan(p,review(p,'subtitle'));r['actions'][0]['stage']='generate_video'
    r['plan_sha256']=sha({k:v for k,v in r.items() if k!='plan_sha256'})
    with pytest.raises(ValueError):apply(p,r)


def test_multiple_defects_schedule_prerequisites_before_video():
    p=project();v=review(p,'video_motion')
    v['issues'].append(dict(kind='asset_identity',asset='adult',shot='s1',evidence='wrong face'))
    r=plan(p,v)
    assert [a['stage'] for a in r['actions']]==['repair_asset','repair_asset','generate_video']
    o=apply(p,r)
    assert o['shots'][0]['required_work']==['repair_asset','generate_video']
    assert not o['shots'][1]['artifacts']['first_frame']['eligible']


def test_input_reordering_cannot_move_video_before_asset_repair():
    p=project();v=review(p,'video_motion')
    v['issues'].append(dict(kind='asset_identity',asset='adult',shot='s1',evidence='wrong face'))
    r=plan(p,v);r['actions'].reverse()
    r['plan_sha256']=sha({k:v for k,v in r.items() if k!='plan_sha256'})
    o=apply(p,r)
    assert o['shots'][0]['required_work']==['repair_asset','generate_video']


@pytest.mark.parametrize('issue',[
    dict(kind='guess',shot='s1',evidence='a'),
    dict(kind='subtitle',shot='missing',evidence='a'),
    dict(kind='subtitle',shot='s1',evidence=''),
    dict(kind='asset_identity',shot='s1',asset='room',evidence='a'),
])
def test_invalid_review_stops(issue):
    p=project()
    with pytest.raises(ValueError):plan(p,dict(target=sha(p),reviewer='x',issues=[issue]))


@pytest.mark.parametrize('kind,extra,invalid,sibling_invalid',[
    ('video_motion',{},['video','delivery'],False),
    ('asset_identity',{'asset':'adult'},['first_frame','video','delivery'],True),
    ('audio',{'lip_sync':False},['audio','delivery'],False),
    ('audio',{'lip_sync':True},['video','audio','delivery'],False),
    ('subtitle',{},['subtitle','delivery'],False),
])
def test_blackbox_cli_plan_apply_pause_and_stale_rejection(tmp_path,kind,extra,invalid,sibling_invalid):
    """Invoke only public CLI as new OS processes, inspect emitted files."""
    entry=Path(__file__).resolve().parents[1]/'scripts/visual_repair_flow_v1.py'
    p=project();pp=tmp_path/'project.json';rp=tmp_path/'review.json'
    pp.write_text(json.dumps(p));rp.write_text(json.dumps(review(p,kind,**extra)))
    planned=tmp_path/'plan.json';updated=tmp_path/'new.json'
    def run(op,source,inp,out):
        return subprocess.run([sys.executable,str(entry),op,'--project',str(source),
                               '--input',str(inp),'--output',str(out)],capture_output=True,text=True)
    a=run('plan',pp,rp,planned);assert a.returncode==0,a.stderr
    b=run('apply',pp,planned,updated);assert b.returncode==0,b.stderr
    result=json.loads(updated.read_text());assert result['paused'] and result['revision']==1
    assert {k for k,v in result['shots'][0]['artifacts'].items() if not v['eligible']}==set(invalid)
    assert any(not v['eligible'] for v in result['shots'][1]['artifacts'].values()) is sibling_invalid
    blocked=tmp_path/'replay.json'
    assert run('apply',updated,planned,blocked).returncode==2 and not blocked.exists()
    original=updated.read_bytes()
    assert run('apply',pp,planned,updated).returncode==2 and updated.read_bytes()==original
