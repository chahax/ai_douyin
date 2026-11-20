from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import autonomous_revision_v3 as n,agent_capacity_v2 as cap,prose_patch
from scripts import run_autonomous_revision_v3 as runner

SOURCE={'chapters':[{'chapter':1,'role':'target','paragraphs':[{'id':'CH1-P001','text':'孩子自己盛饭。'}]}]}
TEXT='背景：父亲盛饭。正文：父亲盛饭。结尾。'


def issue():
    return dict(id='I1',subject='盛饭',kind='continuity',severity='production',claim='盛饭主体错误',source_ids=['CH1-P001'],
        reason='原文是孩子',scopes=[dict(quote='背景：父亲盛饭。',boundary='恢复原主体'),dict(quote='正文：父亲盛饭。',boundary='恢复原主体')])


def verification(x=None,action='repair_source',decision='supported'):
    x=x or issue()
    return dict(decisions=[dict(id=x['id'],decision=decision,severity=x['severity'],action=action,
        reason='核对原文',source_ids=x['source_ids'],scopes=x['scopes'])],summary='完成')


def test_confirmed_production_is_repaired_not_handed_to_human():
    report=dict(issues=[issue()],summary='需要修')
    a=n.adjudicate(SOURCE,TEXT,report,verification())
    assert len(a['accepted'])==1 and a['accepted'][0]['verified_severity']=='production'
    plan=n.patch_plan(TEXT,a)
    fixed=prose_patch.apply(TEXT,plan,dict(edit_0='背景：孩子盛饭。',edit_1='正文：孩子盛饭。'))
    assert fixed.endswith('结尾。')
    with pytest.raises(ValueError,match='cannot_be_downgraded'):
        n.adjudicate(SOURCE,TEXT,report,verification(action='keep'))


def test_style_downgrade_cannot_hide_confirmed_relationship_error():
    x=issue();x.update(kind='facts',severity='style')
    with pytest.raises(ValueError,match='cannot_be_downgraded'):
        n.adjudicate(SOURCE,TEXT,dict(issues=[x],summary='关系'),verification(x,action='keep'))
    x['kind']='expression'
    assert not n.adjudicate(SOURCE,TEXT,dict(issues=[x],summary='可选措辞'),verification(x,action='keep'))['accepted']


def test_unknown_can_be_neutral_but_not_kept_or_claimed_source_fact():
    r=dict(issues=[issue()],summary='缺证据')
    assert n.adjudicate(SOURCE,TEXT,r,verification(action='repair_neutral',decision='unresolved'))['accepted']
    for action in ['keep','repair_source']:
        with pytest.raises(ValueError,match='unresolved_cannot_pass'):
            n.adjudicate(SOURCE,TEXT,r,verification(action=action,decision='unresolved'))
    assert n.adjudicate(SOURCE,TEXT,r,verification(action='blocked',decision='unresolved'))['blocked']


def test_rejected_opinion_is_not_edited_and_bad_addresses_do_not_fuzzy_patch():
    r=dict(issues=[issue()],summary='核对')
    assert not n.adjudicate(SOURCE,TEXT,r,verification(action='keep',decision='rejected'))['accepted']
    with pytest.raises(ValueError,match='rejected_issue_cannot_repair'):
        n.adjudicate(SOURCE,TEXT,r,verification(decision='rejected'))
    v=verification();v['decisions'][0]['scopes'][0]['quote']='不存在的句子'
    with pytest.raises(ValueError,match='range_not_unique'):n.adjudicate(SOURCE,TEXT,r,v)


def test_overlapping_evidence_merges_without_touching_other_text():
    r=dict(issues=[issue()],summary='修复');a=n.adjudicate(SOURCE,TEXT,r,verification())
    other=deepcopy(a['accepted'][0]);other['id']='I2';other['scopes']=[dict(quote='父亲盛饭。正文：父亲',boundary='同一主体')]
    a['accepted'].append(other)
    plan=n.patch_plan(TEXT,a)
    assert len(plan['slots'])==1 and set(plan['slots'][0]['issue_ids'])=={'I1','I2'}
    assert prose_patch.apply(TEXT,plan,dict(edit_0='背景和正文均孩子盛饭。'))=='背景和正文均孩子盛饭。结尾。'


