import pytest
from test_natural_director_pipeline_v10 import prepared,pipe,fx,F
from src.content_factory.editorial_writer_return_v1 import request_revision


@pytest.mark.parametrize('valid',[True,False])
def test_native_pass_preserved_and_evidence_bound(prepared,valid):
    base,run,_,_=prepared
    b,s=pipe.parent._verify(run)
    original=pipe.core._binding(run/'GATE_002.json')
    draft=pipe.parent._text(s)
    diagnosis=base/'diagnosis.json'
    pipe.core._write(diagnosis,{'draft':s['active']['writer_full']['file'],
      'source_binding':b['source']['binding_id'],'decision':'revise','reviewer':'assistant_editorial_review',
      'issues':[{'quote':draft[:30] if valid else 'absent quote never in this draft','reason':'Fixture concrete editorial issue'}]})
    if not valid:
        with pytest.raises(ValueError):request_revision(run,diagnosis)
        assert pipe.core._read(run/'state.json')['stage']=='director_full'
    else:
        result=request_revision(run,diagnosis)
        assert result['stage']=='writer_full' and result['calls_started']==2
        assert pipe.core._binding(run/'GATE_002.json')==original
        assert not result['writer_ready']
        with pytest.raises(ValueError):request_revision(run,diagnosis)
        revised=pipe.execute_writer_only(run,clients=fx.FakeClients(F['success_values']()[:2]))
        assert revised['writer_ready'] and revised['calls_started']==4
        assert pipe.core._binding(run/'GATE_002.json')==original
        request=pipe.core._read(run/'REQUEST_003.json')
        assert 'editorial_review' in request['messages'][-1]['content']
