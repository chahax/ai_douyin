"""One scoped offline actual-request check; counts are not speech semantics."""
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import json,socket
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_legal_complete_revision_v11 as m


def test_v11_actual_payload_bounds_rounds_without_splicing_complete_output(monkeypatch,tmp_path):
    def denied(*a,**k):raise AssertionError('offline dialogue count fixture')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(socket,'create_connection',denied)
    config=m.PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_12/SETUP.json'
    settings=m.control.read(config);parent=m.PROJECT/settings['parent_text_directory']
    raw=m.control.read(parent/'call_425_complete_draft.json')['output'];before=deepcopy(raw)
    original=m.control.read;original_sha=m.control.sha_file;stored={}
    gate_path=parent/'INDEPENDENT_EDITORIAL_GATE.json'
    fake_gate={'script_sha256':m.control.digest(original(parent/'FULL_MODEL_SCRIPT.json')),'text_candidate_qualified':False,'unresolved_mandatory_findings':[{'code':'OFFLINE_REPEATED_ROUND_FIXTURE_ONLY','evidence_refs':['B2.S04'],'evidence_text':raw['beats'][1]['steps'][3]['text'],'problem':'临时离线样例：第二同级催签回合未新增压力。','required_revision':'仅用于测试请求，B2三句B3两句；不作为生产编辑门。'}]}
    def read(path):
        if str(path) in stored:return deepcopy(stored[str(path)])
        if Path(path)==gate_path and not gate_path.exists():return deepcopy(fake_gate)
        return original(path)
    monkeypatch.setattr(m.control,'read',read)
    monkeypatch.setattr(m.control,'sha_file',lambda path:m.control.digest(fake_gate) if Path(path)==gate_path and not gate_path.exists() else original_sha(path))
    monkeypatch.setattr(m.control,'write',lambda path,value,*a:stored.update({str(path):deepcopy(value)}))
    root=tmp_path/'v11';root.mkdir();(root/'SETUP.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
    op=m.Revision(root);monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(prepare=lambda:None));monkeypatch.setattr(op,'summary',lambda:{})
    op.prepare();x=stored[str(root/'INPUT.json')];anchor=stored[str(root/'ANCHOR.json')]
    ledger=original(parent/'CALL_LEDGER.json');receipts=[original(parent/q['receipt']) for q in ledger['calls']]
    assert anchor['inherited']['calls_started']==ledger['starting_spend']['calls_started']+len(receipts)==426
    assert anchor['inherited']['reported_tokens']==ledger['starting_spend']['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts)
    assert anchor['inherited']['unknown_token_reservations']==93117 and anchor['budget_reset'] is False
    assert anchor['automatic_retry'] is False and anchor['media_authorized'] is False
    calls=[]
    def dispatch(label,req,validator):calls.append((label,deepcopy(req),validator));return {'ordinal':999,'status':'contract_rejected'}
    monkeypatch.setattr(op,'prepare',lambda:None);monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(dispatch=dispatch))
    op.dispatch('draft');assert len(calls)==1
    label,req,validator=calls[0];payload=json.loads(req['messages'][1]['content'])
    assert label=='complete_draft' and req['model']=='MiniMax-M3' and payload['reference_fulltext']==x['reference_fulltext']
    assert 'draft_to_replace_not_facts' not in payload and 'previous_full_review' not in payload
    fixed=payload['unchanged_beats_from_single_full_model_source']['beats']
    assert payload['unchanged_beats_from_single_full_model_source']['source_ordinal']==420
    assert [b for b in raw['beats'] if b['id'] in ['B1','B4']]==fixed
    schema=req['structured_schema'];Draft202012Validator.check_schema(schema)
    rules=schema['properties']['beats']['items']['allOf']
    assert len(rules)==4 and [r['then']['const'] for r in rules[:2]]==fixed
    for rule,count,beat in zip(rules[2:],[3,2],['B2','B3']):
        assert rule['if']['properties']['id']['const']==beat
        bound=rule['then']['properties']['steps']
        assert bound['minContains']==bound['maxContains']==count
        assert bound['contains']['properties']['kind']['const']=='dialogue'
    with pytest.raises(ValidationError):validator(raw)
    shorter=deepcopy(raw)
    for beat in shorter['beats']:
        if beat['id'] in settings['dialogue_counts']:
            count=0;kept=[]
            for row in beat['steps']:
                if row['kind']=='dialogue':
                    count+=1
                    if count>settings['dialogue_counts'][beat['id']]:continue
                kept.append(row)
            beat['steps']=kept
    fixture_before=deepcopy(shorter)
    result=validator(shorter)
    assert result['full_model_script'] is True and result['creative_text_changed_locally'] is False
    assert result['creative_quality_passed'] is False and shorter==fixture_before
    bad=deepcopy(shorter);next(q for q in bad['beats'][0]['steps'] if q['kind']=='dialogue')['text']='公司并没有让你离开。'
    with pytest.raises(ValidationError):validator(bad)
    merged=deepcopy(shorter);b3=merged['beats'][2]
    dialogue=[q for q in b3['steps'] if q['kind']=='dialogue']
    dialogue[0]['text']+=' 小林：'+dialogue[1]['text']
    b3['steps']=[q for q in b3['steps'] if q is not dialogue[1]]
    with pytest.raises(ValidationError):validator(merged)
    base_schema=deepcopy(schema);before_schema=deepcopy(base_schema)
    m.bound_dialogue_rounds(base_schema,{'B2':3,'B3':2});assert base_schema==before_schema
    assert raw==before and not (root/'FULL_MODEL_SCRIPT.json').exists()