def test_retrieval_is_exact_bounded_and_excludes_future_and_unrelated_chapters():
    corpus=dict(chapters=[dict(index=1,text='衣服买三套。\n\n多余衣服快递到家。\n\n打包完成。'),
        dict(index=2,text='收到衣服。'),dict(index=3,text='后来两人结婚了。')])
    packet=dict(chapters=[dict(chapter=2,role='target',paragraphs=[dict(id='CH2-P001',text='收到衣服。')])])
    x=issue();x.update(subject='衣服快递',claim='快递衣服批次是否明确')
    result,log=n.retrieve(corpus,packet,[x])
    evidence=[ch for ch in result['chapters'] if ch['role']=='evidence_only']
    assert evidence and all(ch['chapter']<3 for ch in result['chapters'])
    assert any(p['text']=='多余衣服快递到家。' for ch in evidence for p in ch['paragraphs'])
    again,_=n.retrieve(corpus,result,[x]);assert again==result
    assert packet['chapters'][0]['paragraphs']==[dict(id='CH2-P001',text='收到衣服。')]
    assert log['no_hit_is_not_absence']


def test_final_gate_rejects_pending_work_even_if_reviewer_says_empty():
    assert not n.completion_gate('三、待核事项\n1. 夫妻关系需确认。',[],True)['passed']
    assert not n.completion_gate('已完成。',[dict(status='open')],True)['passed']
    assert not n.completion_gate('已完成。',[],False)['passed']
    assert n.completion_gate('三、待核事项：无。',[],True)['passed']
    assert n.completion_gate('使用中性画外音，不指定人物口型。',[],True)['passed']
    assert n.completion_gate('三、待核事项\n\n无。',[],True)['passed']
    assert n.completion_gate('人物甲：我需要确认货款。',[],True)['passed']


def prior_fixture(tmp_path,text=TEXT):
    prior=tmp_path/'prior';prior.mkdir();profiles=cap.profiles()
    plan=dict(routes={k:{z:v[z] for z in ['provider','model','base_url']} for k,v in profiles.items()},
        capabilities=profiles,budgets=dict(writer=[131072,262144],director=[65536,131072]),
        inference=dict(writer_effort='xhigh',director_effort='high',director_thinking='enabled'),
        endpoint_overrides={'writer':'https://api.minimax.cn/v1'},max_calls=27)
    for name,value in [('PLAN',plan),('SOURCE',dict(chapters=[dict(index=1,text='孩子自己盛饭。')])),('INPUT',SOURCE),
        ('PRODUCTION_CHOICES',[]),('ISSUE_REGISTRY',[]),('STATE',dict(pending=None,trial_ended=True,calls_started=3,reported_tokens=300)),
        ('CANDIDATE_BINDING',dict(candidate_digest=digest(text)))]:freeze(prior/(name+'.json'),value)
    (prior/'SCREENPLAY.md').write_text(text,encoding='utf-8');return prior


