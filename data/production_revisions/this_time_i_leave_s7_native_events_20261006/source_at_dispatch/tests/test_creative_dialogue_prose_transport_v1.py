import pytest,json
from scripts.creative_dialogue_prose_transport_v1 import project,prose_messages
from scripts import run_creative_s7_dialogue_prose_v35 as r

def test_exact_plain_prose_no_fill_or_trim():
 text='  方澄目光保持在原位，第一句平稳，换气后第二句轻而明确。  '
 assert project(text)['dialogue_performance']==text
 for bad in ('{"shots":[]}','中文正文<标签>','第一句2.5秒后说下一句','```正文```'):
  with pytest.raises(ValueError):project(bad)

def test_source_and_shot_and_no_transport_fallback():
 c,d=r.previous.direction_source(1);ls=r.previous.local_sources(1,4);inp=r.physical.build_local_input(c,d,ls);m=prose_messages(inp,{})
 obj=json.loads(m[1]['content']);assert obj['read_only_complete_creative_source']['raw_linear_script']==c['raw_linear_script'];assert obj['read_only_complete_creative_source']['reference_pack']==c['reference_pack']
 assert obj['current_direction_and_complete_steps']['actual_start_state']==inp['start_state']
 assert r.AUTH['automatic_retry'] is False


def test_adapter_calls_once_and_preserves_saved_payload(monkeypatch):
 from scripts.creative_dialogue_prose_transport_v1 import ProseOrToolClients,EvidencedRoleClients,EvidenceCallError
 from src.content_factory.creative_workflow_roles import RoleResult
 class Journal:
  def record(self,*args):pass
 calls=[];text='方澄目光保持在原位，第一句坚定平稳，自然换气后第二句轻而明确。'
 def fake(self,role,messages,**kw):
  calls.append(kw);return RoleResult(text=text,metadata={'output_mode':'content','total_tokens':10},response_payload={'original':text})
 monkeypatch.setattr(EvidencedRoleClients,'call',fake)
 out=ProseOrToolClients().call('writer',[{'content':'dialogue_prose/v1'}],structured_schema=None,evidence=Journal())
 assert len(calls)==1 and json.loads(out.text)=={'dialogue_performance':text} and out.response_payload['original']==text
 def invalid(self,*args,**kw):return RoleResult(text='{"wrong":true}',metadata={'total_tokens':10},response_payload={'original':'wrong'})
 monkeypatch.setattr(EvidencedRoleClients,'call',invalid)
 with pytest.raises(EvidenceCallError) as exc:ProseOrToolClients().call('writer',[{'content':'dialogue_prose/v1'}],structured_schema=None,evidence=Journal())
 assert exc.value.provider_outcome_known and exc.value.response_metadata['total_tokens']==10
