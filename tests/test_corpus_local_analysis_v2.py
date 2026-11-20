import json
from types import SimpleNamespace
import pytest

from src.content_factory import corpus_local_analysis_v2 as module


class Response:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.value).encode()


def route():return {'provider':'ollama','model':'qwen3.5:9b-q4_K_M','endpoint':'http://127.0.0.1:11435'}


def test_model_digest_pins_and_changed_weights_are_refused(monkeypatch):
    monkeypatch.setattr(module.urllib.request,'urlopen',lambda *a,**k:Response({'models':[{'name':route()['model'],'digest':'original'}]}))
    pinned=module.preflight(route());assert pinned['digest']=='original'
    pinned['digest']='different'
    with pytest.raises(ValueError,match='model_changed'):module.preflight(pinned)


def test_nonlocal_address_refused_before_request(monkeypatch):
    monkeypatch.setattr(module.urllib.request,'urlopen',lambda *a,**k:pytest.fail('must not request'))
    with pytest.raises(ValueError,match='loopback'):module.preflight({**route(),'endpoint':'https://example.org'})


def test_context_capacity_refuses_before_http_and_reports_not_dispatched():
    client=object.__new__(module.LocalAnalysisClient);client.route={**route(),'context':8192}
    with pytest.raises(module.LocalInputRejected) as error:
        client.call('director',[{'role':'user','content':json.dumps({'text':'字'*9000},ensure_ascii=False)}],
                    response_format={'type':'json_object'},max_tokens=512)
    assert error.value.dispatched is False


def test_local_request_preserves_native_completion_and_uses_schema(monkeypatch):
    client=object.__new__(module.LocalAnalysisClient);client.route={**route(),'context':32768,'digest':'pinned'}
    native={'model':route()['model'],'done':True,'done_reason':'length','prompt_eval_count':2,
            'eval_count':3,'message':{'content':'partial'}}
    def send(request,**kwargs):
        body=json.loads(request.data)
        assert body['format']=={'type':'object'} and body['keep_alive']==0 and body['think'] is False
        return Response(native)
    monkeypatch.setattr(module.urllib.request,'urlopen',send)
    result=client.call('director',[{'role':'user','content':json.dumps({'output_schema':{'type':'object'}})}],
            response_format={'type':'json_object'},max_tokens=512)
    assert result.metadata['finish_reason']=='length' and result.metadata['total_tokens']==5
    assert result.response_payload==native
