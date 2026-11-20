from copy import deepcopy

import pytest

from src.content_factory import visual_h3_handoff_v3 as h


def graph():
    return {'124':{'class_type':'KSamplerAdvanced','inputs':{'denoise':1,'seed':123}},
            '130':{'class_type':'CreateVideo','inputs':{'fps':24,'audio':['audio',0]}},
            'condition':{'inputs':{'width':736,'height':1312,'length':277,'prompt':'原对白'}}}


def test_native_only_float_input_casts_keep_source_and_native_unchanged():
    source=graph();native=deepcopy(source);native['124']['inputs']['denoise']=1.0;native['130']['inputs']['fps']=24.0
    proof=h.native_graph_equivalence(source,native)
    assert len(proof['normalizations'])==2
    assert type(source['124']['inputs']['denoise']) is int
    assert type(native['124']['inputs']['denoise']) is float
    assert proof['source_graph_sha256']!=proof['native_graph_sha256']


@pytest.mark.parametrize('node,field,value',[('124','denoise',.99),('124','seed',123.0),('130','fps',23.976),
                                            ('condition','width',736.0),('condition','length',278),
                                            ('condition','prompt','换了对白')])
def test_other_type_or_value_changes_still_rejected(node,field,value):
    source=graph();native=deepcopy(source);native[node]['inputs'][field]=value
    assert h.native_graph_equivalence(source,native) is None


def test_receipt_pins_actual_original_id_and_both_hashes(tmp_path):
    source=graph();native=deepcopy(source);native['130']['inputs']['fps']=24.0
    h.write(tmp_path/'workflow_api.json',source);row={'graph_sha256':h.fingerprint(source)}
    assert h._verify_native_graph(tmp_path,row,native,'original-native-id')
    receipt=h.read(next((tmp_path/'native_graph_receipts').glob('*.json')))
    assert receipt['prompt_id']=='original-native-id' and receipt['native_graph_sha256']==h.fingerprint(native)
    assert h.read(tmp_path/'workflow_api.json')==source


def test_collect_running_original_cast_graph_does_not_resubmit(tmp_path,monkeypatch):
    source=graph();native=deepcopy(source);native['124']['inputs']['denoise']=1.0
    folder=tmp_path/'shots/F1';folder.mkdir(parents=True);h.write(folder/'workflow_api.json',source)
    row=dict(id='F1',graph_sha256=h.fingerprint(source));state=dict(status='submitted',prompt_id='pid')
    plan=dict(config={},shots=[row])
    monkeypatch.setattr(h,'_load',lambda *a,**k:(tmp_path,plan))
    monkeypatch.setattr(h,'_shot_state',lambda *a:dict(state))
    monkeypatch.setattr(h,'_http',lambda *a:{})
    monkeypatch.setattr(h,'_queue',lambda *a:dict(queue_running=[[1,'pid',native]],queue_pending=[]))
    monkeypatch.setattr(h,'status',lambda *a:h.read(folder/'STATE.json'))
    result=h.poll_collect(tmp_path)
    assert result['status']=='running' and result['prompt_id']=='pid'
