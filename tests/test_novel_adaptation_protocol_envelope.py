import json
import pytest
from src.content_factory.novel_adaptation.protocol_envelope import decode,StringEnvelopeClient,WIRE_SCHEMA
from src.content_factory.serial_story_transport_v6 import NativeClient


def test_complete_json_string_roundtrips_without_changing_text():
    value={'records':{'b':{'audio_texts':{'0':'她说：“好像。”'},'blocking':[{'kind':'gesture'}]}}}
    assert decode({'result_json':json.dumps(value,ensure_ascii=False)})==value


@pytest.mark.parametrize('value',[{'result_json':'{"a":'},{'result_json':'{"a":1,"a":2}'},{'result_json':{},'extra':1},{'records':{}}])
def test_bad_or_ambiguous_envelopes_are_not_repaired(value):
    with pytest.raises(ValueError):decode(value)


def test_wire_schema_is_simple_while_original_semantic_instructions_are_preserved(monkeypatch,tmp_path):
    captured=[]
    def fake(self,role,messages,schema):captured.append((messages,schema));return {'native':'untouched'}
    monkeypatch.setattr(NativeClient,'call',fake)
    client=StringEnvelopeClient(tmp_path,{})
    messages=[{'role':'user','content':'full semantic schema and source'}]
    assert client.call('writer',messages,{'complex':'schema'})=={'native':'untouched'}
    assert captured==[(messages,WIRE_SCHEMA)]


def test_capacity_counts_actual_contents_and_wire_schema_without_double_escaping(tmp_path):
    from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger
    messages=[{'role':'user','content':json.dumps({'中文':'"nested"'},ensure_ascii=False)}]
    ledger=StringEnvelopeLedger(tmp_path,{}, {},None)
    expected=len(messages[0]['content'].encode())+len('user')+len(json.dumps(WIRE_SCHEMA,ensure_ascii=False).encode())
    assert ledger.request_size(messages,{'semantic':'already in payload'})==expected
