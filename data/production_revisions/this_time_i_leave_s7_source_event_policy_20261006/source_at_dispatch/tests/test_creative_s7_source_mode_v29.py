from copy import deepcopy
import json
import pytest
from scripts import run_creative_s7_source_mode_v29 as r

def case():
    c=deepcopy(r.previous.context());raw={'schema':r.SCALAR_FILM,'emotional_arc':'选择自己','causal_chain':'明确拒绝后接回责任','ending_intent':'她赴约他工作'}
    for b in c['raw_linear_script']['beats']:
        mode='画内对白' if b['id'] in ('B02','B05') else '画外对白' if b['id']=='B03' else '无对白'
        raw[b['id']]='新增信息与目的|原主体观察重点| '+r.frame_catalog.ALLOWED[b['id']][0]+' |本镜信息充分后切下一反应'
    return c,raw

def test_complete_film_author_text_and_selected_lookup_no_action_patch():
    c,raw=case();film=r.decode_scalar_film(raw,c)
    for b in film['beats']:
        s=b['shots'][0];cols=raw[b['beat_id']].split('|');f=r.frame_catalog.FRAMES[cols[2].strip()]
        assert s['new_information']==s['purpose']==cols[0] and s['observation_object']==cols[1] and s['cut_reason']==cols[3]
        assert s['camera']==f['camera'] and s['composition']==f['composition']
    assert len(film['beats'])==10

def test_invisible_speaker_wrong_actor_frame_and_missing_row_rejected():
    c,raw=case()
    for beat,row in [('B06','信息|对象|table_hands|理由'),('B03','信息|对象|table_hands|理由|画内对白'),('B08','信息|对象|follow_fang')]:
        bad=deepcopy(raw);bad[beat]=row
        with pytest.raises(ValueError):r.decode_scalar_film(bad,c)
    bad=deepcopy(raw);del bad['B09']
    with pytest.raises(Exception):r.decode_scalar_film(bad,c)

def test_actual_wire_full_source_and_R01_presets_are_bound(monkeypatch):
    c,raw=case();monkeypatch.setattr(r,'context',lambda:deepcopy(c));monkeypatch.setattr(r,'dispatch',lambda label,request,validator:request)
    req=r.film_plan();payload=json.loads(req['messages'][1]['content']);assert payload['context']['raw_linear_script']==c['raw_linear_script'] and payload['context']['reference_pack']==c['reference_pack']
    assert req['input_provenance']['frame_catalog_sha256']==r.control.digest(r.frame_catalog.FRAMES)
    assert req['model']=='MiniMax-M3' and r.AUTH['automatic_retry'] is False and r.AUTH['media_calls']==0


def test_mode_is_exact_source_and_frame_visibility_not_model_repair():
    c,raw=case();film=r.decode_scalar_film(raw,c);modes={b['beat_id']:b['shots'][0]['dialogue_mode'] for b in film['beats']}
    assert modes['B02']==modes['B05']=='画内对白' and modes['B03']=='画外对白'
    assert all(v=='无对白' for k,v in modes.items() if k not in ('B02','B03','B05'))
    for k,v in raw.items():assert isinstance(v,str)
