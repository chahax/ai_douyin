import json
from pathlib import Path
import pytest
from src.content_factory import creative_legal_short_seedance_execution_v1 as e
from src.content_factory.creative_stage_contracts import digest,persist
from src.content_factory.seedance_client import SeedanceAPIError

def fixture(tmp):
 frame=tmp/'native.png';frame.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
 asset=tmp/'asset.json';persist(asset,{'path':str(frame.resolve()),'sha256':e.sha(frame)})
 d={'segment_id':'SHORT01','rows':[],'duration_seconds':4};m=tmp/'manifest.json';persist(m,{'segments':[d]})
 a=tmp/'auth.json';persist(a,{'user_statement':'本次整批生成，最后统一审核','automatic_retry':False,'publishing_authorized':False,'manifest_sha256':e.sha(m),'script_sha256':'s'})
 p=tmp/'plan.json';value={'schema':'legal_short_seedance_segment_plan/v1','segment_id':'SHORT01','shot_id':'SH01','logical_task_id':'test_short_no_paid','script_content_sha256':'s','model':'doubao-seedance-2-0-mini-260615','provider':'ark_api','resolution':'480p','duration_seconds':4,'image_role':'reference_image','opening_frame_source':'old_native_image_as_identity_environment_reference','first_frame':{'path':str(frame.resolve()),'sha256':e.sha(frame)},'sources':{k:{'path':str(v.resolve()),'sha256':e.sha(v)} for k,v in [('asset_feedback',asset),('batch_manifest',m),('batch_authorization',a)]},'segment_definition':d,'prompt':'test current scope','prompt_sha256':digest('test current scope')};persist(p,value);return p,value,frame

def test_reference_bootstrap_cannot_be_literal_old_frame(tmp_path):
 p,v,f=fixture(tmp_path);e.validate(p);v['image_role']='first_frame';persist(p,v)
 with pytest.raises(ValueError,match='opening must reference'):e.validate(p)
def test_scope_tamper_stops_before_provider(tmp_path):
 p,v,f=fixture(tmp_path);Path(v['sources']['batch_authorization']['path']).write_text('{}',encoding='utf-8')
 with pytest.raises(ValueError,match='frozen source'):e.validate(p)
def test_role_and_selected_native_bytes_enter_actual_payload(tmp_path):
 from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig
 import httpx,base64
 p,v,f=fixture(tmp_path)
 with SeedanceClient(SeedanceConfig(api_key='offline',provider='ark_api',model=v['model']),http_client=httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('network'))),record_calls=False) as c:r=e.payload(v,f,c)
 assert r['content'][1]['role']=='reference_image';assert base64.b64decode(r['content'][1]['image_url']['url'].split(',')[1])==f.read_bytes()
class Client:
 def __init__(self,exc):self.exc=exc;self.created=0
 def create_task(self,p):self.created+=1;raise self.exc

def test_unknown_never_repeats_submit_or_query_without_id(tmp_path,monkeypatch):
 p,v,f=fixture(tmp_path);c=Client(TimeoutError('network outcome unknown'));monkeypatch.setattr(e,'payload',lambda *args:{'model':v['model'],'content':[]});monkeypatch.setattr(e,'reserve_media_attempt',lambda *args:None)
 with pytest.raises(TimeoutError):e.execute_segment(p,tmp_path/'out','submit',c)
 assert e.read(tmp_path/'out/receipt.json')['technical_status']=='unknown'
 with pytest.raises(ValueError):e.execute_segment(p,tmp_path/'out','submit',c)
 with pytest.raises(ValueError,match='without a task ID'):e.execute_segment(p,tmp_path/'out','query',c)
 assert c.created==1

def test_definite_400_rejected_and_no_retry(tmp_path,monkeypatch):
 p,v,f=fixture(tmp_path);c=Client(SeedanceAPIError('bad request',status_code=400,error_code='InvalidParameter'));monkeypatch.setattr(e,'payload',lambda *args:{'model':v['model'],'content':[]});monkeypatch.setattr(e,'reserve_media_attempt',lambda *args:None)
 with pytest.raises(SeedanceAPIError):e.execute_segment(p,tmp_path/'out','submit',c)
 r=e.read(tmp_path/'out/receipt.json');assert r['technical_status']=='failed';assert r['task_created'] is False;assert c.created==1
