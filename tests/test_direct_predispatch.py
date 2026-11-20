import pytest
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger
from src.content_factory.serial_story_transport_v6 import Ledger

def test_predispatch_capacity_error_does_not_reaudit_previous_receipt(tmp_path,monkeypatch):
    folder=tmp_path/'native_159';folder.mkdir()
    (folder/'CHUNKS.jsonl').write_text('invalid old file must not be read')
    (folder/'RESPONSE.json').write_text('{}')
    evidence=tmp_path/'STREAM_EVIDENCE_159.json';evidence.write_text('original evidence')
    def reject(*args,**kwargs):raise ValueError('complete_request_exceeds_capacity')
    monkeypatch.setattr(Ledger,'call',reject)
    ledger=DirectLedger(tmp_path,{}, {'calls_started':159,'pending':None},None)
    with pytest.raises(ValueError,match='complete_request_exceeds_capacity'):
        ledger.call('NEXT','writer','prompt',{}, {})
    assert evidence.read_text()=='original evidence'
    assert ledger.state['calls_started']==159 and ledger.state['pending'] is None
