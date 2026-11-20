from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.novel_adaptation import continuity_cards_v5 as n

SOURCE={'chapters':[{'chapter':1,'role':'target','paragraphs':[{'id':'CH1-P001','text':'孩子们住在隔壁。'}]}]}
OK={'passed':True,'issues':[]}

def card(key='room',kind='design',value='两间屋子',refs=None):
    return dict(key=key,kind=kind,value=value,source_ids=refs or [],reason='保持布局')

def test_unchanged_room_survives_new_character_fact():
    old=[card()]
    new=n.merge_cards(old,{'updates':[card('person','fact','兄弟',['CH1-P001'])]},SOURCE,OK)
    assert new[0]==old[0] and len(new)==2 and len(old)==1

def test_reinvented_room_requires_evidence():
    with pytest.raises(ValueError,match='change_requires_source'):
        n.merge_cards([card()],{'updates':[card(value='一室一厅')]},SOURCE,OK)

def test_design_cannot_be_promoted_to_source_fact():
    with pytest.raises(ValueError,match='kind_cannot'):
        n.merge_cards([card()],{'updates':[card(kind='fact',refs=['CH1-P001'])]},SOURCE,OK)

def test_source_correction_preserves_old_version():
    old=[card()];snapshot=deepcopy(old)
    result=n.merge_cards(old,{'updates':[card(value='三间',refs=['CH1-P001'])]},SOURCE,OK)
    assert old==snapshot and result[0]['value']=='三间'

def test_unreferenced_age_fact_rejected():
    with pytest.raises(ValueError,match='fact_without_source'):
        n.merge_cards([],{'updates':[card('age','fact','十五六岁')]},SOURCE,OK)

def test_rejected_semantics_not_committed():
    with pytest.raises(ValueError,match='not_approved'):
        n.merge_cards([],{'updates':[]},SOURCE,{'passed':False,'issues':['时序不对']})

def test_conflicting_audit_verdict_rejected():
    with pytest.raises(ValueError,match='audit_contract'):
        n.merge_cards([],{'updates':[]},SOURCE,{'passed':True,'issues':['时序不对']})

def bound(tmp_path):
    p=tmp_path/'script.md';p.write_text('夜，两个孩子进屋，举起菜袋。',encoding='utf-8')
    value=dict(time='夜',place='屋内',people='两个孩子',held_props='菜袋',unfinished_action='举起菜袋',candidate_quotes=['两个孩子进屋，举起菜袋'],source_ids=['CH1-P001'])
    h=n.bind_handoff(value,SOURCE,p.read_text(encoding='utf-8'),p,OK)
    return p,dict(version='continuity_cards_v5',chapter=2,cards=[card()],previous_handoff=h,parent_digest='previous')

def test_new_revision_invalidates_previous_handoff(tmp_path):
    p,b=bound(tmp_path);n.validate_bundle(b)
    p.write_text('傍晚，孩子尚未进屋。',encoding='utf-8')
    with pytest.raises(ValueError,match='stale_handoff'):n.validate_bundle(b)

def test_cannot_extract_nonexistent_final_action(tmp_path):
    p,b=bound(tmp_path);v=b['previous_handoff']['state'];v['candidate_quotes']=['出门去学校']
    with pytest.raises(ValueError,match='quote_not'):
        n.bind_handoff(v,SOURCE,p.read_text(encoding='utf-8'),p,OK)

def test_all_nodes_receive_same_bundle_without_old_reviews(tmp_path):
    p,b=bound(tmp_path)
    class Fake:
        def __init__(self):self.calls=[]
        def call(self,*args,**kwargs):self.calls.append(args);return {}
    f=Fake();t=n.BoundTransport(f,b)
    for node,role in [('generate','writer'),('cycle_0_review','director'),('cycle_0_patch','writer'),('cycle_0_check','writer')]:
        t.call(node,role,'prompt',{'source':SOURCE},{})
    assert all(x[3]['continuity']==b for x in f.calls)
    assert set(f.calls[1][3])=={'source','continuity'}
    p.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='stale_handoff'):t.call('next','writer','p',{}, {})
    assert len(f.calls)==4

def test_duplicate_card_keys_not_silently_overwritten():
    with pytest.raises(ValueError,match='duplicate_card'):
        n.merge_cards([],{'updates':[card(),card()]},SOURCE,OK)

def test_missing_handoff_prevents_second_chapter():
    with pytest.raises(ValueError,match='handoff_required'):
        n.validate_bundle(dict(version='continuity_cards_v5',chapter=2,cards=[],previous_handoff=None,parent_digest=None))