@pytest.mark.parametrize('scenario',['success','new_production','retry','unresolvable','missing_contract','minor_spec'])
def test_actual_orchestration_without_manual_gate(tmp_path,monkeypatch,scenario):
    text=TEXT if scenario!='missing_contract' else '三、待核事项\n关系需要确认。'
    if scenario=='minor_spec':text='父亲稍作停顿，然后说话。'
    prior=prior_fixture(tmp_path,text);run=tmp_path/'run'
    if scenario=='minor_spec':
        plan=read(prior/'PLAN.json');plan['specification']=runner.spec_rules.config()
        runner.transport.atomic(prior/'PLAN.json',plan)
    runner.prepare(run,prior)
    seen=[]
    class Fake:
        def __init__(self,run,plan,state):self.run,self.state=run,state
        def save(self):runner.transport.atomic(self.run/'STATE.json',self.state)
        def call(self,node,role,prompt,payload,schema):
            seen.append((node,payload));self.state['calls_started']+=1
            if scenario=='minor_spec':
                assert '近景' in prompt and '微动作' in prompt
                assert 'supported的facts/continuity/scope以及production/blocking不可keep' not in prompt
            if node.endswith('_review'):
                assert 'relevant_history' not in payload and 'review' not in payload
                if scenario=='minor_spec':
                    note=issue();note.update(subject='停顿措辞',claim='停顿措辞可简化',kind='expression',reason='信息与动作顺序已清晰',
                        scopes=[dict(quote=text,boundary='可选措辞')])
                    return dict(issues=[note],summary='只有轻微表达问题')
                return dict(issues=[issue()] if node=='cycle_0_review' and scenario!='missing_contract' else [],summary='已审')
            if node.endswith('_verify'):
                items=payload['review']['issues'];dec=[]
                for x in items:
                    v=verification(x,action='blocked' if scenario=='unresolvable' else 'repair_source',
                        decision='unresolved' if scenario=='unresolvable' else 'supported')['decisions'][0];dec.append(v)
                    if scenario=='minor_spec':v.update(action='keep',severity='style',scopes=[],reason='只是措辞略重复，事件主体、说话顺序和可执行性均不受影响。')
                return dict(decisions={d['id']:{k:v for k,v in d.items() if k!='id'} for d in dec},summary='完成')
            if node=='cycle_0_patch':
                return dict(edit_0='背景：父亲盛饭。',edit_1='正文：父亲盛饭。') if scenario=='retry' else dict(edit_0='背景：孩子盛饭。',edit_1='正文：孩子盛饭。')
            if node=='cycle_1_patch':
                return dict(edit_0='背景：孩子盛饭。',edit_1='正文：孩子盛饭。') if scenario=='retry' else dict(edit_0='完成。')
            if node.endswith('_check'):
                regressions=[]
                if scenario=='new_production' and node=='cycle_0_check':
                    x=issue();x.update(id='NEW',subject='收尾',scopes=[dict(quote='结尾。',boundary='确定收尾')]);regressions=[x]
                if scenario=='retry' and node=='cycle_0_check':
                    return dict(results=[dict(id='I1',result='unresolved',reason='未改动')],regressions=[issue()],summary='需继续')
                return dict(results=[dict(id=x['id'],result='resolved',reason='已改') for x in payload['confirmed_issues']],
                    regressions=regressions,summary='复核')
            raise AssertionError(node)
    monkeypatch.setattr(runner.transport,'Transport',Fake);runner.execute(run)
    state=read(run/'STATE.json');expected={'success':'text_contract_complete','new_production':'text_contract_complete',
        'retry':'text_contract_complete',
        'unresolvable':'auto_failed_unresolvable_evidence','missing_contract':'auto_failed_open_contract','minor_spec':'text_contract_complete'}[scenario]
    assert state['status']==expected
    assert not state['requires_human_confirmation'] and not state['requires_primary_acceptance'] and not state['video_released']
    assert read(run/'PLAN.json')['max_calls']==27
    if scenario=='minor_spec':
        assert state['patch_rounds']==0
        assert read(run/'ISSUE_REGISTRY.json')[0]['status']=='kept_style'
        assert not any(node.endswith('_patch') for node,_ in seen)
    if scenario in ('new_production','retry'):
        assert state['patch_rounds']==2
        assert seen[-1][0]=='cycle_2_review'
        assert all(x['status']=='resolved' for x in read(run/'ISSUE_REGISTRY.json'))
    assert (prior/'SCREENPLAY.md').read_text(encoding='utf-8')==text


