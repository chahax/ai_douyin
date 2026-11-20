"""Only known native revise + confirmed content can start a fresh full draft."""
from copy import deepcopy
from pathlib import Path
import json
import runpy
import pytest
from src.content_factory import known_complete_review_revision_v1 as helper
H=runpy.run_path(str(Path(__file__).with_name('test_natural_director_pipeline_v10.py')))
pipe=H['pipe']; fx=H['fx']; F=H['F']

def raw_review(*,unlinked=False):
    raw=fx.review('revise'); raw['adjudication']['new_issues']=[deepcopy(raw['full_review']['issues'][0])]
    if unlinked:
        for row in raw['full_review']['checks']: row['issue_ids']=[]
    return raw

def snapshot(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

@pytest.fixture
def setup(tmp_path,monkeypatch):
    registry=tmp_path/'canonical'; monkeypatch.setattr(pipe,'CANONICAL_REGISTRY',registry)
    monkeypatch.setattr(pipe.parent,'CANONICAL_REGISTRY',registry)
    monkeypatch.setattr(pipe.core,'_legacy_blocks',lambda *a,**kw:[])
    def create(raw=None,finish='stop',unknown=False):
        source=tmp_path/'source.txt'; source.write_text('An original story requiring an actual causal answer.',encoding='utf-8')
        run=tmp_path/'writer'; authorization=H['auth'](tmp_path,run)
        pipe.prepare_source(run,authorization_path=authorization,source_path=source,source_kind='original',title='Known full review content case')
        client=fx.FakeClients([F['success_values']()[0],fx.result(raw_review() if raw is None else raw,'director',finish=finish,unknown=unknown)])
        with pytest.raises((ValueError,RuntimeError)): pipe.execute_writer_only(run,clients=client)
        assert len(client.calls)==2
        return run
    return create

@pytest.mark.parametrize('unlinked',[False,True])
def test_readonly_plan_keeps_native_revise_and_all_packaging_errors(setup,unlinked):
    run=setup(raw_review(unlinked=unlinked)); before=snapshot(run); plan=helper.plan_revision(run)
    assert plan['status']=='known_complete_content_revision_proven'
    assert (plan['calls_started'],plan['reported_tokens'],plan['revisions_used'])==(2,200,0)
    assert plan['old_review_accepted'] is False and plan['model_calls_started']==0
    assert plan['target_state']['stage']=='writer_full' and plan['target_state']['status']=='needs_full_revision'
    assert set(plan['target_state']['active'])=={'writer_full'}
    assert len(plan['program_contract_errors'])==(3 if unlinked else 1)
    assert snapshot(run)==before

def test_frozen_writer_rewrites_full_text_then_reviews_only_new_receipt(setup,monkeypatch):
    run=setup(raw_review(unlinked=True)); old_raw=pipe.core._read(run/'RESPONSE_002.json')['response_text']; before=snapshot(run)
    plan=helper.plan_revision(run); result=helper.apply_revision(run,reviewed_plan=plan)
    assert result['status']=='revision_prepared' and result['calls_started']==2 and result['revisions_used']==0
    for name,data in before.items():
        if name!='state.json': assert (run/name).read_bytes()==data
    original=pipe.parent.roles.parse_review_bundle
    def parse(text,*args,**kw):
        assert text!=old_raw,'Old rejected native review must never be rebuilt as accepted.'
        return original(text,*args,**kw)
    monkeypatch.setattr(pipe.parent.roles,'parse_review_bundle',parse)
    client=fx.FakeClients([fx.result('Revised complete screenplay, keeping the full story and correcting the confirmed issue.'),fx.result(fx.review(),'director')])
    view=pipe.execute_writer_only(run,clients=client)
    assert view['writer_ready'] and (view['calls_started'],view['known_reported_tokens'])==(4,400)
    assert view['state']['revisions_used']==view['state']['quality_revisions_used']==1
    assert [v['role'] for v in client.calls]==['writer','director']
    materials=json.loads(client.calls[0]['messages'][-1]['content'])
    assert materials['previous_draft']==before['DRAFT_001.md'].decode()
    assert materials['review']['native_review_text']==old_raw
    assert not (run/'REVIEW_BUNDLE_002.json').exists() and (run/'REVIEW_BUNDLE_004.json').exists()
    assert pipe.core._read(run/'BINDING.json')['budget']['max_calls']==20

def test_apply_is_idempotent_but_cannot_rewind_after_new_writer(setup):
    run=setup(); plan=helper.plan_revision(run)
    first=helper.apply_revision(run,reviewed_plan=plan); before=snapshot(run)
    assert helper.apply_revision(run,reviewed_plan=plan)==first and snapshot(run)==before
    pipe.execute_writer_only(run,clients=fx.FakeClients([fx.result('Complete new native screenplay.')]),max_steps=1)
    with pytest.raises(ValueError,match='推进'): helper.apply_revision(run,reviewed_plan=plan)

@pytest.mark.parametrize('change',[
    lambda raw: raw['full_review'].update(native_verdict='pass'),
    lambda raw: raw['full_review']['issues'][0].update(finding_status='candidate'),
    lambda raw: raw['adjudication']['new_issues'][0].update(evidence=['Different issue body']),
    lambda raw: raw['full_review']['checks'].pop(),
    lambda raw: raw['scene_ledger']['events'][0].update(timeline_id=''),
])
def test_pass_format_only_or_nonmatching_other_errors_never_force_writer(setup,change):
    raw=raw_review(); change(raw); run=setup(raw); before=snapshot(run)
    with pytest.raises((ValueError,RuntimeError)): helper.plan_revision(run)
    assert snapshot(run)==before and not (run/helper.RECORD).exists()

@pytest.mark.parametrize('finish,unknown',[('length',False),('stop',True)])
def test_unknown_or_truncated_review_cannot_be_reclassified(setup,finish,unknown):
    run=setup(finish=finish,unknown=unknown); before=snapshot(run)
    with pytest.raises(ValueError): helper.plan_revision(run)
    assert snapshot(run)==before

def test_changed_reviewed_plan_cannot_create_revision_claim(setup):
    run=setup(); plan=helper.plan_revision(run); plan['calls_started']=0; before=snapshot(run)
    with pytest.raises(ValueError,match='变化'): helper.apply_revision(run,reviewed_plan=plan)
    assert snapshot(run)==before

def test_tampered_native_review_stops_before_application(setup):
    run=setup(); path=run/'RESPONSE_002.json'; path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError): helper.plan_revision(run)
