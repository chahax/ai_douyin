from copy import deepcopy
import json
import pytest
from jsonschema import ValidationError
from scripts import run_creative_s7_outline_and_shots_v32 as r


def fixture():
 c=deepcopy(r.previous.context());outline={'emotional_arc':'明确拒绝到释放','causal_chain':'拒绝后他接回工作，她赴约','ending_intent':'她的时间归她'}
 modules=[{'new_information_and_purpose':'本拍完整新增信息与目的','observation_object':'当前原主体','frame_id':r.frame_catalog.ALLOWED[b['id']][0],'cut_reason':'信息读清后转向下一拍因果反应'} for b in c['raw_linear_script']['beats']]
 return c,outline,modules


def test_all_complete_new_modules_compose_exact_author_text_and_full_source():
 c,o,ms=fixture();d=r.assemble_film_documents(c,o,ms)
 assert d['emotional_arc']==o['emotional_arc'] and d['causal_chain']==[o['causal_chain']]
 assert [x for b in d['beats'] for s in b['shots'] for x in s['source_step_refs']]==[x['ref'] for x in r.physical.source_contract.source_catalog(c)]
 for b,m in zip(d['beats'],ms):
  s=b['shots'][0];assert s['purpose']==s['new_information']==m['new_information_and_purpose'] and s['observation_object']==m['observation_object'] and s['cut_reason']==m['cut_reason']
 assert [b['shots'][0]['dialogue_mode'] for b in d['beats']]==['无对白','画内对白','画外对白','无对白','画内对白','无对白','无对白','无对白','无对白','无对白']


def test_missing_module_or_extra_keys_or_wrong_frame_rejected():
 c,o,ms=fixture()
 with pytest.raises(ValueError):r.assemble_film_documents(c,o,ms[:-1])
 bad=deepcopy(ms);bad[1]['B02补充']='不接受追加局部补丁'
 with pytest.raises(ValidationError):r.assemble_film_documents(c,o,bad)
 bad=deepcopy(ms);bad[5]['frame_id']='table_hands'
 with pytest.raises(ValidationError):r.assemble_film_documents(c,o,bad)


def test_global_and_single_beat_wire_full_source_R01_focused_and_fixed_roles(monkeypatch):
 c,o,ms=fixture();monkeypatch.setattr(r,'context',lambda:deepcopy(c));monkeypatch.setattr(r,'dispatch',lambda label,request,validator:request);monkeypatch.setattr(r,'reviewed_outline',lambda:{'output':o})
 for req in (r.outline(),r.shot_direction(2)):
  p=json.loads(req['messages'][1]['content']);assert p['read_only_creative_source']['raw_linear_script']==c['raw_linear_script'] and p['read_only_creative_source']['reference_pack']==c['reference_pack']
  assert req['model']=='MiniMax-M3' and req['parameters']['temperature']==.4 and req['parameters']['thinking']=='disabled'
 shot=r.shot_direction(2);payload=json.loads(shot['messages'][1]['content']);assert payload['current_complete_source_beat']==c['raw_linear_script']['beats'][1]
 assert len(shot['structured_schema']['properties'])==4 and len(r.outline()['structured_schema']['properties'])==3
 assert r.AUTH['automatic_retry'] is False and r.AUTH['media_calls']==0


def test_changed_outline_or_source_or_framing_invalidates_module_before_assembly():
 c,o,ms=fixture();outline={'output':o};b=c['raw_linear_script']['beats'][1]
 rec={'request':{'input_provenance':{'outline_sha256':r.control.digest(o),'context_sha256':r.control.digest(c),'beat_sha256':r.control.digest(b),'beat_id':b['id'],'raw_script_sha256':r.control.digest(c['raw_linear_script']),'frame_catalog_sha256':r.control.digest(r.frame_catalog.FRAMES),'full_reference_pack_in_messages':True}}}
 r.check_shot_binding(rec,outline,c,2)
 for key in ('outline_sha256','context_sha256','beat_sha256','beat_id','raw_script_sha256','frame_catalog_sha256'):
  bad=deepcopy(rec);bad['request']['input_provenance'][key]='stale'
  with pytest.raises(RuntimeError):r.check_shot_binding(bad,outline,c,2)


def test_no_action_two_dialogue_performance_still_has_valid_schema():
 from jsonschema import Draft202012Validator
 schema=r.split.performance_schema({'actions':[]});Draft202012Validator.check_schema(schema)
 Draft202012Validator(schema).validate({'dialogue_performance':'两句原拒绝自然说完，语气轻而确定，不道歉不补偿','performances':[]})