def test_auxiliary_repairs_once_then_quarantines_rejection(tmp_path,monkeypatch):
    from scripts import run_continuity_cards_v5 as runner
    from src.content_factory.corpus_screenplay_v1 import read
    from src.platform_adapter.fanqie_book_corpus import atomic
    seen=[]
    class Fake:
        def __init__(self,run,plan,state):self.run,self.state=run,state
        def save(self):atomic(self.run/'STATE.json',self.state)
        def call(self,node,*args):
            seen.append(node);self.state['calls_started']+=1;self.save()
            return {'passed':False,'issues':['房型与旧卡冲突']} if 'audit' in node else {'updates':[]}
    monkeypatch.setattr(runner.transport,'Transport',Fake)
    with pytest.raises(ValueError,match='not_approved'):
        runner.auxiliary(tmp_path/'stage',{},dict(calls_started=10,reported_tokens=0),{},SOURCE,'cards',{},[])
    assert seen==['cards','cards_audit_0','cards_repair','cards_audit_1']
    s=read(tmp_path/'stage/STATE.json')
    assert s['trial_ended'] and s['calls_started']==14 and s['pending'] is None
    assert not (tmp_path/'stage/RESULT.json').exists()

def test_unknown_auxiliary_is_never_retried(tmp_path,monkeypatch):
    from scripts import run_continuity_cards_v5 as runner
    from src.content_factory.corpus_screenplay_v1 import read
    from src.platform_adapter.fanqie_book_corpus import atomic
    class Fake:
        def __init__(self,run,plan,state):self.run,self.state=run,state
        def save(self):atomic(self.run/'STATE.json',self.state)
        def call(self,node,*args):
            self.state.update(calls_started=11,pending=11,status='outcome_unknown');self.save();raise RuntimeError('unknown')
    monkeypatch.setattr(runner.transport,'Transport',Fake)
    with pytest.raises(RuntimeError,match='unknown'):
        runner.auxiliary(tmp_path/'stage',{},dict(calls_started=10,reported_tokens=0),{},SOURCE,'cards',{},[])
    s=read(tmp_path/'stage/STATE.json')
    assert s['pending']==11 and s['calls_started']==11 and s['trial_ended']

def test_three_chapter_runner_handoff_uses_final_patch_not_original(tmp_path,monkeypatch):
    from scripts import run_continuity_cards_v5 as r
    from src.content_factory.corpus_screenplay_v1 import freeze,read,digest
    from src.platform_adapter.fanqie_book_corpus import atomic
    corpus={'chapters':[{'index':i,'text':'孩子回家。'} for i in range(1,4)]}
    run=tmp_path/'trial';run.mkdir()
    freeze(run/'PLAN.json',dict(corpus_digest=digest(corpus),implementation_pin={},max_calls=70))
    freeze(run/'SOURCE.json',corpus)
    atomic(run/'STATE.json',dict(status='prepared',trial_ended=False,pending=None,calls_started=10,reported_tokens=0,chapters=[]))
    received=[]
    def aux(child,plan,state,corpus,source,stage,payload,previous):
        child.mkdir();atomic(child/'STATE.json',dict(status='done',trial_ended=True,pending=None,calls_started=state['calls_started']+1,reported_tokens=0))
        if stage=='cards':return previous or [card()]
        text=payload['final_candidate'];assert text.startswith('FINAL')
        value=dict(time='夜',place='家',people='孩子',held_props='无',unfinished_action='无',candidate_quotes=[text],source_ids=[source['chapters'][-1]['paragraphs'][0]['id']])
        return n.bind_handoff(value,source,text,payload['candidate_path'],OK)
    def prep(child,prior,**kw):
        received.append(deepcopy(kw));child.mkdir()
        atomic(child/'STATE.json',read(prior/'STATE.json'))
    def script(child):
        ch=len(received);text=f'FINAL chapter {ch} 夜，回家。'
        (child/'ORIGINAL.md').write_text('OLD 傍晚',encoding='utf-8')
        (child/'SCREENPLAY.md').write_text(text,encoding='utf-8')
        freeze(child/'CANDIDATE_BINDING.json',dict(candidate_digest=digest(text)))
        s=read(child/'STATE.json');s.update(status='auto_failed_revision_limit',calls_started=s['calls_started']+1)
        atomic(child/'STATE.json',s)
    monkeypatch.setattr(r,'auxiliary',aux);monkeypatch.setattr(r.script,'prepare',prep);monkeypatch.setattr(r.script,'execute',script)
    r.execute(run)
    assert read(run/'STATE.json')['status']=='trial_complete'
    assert read(run/'STATE.json')['calls_started']==19
    assert [x['shared_max_calls'] for x in received]==[70]*3
    assert received[1]['continuity_bundle']['previous_handoff']['state']['candidate_quotes']==['FINAL chapter 1 夜，回家。']
    assert received[2]['continuity_bundle']['cards']==received[0]['continuity_bundle']['cards']
    assert read(run/'COMMIT_003.json')['full_script_accepted'] is False