def test_real_previous_production_findings_now_create_patch_plan():
    path=Path('data/corpus_production_trials/20261101_script_agent_v2_full_repeat')
    report=read(path/'round_0_review.json');source=read(path/'INPUT.json');text=(path/'SCREENPLAY.md').read_text(encoding='utf-8')
    v=dict(decisions=[dict(id=x['id'],decision='supported',severity='production',action='repair_neutral',
        reason='离线机械回放，不代表语义修复',source_ids=x['source_ids'],scopes=x['scopes']) for x in report['issues']],summary='offline')
    a=n.adjudicate(source,text,report,v)
    assert len(a['accepted'])==4 and len(n.patch_plan(text,a)['slots'])==4


def test_actual_corpus_retrieves_missing_relationship_and_clothing_evidence():
    path=Path('data/corpus_production_trials/20261101_script_agent_v2_full_repeat')
    source=read(path/'SOURCE.json');packet=read(path/'INPUT.json')
    report=read(path/'round_0_review.json')
    enriched,log=n.retrieve(source,packet,report['issues'])
    refs={p['id'] for ch in enriched['chapters'] if ch['role']=='evidence_only' for p in ch['paragraphs']}
    assert 'CH18-P003' in refs
    texts=[p['text'] for ch in enriched['chapters'] if ch['chapter']==20 for p in ch['paragraphs']]
    assert any('送货上门' in x or '送过去' in x for x in texts)


def test_typographic_address_recovers_native_span_without_word_or_number_changes():
    native='（角色心声：两个房间没有窗帘，得买窗帘；床还能用，被子重新买。）'
    assert n.resolve_typographic_span(native,native.replace('；','，'))==native
    for wrong in [native.replace('两个','三个'),native.replace('没有','有'),native.replace('床还能用','床不能用')]:
        with pytest.raises(ValueError):n.resolve_typographic_span(native,wrong)
    with pytest.raises(ValueError):n.resolve_typographic_span(native+native,native.replace('；','，'))
    with pytest.raises(ValueError):n.resolve_typographic_span('角色说物品金额是1.2元整。','角色说物品金额是12元整。')


def test_real_completed_verification_now_has_unique_patch_ranges():
    p=Path('data/corpus_production_trials/20261101_autonomous_revision_v3_gap')
    text=(p/'SCREENPLAY.md').read_text(encoding='utf-8')
    a=n.adjudicate(read(p/'FINAL_SOURCE.json'),text,read(p/'cycle_0_COMBINED_REVIEW.json'),read(p/'cycle_0_verify.json'))
    assert any(x['requested_scopes']!=x['scopes'] for x in a['accepted'])
    assert n.patch_plan(text,a)['slots']


def test_completed_review_can_resume_without_replaying_deepseek(tmp_path):
    p=Path('data/corpus_production_trials/20261101_autonomous_revision_v3_gap')
    run=tmp_path/'resume';runner.prepare(run,p,resume_review='cycle_0_review')
    assert read(run/'IMPORTED_REVIEW.json')['call']==369
    assert read(run/'PLAN.json')['max_calls']==389
    assert len(read(run/'OPEN_ISSUES.json'))==4


def test_verification_ids_are_schema_keys_not_model_generated_values():
    report=dict(issues=[issue()],summary='核验')
    d=verification()['decisions'][0]
    value=dict(decisions={'I1':{k:v for k,v in d.items() if k!='id'}},summary='完成')
    assert n.decode_verification(report,value)==verification()
    value['decisions']['I2']=value['decisions'].pop('I1')
    with pytest.raises(n.c.ContractError):n.decode_verification(report,value)


def test_resume_imported_review_keeps_latest_accounting_and_original_review(tmp_path):
    prior=Path('data/corpus_production_trials/20261101_autonomous_revision_v3_address')
    run=tmp_path/'imported';runner.prepare(run,prior,resume_review='imported')
    assert read(run/'STATE.json')['calls_started']==371
    assert read(run/'PLAN.json')['max_calls']==389
    assert read(run/'IMPORTED_REVIEW.json')['call']==369


