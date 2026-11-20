from copy import deepcopy
import pytest
from test_text_validation import fixture
from src.content_factory.corpus_screenplay_v1 import freeze,digest,read
from src.content_factory.novel_adaptation import stage_session
from scripts.run_novel_text_session import prepare,prepare_repaired,step


def setup(tmp_path):
    b=fixture();b['packet']['semantic_status']='selected_dependencies_reviewed'
    seed=tmp_path/'seed';seed.mkdir();context=tmp_path/'context';context.mkdir();design=tmp_path/'design';design.mkdir()
    freeze(seed/'STATE.json',{'status':'done','pending':None,'calls_started':8,'reported_tokens':100})
    freeze(seed/'PLAN.json',{'max_calls':12,'source_sha256':digest(b['source'])})
    freeze(seed/'SOURCE.json',b['source']);freeze(context/'PACKET.json',b['packet'])
    freeze(design/'EPISODE.json',{'design':b['design']})
    acceptance={'status':'text_review_accepted','semantic_acceptance':True,
        'artifact_hashes':{k:digest(b[k]) for k in ('source','packet','design')}}
    previous=tmp_path/'previous';prepare(previous,seed,context,design,0,acceptance)
    def fail(folder,state,plan):
        folder.mkdir();freeze(folder/'STATE.json',{'status':'needs_attention','pending':None,'calls_started':9,'reported_tokens':110})
    stage_session.step(previous,{'author':fail})
    repair=tmp_path/'repair';repair.mkdir()
    freeze(repair/'STATE.json',{'status':'repaired_candidate_awaiting_independent_review','pending':None,'calls_started':10,'reported_tokens':120})
    freeze(repair/'PLAN.json',read(seed/'PLAN.json'));freeze(repair/'SOURCE.json',b['source']);freeze(repair/'CANDIDATE.json',b['candidate'])
    return previous,repair


def test_repaired_author_is_adopted_without_dispatch_and_next_stage_is_presence(tmp_path,monkeypatch):
    previous,repair=setup(tmp_path);old=deepcopy(stage_session.inspect(previous));root=tmp_path/'successor'
    prepare_repaired(root,previous,repair,repair)
    def forbid(*args,**kwargs):pytest.fail('author must not be regenerated')
    monkeypatch.setattr('scripts.run_novel_text_session.subprocess.run',forbid)
    result=step(root)
    assert result['calls_started']==10 and result['reported_tokens']==120
    assert result['completed'][0]['name']=='author' and result['status']=='ready'
    assert read(root/'00_author/CANDIDATE.json')==read(repair/'CANDIDATE.json')
    assert stage_session.inspect(previous)==old
    assert read(root/'SESSION.json')['stages'][len(result['completed'])]['name']=='presence'
    from types import SimpleNamespace
    def presence_only(command,**kwargs):
        assert command[1].endswith('project_narrative_presence.py')
        assert command[command.index('--prior')+1]==str(root/'00_author')
        folder=root/'01_presence';folder.mkdir()
        for name in ('CANDIDATE.json','SOURCE.json','PLAN.json'):
            freeze(folder/name,read(root/'00_author'/name))
        for name in ('PROGRAM_BOUND_PROJECTION.json','PRESENCE_REPLAY.json'):freeze(folder/name,{'test_fixture':True})
        freeze(folder/'STATE.json',{'status':'projection_replayed_awaiting_semantic_coverage_review',
            'pending':None,'calls_started':11,'reported_tokens':130})
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    monkeypatch.setattr('scripts.run_novel_text_session.subprocess.run',presence_only)
    result=step(root)
    assert [x['name'] for x in result['completed']]==['author','presence']
    assert result['calls_started']==11 and result['reported_tokens']==130


def test_latest_unknown_ledger_cannot_be_bypassed_with_older_good_candidate(tmp_path):
    previous,repair=setup(tmp_path);latest=tmp_path/'latest';latest.mkdir()
    freeze(latest/'STATE.json',{'status':'outcome_unknown','pending':11,'calls_started':11,'reported_tokens':120})
    with pytest.raises(ValueError,match='latest_ledger_unsettled'):
        prepare_repaired(tmp_path/'blocked',previous,repair,latest)
    assert not (tmp_path/'blocked').exists()


def test_structural_success_label_does_not_override_actual_audio_duration(tmp_path):
    import json
    previous,repair=setup(tmp_path);candidate=read(repair/'CANDIDATE.json')
    candidate['scenes'][0]['segments'][0]['audio'][0]['text']='很长的对白'*300
    (repair/'CANDIDATE.json').write_text(json.dumps(candidate),encoding='utf-8')
    with pytest.raises(ValueError,match='estimated_duration_exceeds_brief'):
        prepare_repaired(tmp_path/'blocked',previous,repair,repair)


def test_all_adapters_complete_but_review_revision_is_not_content_acceptance(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from scripts.run_novel_text_session import STAGES
    previous,repair=setup(tmp_path)
    plan=read(repair/'PLAN.json');plan['max_calls']=14
    (repair/'PLAN.json').write_text(json.dumps(plan),encoding='utf-8')
    root=tmp_path/'successor';prepare_repaired(root,previous,repair,repair);step(root)
    dispatched=[]
    def fake(command,**kwargs):
        prior=Path(command[command.index('--prior')+1]);folder=Path(command[command.index('--run')+1]);folder.mkdir()
        index=len(dispatched)+1;spec=STAGES[index];state=read(prior/'STATE.json')
        expected=['project_narrative_presence.py','project_narrative_props.py','review_rendered_adaptation.py'][index-1]
        assert command[1].endswith(expected)
        if index==3:assert '--estimate-timing' in command and '--narrative' in command
        for name in spec['artifacts']:
            if name in ('PLAN.json','SOURCE.json','CANDIDATE.json'):value=read(prior/name)
            else:value={'test_fixture':True,'verdict':'revise'}
            freeze(folder/name,value)
        count=2 if index==2 else 1
        freeze(folder/'STATE.json',{'status':spec['success_states'][0],'pending':None,
            'calls_started':state['calls_started']+count,'reported_tokens':state['reported_tokens']+10*count})
        dispatched.append(expected)
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    monkeypatch.setattr('scripts.run_novel_text_session.subprocess.run',fake)
    for _ in range(3):result=step(root)
    assert result['status']=='stages_complete_awaiting_acceptance'
    assert result['calls_started']==14 and result['reported_tokens']==160
    assert read(root/'03_review/FINAL_RENDERED_REVIEW_ENVELOPE_DECODED.json')['verdict']=='revise'
    assert step(root)==result and len(dispatched)==3


def test_mutated_adopted_candidate_blocks_downstream_dispatch(tmp_path,monkeypatch):
    previous,repair=setup(tmp_path);root=tmp_path/'successor'
    prepare_repaired(root,previous,repair,repair);step(root)
    (root/'00_author/CANDIDATE.json').write_text('{}',encoding='utf-8')
    monkeypatch.setattr('scripts.run_novel_text_session.subprocess.run',lambda *a,**k:pytest.fail('must not dispatch'))
    with pytest.raises(ValueError,match='completed_stage_artifact_changed'):step(root)