def test_real_506_root_rows_recovery_keeps_every_decision_and_budget(tmp_path):
    import json
    from scripts import run_continuity_cards_v5 as r,run_autonomous_revision_v3 as v3
    from src.content_factory.corpus_screenplay_v1 import read
    prior=Path('data/corpus_production_trials/20261102_continuity_cards_first_three')
    child=prior/'chapter_002_script';report=read(child/'cycle_0_review.json')
    raw=json.loads(read(child/'RESPONSE_506.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    fixed,receipt=v3.n.repair_unique_misplaced_scopes(report,raw)
    assert fixed['decisions']['5']==raw['5'] and fixed['decisions']['6']==raw['6']
    assert {k:v for k,v in fixed['decisions'].items() if k not in ('5','6')}==raw['decisions']
    assert fixed['summary']==raw['summary'] and receipt['values_unchanged']
    root=tmp_path/'resume';r.prepare(root,prior,'cycle_0_verify')
    assert read(root/'PLAN.json')['max_calls']==541
    assert read(root/'STATE.json')['calls_started']==506
    assert len(read(root/'STATE.json')['chapters'])==1
    trial=root/'script';v3.prepare(trial,child,resume_verification='cycle_0_verify')
    assert read(trial/'CONTINUITY.json')==read(child/'CONTINUITY.json')
    assert read(trial/'PLAN.json')['max_repair_rounds']==2

def test_root_rows_recovery_rejects_duplicates_or_unknown_keys():
    import json
    from scripts import run_autonomous_revision_v3 as v3
    from src.content_factory.corpus_screenplay_v1 import read
    child=Path('data/corpus_production_trials/20261102_continuity_cards_first_three/chapter_002_script')
    report=read(child/'cycle_0_review.json')
    raw=json.loads(read(child/'RESPONSE_506.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    for variant in (deepcopy(raw),deepcopy(raw)):
        if 'bad' not in locals():variant['decisions']['5']=deepcopy(variant['5']);bad=True
        else:variant['unknown']=variant.pop('5')
        with pytest.raises(ValueError):v3.n.repair_unique_misplaced_scopes(report,variant)

def test_keep_without_scopes_settles_with_zero_remaining_patches(tmp_path):
    import json
    from scripts import run_autonomous_revision_v3 as v3
    from src.content_factory.corpus_screenplay_v1 import read
    child=Path('data/corpus_production_trials/20261102_continuity_cards_first_three_continued/chapter_002_script')
    report=read(child/'cycle_2_COMBINED_REVIEW.json')
    raw=json.loads(read(child/'RESPONSE_514.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    fixed,receipt=v3.n.repair_unique_misplaced_scopes(report,raw)
    assert fixed['decisions']['C2_1_R2_2']['scopes']==[] and receipt['no_edit_authority_added']
    assert fixed['decisions']['I1']==raw['decisions']['I1']
    # A scope classification conflict must not be silently approved as style.
    with pytest.raises(ValueError,match='cannot_be_downgraded'):
        v3.prepare(tmp_path/'settle',child,resume_verification='cycle_2_verify')
    from scripts import run_continuity_cards_v5 as r
    run=tmp_path/'boundary';r.prepare(run,child.parent,finish_known_final=True)
    assert read(run/'PLAN.json')['max_calls']==541
    assert read(run/'STATE.json')['calls_started']==514
    note=read(run/'KNOWN_FINAL_EVALUATION.json')
    assert note['additional_script_calls']==0 and not note['automatic_script_accepted']
    assert note['original_status']=='known_invalid_output'
    bad=deepcopy(raw);bad['decisions']['C2_1_R2_2']['action']='repair_source'
    with pytest.raises(ValueError):v3.n.repair_unique_misplaced_scopes(report,bad)


def test_handoff_addresses_preserve_state_and_refuse_unsupported():
    candidate='夜晚，厨房。\n\n孩子和父亲围桌坐着。'
    proposal=dict(time='夜晚',place='厨房',people='孩子和父亲',held_props='未明确',unfinished_action='未明确',candidate_quotes=['错误来源'],source_ids=['P1'])
    addresses={key:dict(supported=True,line_ids=['L0001','L0003']) for key in ('time','place','people','held_props','unfinished_action')}
    fixed,receipt=n.apply_addresses(proposal,candidate,addresses)
    assert {k:v for k,v in fixed.items() if k!='candidate_quotes'}=={k:v for k,v in proposal.items() if k!='candidate_quotes'}
    assert fixed['candidate_quotes']==['夜晚，厨房。','孩子和父亲围桌坐着。']
    assert proposal['candidate_quotes']==['错误来源'] and receipt['state_fields_unchanged']
    bad=deepcopy(addresses);bad['people']['supported']=False
    with pytest.raises(ValueError,match='not_supported'):n.apply_addresses(proposal,candidate,bad)
    bad=deepcopy(addresses);bad['people']['line_ids']=['L9999']
    with pytest.raises(Exception):n.apply_addresses(proposal,candidate,bad)


def test_real_518_handoff_resume_preserves_ledger_and_finished_scripts(tmp_path):
    from scripts import run_continuity_cards_v5 as r
    from src.content_factory.corpus_screenplay_v1 import read
    prior=Path('data/corpus_production_trials/20261102_continuity_cards_first_three_final')
    run=tmp_path/'addresses';r.prepare(run,prior,resume_handoff=True)
    plan=read(run/'PLAN.json');state=read(run/'STATE.json')
    assert plan['max_calls']==541 and plan['trial_baseline_calls']==481
    assert state['calls_started']==518 and state['pending'] is None
    assert plan['resumed_script']['resume_handoff'] and len(state['chapters'])==1
    imported=read(run/'IMPORTED_HANDOFF.json')
    assert imported['proposal']==read(prior/'chapter_002_handoff/handoff_repair.json')
    assert imported['audit']['passed'] and imported['payload']['final_candidate']==Path(imported['payload']['candidate_path']).read_text(encoding='utf-8')


def test_real_520_cards_metadata_recovery_keeps_all_rows(tmp_path):
    import json
    from scripts import run_continuity_cards_v5 as r
    from src.content_factory.corpus_screenplay_v1 import read
    prior=Path('data/corpus_production_trials/20261102_continuity_cards_first_three_addresses')
    run=tmp_path/'cards';r.prepare(run,prior,resume_cards=True)
    raw=json.loads(read(prior/'chapter_003_cards/RESPONSE_520.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    restored=read(run/'IMPORTED_CARDS.json')
    assert restored['proposal']['updates']==raw['updates'] and restored['metadata_preserved']==raw['reason']
    assert read(run/'PLAN.json')['max_calls']==541 and read(run/'STATE.json')['calls_started']==520
    assert len(read(run/'STATE.json')['chapters'])==2


def test_real_530_incomplete_json_reuses_review_not_failed_decisions(tmp_path):
    from scripts import run_continuity_cards_v5 as r,run_autonomous_revision_v3 as v3
    from src.content_factory.corpus_screenplay_v1 import read
    prior=Path('data/corpus_production_trials/20261102_continuity_cards_first_three_metadata')
    root=tmp_path/'resume';r.prepare(root,prior,resume_review='cycle_1_review')
    assert read(root/'STATE.json')['calls_started']==530 and read(root/'PLAN.json')['max_calls']==541
    child=tmp_path/'script';v3.prepare(child,prior/'chapter_003_script',resume_review='cycle_1_review')
    assert read(child/'PLAN.json')['max_repair_rounds']==1
    assert read(child/'IMPORTED_REVIEW.json')['call']==529
    assert not (child/'IMPORTED_DECISIONS.json').exists()
    assert read(child/'CONTINUITY.json')==read(prior/'chapter_003_script/CONTINUITY.json')


def test_real_535_combined_unique_protocol_recovery_is_not_semantic_approval():
    import json
    from scripts import run_autonomous_revision_v3 as v3
    from src.content_factory.corpus_screenplay_v1 import read
    child=Path('data/corpus_production_trials/20261102_continuity_cards_first_three_review_resume/chapter_003_script')
    report=read(child/'cycle_1_COMBINED_REVIEW.json')
    raw=json.loads(read(child/'RESPONSE_535.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    fixed,receipt=v3.n.repair_unique_misplaced_scopes(report,raw)
    assert receipt['method']=='exact_missing_decision_ids_at_root_and_empty_keep_scopes'
    assert len(receipt['empty_keep_scopes'])==2
    for key,row in fixed['decisions'].items():
        original=raw['decisions'].get(key,raw.get(key))
        assert {k:v for k,v in row.items() if k in original}==original
    decoded=v3.n.decode_verification(report,fixed)
    a=v3.n.adjudicate(read(child/'FINAL_SOURCE.json'),(child/'SCREENPLAY.md').read_text(encoding='utf-8'),report,decoded,allow_minor=True)
    assert any(x['id']=='ch3_breakfast_space' for x in a['accepted'])