def test_real_model_claimed_pending_deleted_but_program_gate_rejects_actual_text():
    p=Path('data/corpus_production_trials/20261101_autonomous_revision_v3_identity')
    text=(p/'cycle_0_AFTER.md').read_text(encoding='utf-8')
    check=read(p/'cycle_0_check.json')
    assert next(x for x in check['results'] if x['id']=='pending-section')['result']=='resolved'
    gate=n.completion_gate(text,[dict(status='resolved')],True)
    assert not gate['passed'] and 'unresolved_handoff_language' in gate['failures']


def test_real_schema_displacement_recovery_and_budget_preservation(tmp_path):
    import json
    p=Path('data/corpus_production_trials/20261101_autonomous_revision_v3_identity')
    native=read(p/'RESPONSE_376.json')['choices'][0]['message']
    raw=json.loads(native['tool_calls'][0]['function']['arguments'])
    report=read(p/'cycle_1_COMBINED_REVIEW.json')
    fixed,receipt=n.repair_unique_misplaced_scopes(report,raw)
    assert fixed['decisions']['pending-general']['scopes']==raw['decisions']['scopes']['item']
    assert 'scopes' not in fixed['decisions'] and receipt['values_unchanged']
    canonical=n.decode_verification(report,fixed)
    text=(p/'SCREENPLAY.md').read_text(encoding='utf-8')
    a=n.adjudicate(read(p/'FINAL_SOURCE.json'),text,report,canonical)
    assert n.patch_plan(text,a)['slots']
    run=tmp_path/'continue';runner.prepare(run,p,resume_verification='cycle_1_verify')
    assert read(run/'STATE.json')['calls_started']==376
    plan=read(run/'PLAN.json');assert plan['max_calls']==389 and plan['max_repair_rounds']==1
    assert read(run/'OPEN_LINKS.json')


def test_protocol_recovery_refuses_ambiguous_field_owner():
    x=issue();second=deepcopy(x);second['id']='I2';report=dict(issues=[x,second],summary='two')
    d=verification()['decisions'][0];value={k:v for k,v in d.items() if k not in ('id','scopes')}
    raw=dict(decisions={'I1':deepcopy(value),'I2':deepcopy(value),'scopes':{'item':x['scopes']}},summary='bad')
    with pytest.raises(ValueError):n.repair_unique_misplaced_scopes(report,raw)


def test_metadata_item_address_never_selects_story_dialogue_or_another_label():
    text='人物甲：3. 衣物来源需确认。\n三、制作口径\n3. 衣物来源与送达批次说明：当日已经穿着新衣。'
    quote='3. 衣物来源与送达批次说明：当日已穿新衣。'
    assert n.resolve_typographic_span(text,quote)=='3. 衣物来源与送达批次说明：当日已经穿着新衣。'
    with pytest.raises(ValueError):n.resolve_typographic_span(text,quote.replace('3.','4.'))


def test_runtime_recovers_only_known_completed_protocol_failure_without_new_call(tmp_path):
    import json
    p=Path('data/corpus_production_trials/20261101_autonomous_revision_v3_identity')
    report=read(p/'cycle_1_COMBINED_REVIEW.json');response=read(p/'RESPONSE_376.json')
    freeze(tmp_path/'RESPONSE_376.json',response)
    class Fake:
        def __init__(self):
            self.run=tmp_path;self.calls=0
            self.state=dict(calls_started=376,pending=None,status='known_invalid_output',trial_ended=True,nodes={'verify':{'status':'known_invalid_output'}})
        def call(self,*args):self.calls+=1;raise n.c.ContractError([])
        def save(self):pass
    t=Fake();fixed=runner.call_verification(t,'verify',dict(review=report))
    assert t.calls==1 and t.state['calls_started']==376 and not t.state['trial_ended']
    assert n.decode_verification(report,fixed)['decisions']
    assert (tmp_path/'verify_PROTOCOL_RECOVERY.json').exists()


def test_new_user_requested_full_trial_has_fresh_window_and_source_but_no_old_opinions(tmp_path):
    prior=prior_fixture(tmp_path)
    enriched=deepcopy(SOURCE)
    enriched['chapters'].append(dict(chapter=0,role='evidence_only',paragraphs=[dict(id='CH0-P001',text='已检索到的原文。')]))
    freeze(prior/'FINAL_SOURCE.json',enriched)
    with pytest.raises(ValueError,match='request_record'):runner.prepare(tmp_path/'unauthorized',prior,mode='full')
    run=tmp_path/'fresh';runner.prepare(run,prior,mode='full',request_text='再次生产执行，用前几轮章节')
    assert read(run/'INPUT.json')==enriched
    assert read(run/'PLAN.json')['max_calls']==read(prior/'STATE.json')['calls_started']+24
    assert read(run/'OPEN_ISSUES.json')==[] and read(run/'PREVIOUS_REGISTRY.json')==[]
    assert not (run/'ORIGINAL.md').exists()
    assert read(run/'AUTHORIZATION.json')['new_user_requested_full_trial']


@pytest.mark.parametrize('second', ['valid','invalid','drop'])
def test_address_retry_is_bounded_and_cannot_drop_confirmed_issue(tmp_path,monkeypatch,second):
    good=verification();row=good['decisions'][0]
    raw=dict(decisions={'I1':{k:v for k,v in row.items() if k!='id'}},summary='核验')
    bad=deepcopy(raw);bad['decisions']['I1']['scopes'][0]['quote']='背景：父亲已经盛饭。'
    answer={'a0':row['scopes'][0]['quote'] if second=='valid' else '背景：父亲已经盛饭。'}
    if second=='drop':answer['action']='keep'
    calls=[]
    def call(t,node,payload,spec=None):
        calls.append(node)
        return bad
    monkeypatch.setattr(runner,'call_verification',call)
    class Fake:
        run=tmp_path
        def call(self,node,*args):calls.append(node);return answer
    t=Fake()
    payload=dict(source=SOURCE,candidate=TEXT,review=dict(issues=[issue()],summary='需要修'))
    if second=='valid':assert runner.verified_decisions(t,'verify',payload)['decisions'][0]['scopes']==row['scopes']
    else:
        with pytest.raises(ValueError):runner.verified_decisions(t,'verify',payload)
    assert calls==['verify','verify_address_quotes']
    assert read(tmp_path/'verify_ADDRESS_FAILURE.json')['candidate_digest']==digest(TEXT)


def test_real_failed_quote_omitted_voice_label_not_safe_typographic_change():
    p=Path('data/corpus_production_trials/20261101_autonomous_v3_full_production')
    text=(p/'SCREENPLAY.md').read_text(encoding='utf-8')
    d=read(p/'cycle_0_CANONICAL_VERIFY.json')['decisions'][3]
    with pytest.raises(ValueError,match='repair_range_not_unique'):
        n.resolve_typographic_span(text,d['scopes'][0]['quote'])


def test_known_address_resume_copies_quotes_only_and_keeps_remaining_round_budget(tmp_path):
    prior=Path('data/corpus_production_trials/20261101_autonomous_v3_full_production_continued')
    run=tmp_path/'resume'
    runner.prepare(run,prior,resume_verification='cycle_1_verify_address_retry')
    imported=read(run/'IMPORTED_DECISIONS.json')
    original=read(prior/'cycle_1_verify.json')
    fixed=imported['repaired_native_value']
    assert fixed['decisions']['2']['severity']==original['decisions']['2']['severity']=='production'
    original['decisions']['2']['scopes'][0]['quote']=fixed['decisions']['2']['scopes'][0]['quote']
    assert fixed==original
    assert read(run/'PLAN.json')['max_calls']==404
    assert read(run/'PLAN.json')['max_repair_rounds']==1
