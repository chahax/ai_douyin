import copy
import json
from types import SimpleNamespace
import pytest
from src.content_factory.screenplay_review_cycle_v2 import CHECKS,run_cycle,validate_review,text_sha,timing_constraints
from src.content_factory.corpus_screenplay_v1 import execute,read,prepare_rework,resume_review_validation
from test_corpus_screenplay import setup_run,put,Client


def review_for(payload, *, fail=False, advice=True):
    draft=payload['screenplay'];chapters=payload['selected_original_chapters']
    return {'reviewed_draft_sha256':text_sha(draft),'whole_draft_reviewed':True,
        'reviewed_chapter_indices':[c['index'] for c in chapters],
        'decision':'revise' if fail else 'pass',
        'checks':{k:'fail' if fail and k=='source_causality' else 'pass' for k in CHECKS},
        'blocking_issues':[{'check':'source_causality','location':'开头',
            'source_evidence':[{'chapter_index':chapters[0]['index'],'quote':chapters[0]['text'][:12]}],
            'draft_quote':draft[:12],'reason':'漏了原文必要前因','required_change':'补足因果，保持其他人物状态'}] if fail else [],
        'non_blocking_notes':[{'suggestion':'optional wording; never send to writer'}] if advice else [],
        'timing_assessment':[{'segment':'all','reason':'natural speech with serial action'}]}


class CycleClient(Client):
    def __init__(self, mode='pass'):
        self.calls=0;self.events=[];self.mode=mode;self.reviews=0;self.writers=0
    def call(self,role,messages,**kwargs):
        payload=json.loads(messages[-1]['content']);self.events.append((role,payload))
        if 'screenplay' not in payload and role!='writer':return super().call(role,messages,**kwargs)
        self.calls+=1
        if role=='writer':
            self.writers+=1
            if self.writers>1:
                assert 'required_revisions' in payload and 'non_blocking_notes' not in payload
                assert 'optional wording' not in json.dumps(payload)
            out='完整自然剧本修订'+str(self.writers)+'，人物动作和因果。'
        else:
            assert 'selection' not in payload
            assert payload['required_reviewed_chapter_indices']==[c['index'] for c in payload['selected_original_chapters']]
            self.reviews+=1
            failure=self.mode=='always_fail' or (self.mode=='revise' and self.reviews<=2)
            out=review_for(payload,fail=failure)
            if self.mode=='invalid_quote' and self.reviews==1:
                out=review_for(payload,fail=True);out['blocking_issues'][0]['source_evidence'][0]['quote']='根本不在原文中的审查杜撰'
            if self.mode=='bad_sha':out['reviewed_draft_sha256']='wrong'
            if self.mode=='audit_catches' and self.reviews==2:out=review_for(payload,fail=True)
        return SimpleNamespace(text=out if isinstance(out,str) else json.dumps(out,ensure_ascii=False),
            metadata={'total_tokens':100,'finish_reason':'stop'},response_payload={})


def test_new_pipeline_allows_advice_binds_final_and_never_replays(tmp_path):
    run=setup_run(tmp_path,True);c=CycleClient();s=execute(run,c)
    assert s['calls_started']==5 and s['total_calls_with_history']==11
    b=read(run/'REVIEW_BINDING.json')
    assert b['draft_sha256']==text_sha((run/'剧本_全可读范围选段.md').read_text(encoding='utf-8'))
    assert read(run/'REVIEW_00.json')['non_blocking_notes']
    assert execute(run,c)==s and c.calls==5 and s['automatic_video_dispatch'] is False


def test_review_rewrite_full_review_audit_closed_loop(tmp_path):
    run=setup_run(tmp_path,True);c=CycleClient('revise');s=execute(run,c)
    assert s['calls_started']==8 and c.writers==2 and c.reviews==4
    assert read(run/'REVIEW_00.json')['decision']=='revise'
    assert read(run/'REVIEW_BINDING.json')['revisions']==1
    assert (run/'SCREENPLAY.md').read_text(encoding='utf-8')!= (run/'SCREENPLAY_REVISION_01.md').read_text(encoding='utf-8')


def test_invalid_review_repairs_review_not_writer(tmp_path):
    run=setup_run(tmp_path,True);c=CycleClient('invalid_quote');execute(run,c)
    assert c.writers==1 and (run/'REVIEW_00_REPAIR.json').exists()
    assert read(run/'REVIEW_00.json')['blocking_issues'][0]['source_evidence'][0]['quote']=='根本不在原文中的审查杜撰'


def test_audit_catches_problem_missed_by_initial_review(tmp_path):
    run=setup_run(tmp_path,True);c=CycleClient('audit_catches');execute(run,c)
    assert c.writers==2 and read(run/'REVIEW_00.json')['decision']=='pass'
    assert read(run/'REVIEW_AUDIT_00.json')['decision']=='revise'


@pytest.mark.parametrize('mode,reason',[('bad_sha','binding_mismatch'),('always_fail','revision_limit')])
def test_no_false_pass_or_infinite_rewrite(tmp_path,mode,reason):
    run=setup_run(tmp_path,True);c=CycleClient(mode)
    with pytest.raises(ValueError,match=reason):execute(run,c)
    assert read(run/'STATE.json')['status']=='needs_attention'
    assert not (run/'剧本_全可读范围选段.md').exists()
    before=c.calls;execute(run,c);assert c.calls==before
    assert c.writers <= 3


@pytest.mark.parametrize('mutate',[
 lambda v:v.update(decision='pass'),
 lambda v:v['blocking_issues'][0].update(draft_quote='不在当前稿中的引文'),
 lambda v:v['blocking_issues'][0].update(source_evidence=[]),
 lambda v:v['checks'].update(dialogue_timing='fail'),
 lambda v:v.update(reviewed_chapter_indices=[]),
])
def test_validator_rejects_inconsistent_or_unbound_review(mutate):
    p={'screenplay':'完整剧本中的一句实际对白。','selected_original_chapters':[{'index':4,'text':'来源中明确交代的事实和动机。'}]}
    v=review_for(p,fail=True);mutate(v)
    with pytest.raises(ValueError):validate_review(v,p['screenplay'],p['selected_original_chapters'])


@pytest.mark.parametrize('story',[
 ('哥哥交给妹妹钥匙，妹妹打开旧家门。','妹妹拿到钥匙以后开门；哥哥提包进屋。'),
 ('老员工没有提出辞职，经理递来辞职申请。','经理把离职申请推近，员工停笔追问原因。'),
 ('渡船午后才开，女儿收好船票等父亲。','女儿握着船票看向父亲，两人沿栈桥走。'),
])
def test_contract_has_no_story_specific_dialogue_or_cast(story):
    context={'selected_original_chapters':[{'index':1,'text':story[0]}],'target_seconds':60}
    events=[]
    def call(name,role,prompt,payload,json_output=True):
        events.append(name)
        return story[1] if role=='writer' else review_for(payload)
    result,binding=run_cycle(call,context,lambda t:{})
    assert result==story[1] and events==['SCREENPLAY','REVIEW_00','REVIEW_AUDIT_00']
    assert binding['revisions']==0


def test_unknown_review_is_not_replayed(tmp_path):
    run=setup_run(tmp_path,True)
    class Unknown(CycleClient):
        def call(self,role,messages,**kwargs):
            if 'screenplay' in json.loads(messages[-1]['content']):self.calls+=1;raise TimeoutError('transport')
            return super().call(role,messages,**kwargs)
    c=Unknown()
    with pytest.raises(TimeoutError):execute(run,c)
    assert read(run/'STATE.json')['pending'] and execute(run,c)['status']=='outcome_unknown'
    assert c.calls==4


def test_native_received_rejection_accounts_usage_without_replay(tmp_path):
    run=setup_run(tmp_path,True)
    class Truncated(CycleClient):
        def call(self,*a,**k):
            self.calls+=1
            e=RuntimeError('known received length')
            e.response_metadata={'response_id':'id','finish_reason':'length','prompt_tokens':10,'completion_tokens':20,'total_tokens':30}
            e.response_payload={'id':'id','choices':[{'finish_reason':'length'}],'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}
            raise e
    c=Truncated()
    with pytest.raises(RuntimeError):execute(run,c)
    s=execute(run,c);assert s['status']=='needs_attention' and s['pending'] is None
    assert s['reported_tokens']==30 and c.calls==1


def test_rework_rejects_unknown_before_creating_scope(tmp_path):
    old=tmp_path/'old';put(old/'STATE.json',{'status':'outcome_unknown','pending':'call'})
    put(old/'PLAN.json',{})
    with pytest.raises(ValueError,match='known_completed'):prepare_rework(old,tmp_path/'new',user_statement='流程修复',previous_status=tmp_path/'history')
    assert not (tmp_path/'new').exists()


def make_rejected_source(tmp_path):
    previous=setup_run(tmp_path)
    draft='MiniMax原生完整失败稿，未经助手修改。'
    (previous/'SCREENPLAY_REVISION.md').write_text(draft,encoding='utf-8')
    put(previous/'STATE.json',{'status':'needs_attention','pending':None,'calls_started':2,'reported_tokens':200})
    put(previous/'REVIEW_REVISION.json',{'decision':'revise'})
    put(previous/'SELECTION.json',{'selected_chapter_indices':[1,2]})
    put(previous/'CALL_001.json',{'name':'SCREENPLAY_REVISION','role':'writer'})
    put(previous/'RESPONSE_001.json',{'text':draft,'metadata':{'finish_reason':'stop'}})
    put(previous/'CALL_002.json',{'name':'REVIEW_REVISION','role':'director','messages':[{'role':'user','content':json.dumps({'screenplay':draft})}]})
    put(previous/'RESPONSE_002.json',{'metadata':{'finish_reason':'stop'}})
    history=put(tmp_path/'latest.json',{'status':'text_revision_review_complete','pending':None,'calls_started':1,'reported_tokens':100,
        'cumulative_calls':9,'cumulative_reported_tokens':136345})
    return previous,history


def test_rework_uses_original_model_draft_and_cumulative_history(tmp_path,monkeypatch):
    from src.content_factory import corpus_screenplay_v1
    from src.content_factory.screenplay_review_cycle_v2 import policy
    monkeypatch.setattr(corpus_screenplay_v1,'review_policy',policy)
    previous,history=make_rejected_source(tmp_path)
    original={p.name:p.read_bytes() for p in previous.iterdir() if p.is_file()}
    run=tmp_path/'rework'
    plan=prepare_rework(previous,run,user_statement='改自动化流程后验证',previous_status=history)
    assert plan['inherited_consumption']=={'calls_started':9,'reported_tokens':136345}
    client=CycleClient();s=execute(run,client)
    assert client.writers==0 and client.reviews==2 and s['calls_started']==2
    assert s['total_calls_with_history']==11 and s['analysis_reused']
    assert all((previous/name).read_bytes()==value for name,value in original.items())


def test_rework_rejects_hand_edited_draft_and_reset_consumption(tmp_path):
    previous,history=make_rejected_source(tmp_path)
    draft=previous/'SCREENPLAY_REVISION.md';original=draft.read_bytes();draft.write_text('手工替换的稿',encoding='utf-8')
    with pytest.raises(ValueError,match='model_draft_changed'):prepare_rework(previous,tmp_path/'r1',user_statement='修流程',previous_status=history)
    draft.write_bytes(original)
    put(history,{'calls_started':1,'reported_tokens':100})
    with pytest.raises(ValueError,match='cumulative_history'):prepare_rework(previous,tmp_path/'r2',user_statement='修流程',previous_status=history)


def test_writer_not_called_without_review_and_audit_capacity():
    context={'selected_original_chapters':[{'index':1,'text':'原文中的真实来源句子。'}]}
    events=[]
    def call(name,role,prompt,payload,json_output=True):
        events.append(role);assert role=='director'
        return review_for(payload,fail=True)
    with pytest.raises(ValueError,match='insufficient_capacity'):
        run_cycle(call,context,lambda t:{},initial_draft='完整失败稿中的原话。',remaining_calls=lambda:2)
    assert events==['director','director']


def test_known_coverage_stop_continues_once_without_replaying_calls(tmp_path):
    run=setup_run(tmp_path,True)
    class Coverage(CycleClient):
        fixed=False
        def call(self,*a,**k):
            r=super().call(*a,**k)
            p=json.loads(a[1][-1]['content'])
            if 'screenplay' in p and not self.fixed:
                value=json.loads(r.text);value['reviewed_chapter_indices']=[1,2];r.text=json.dumps(value)
            return r
    c=Coverage()
    with pytest.raises(ValueError,match=r'expected=\[1, 2, 3\]'):execute(run,c)
    before=read(run/'STATE.json');old=(run/'REVIEW_00_REPAIR.json').read_bytes()
    resume_review_validation(run,user_statement='修流程并继续验证')
    c.fixed=True;s=execute(run,c)
    assert s['calls_started']==before['calls_started']+2 and c.writers==1
    assert (run/'REVIEW_00_REPAIR.json').read_bytes()==old
    assert (run/'REVIEW_00_REPAIR_RECOVERY.json').exists()
    with pytest.raises(ValueError,match='known_review_validation'):resume_review_validation(run,user_statement='再跑')


def test_review_validation_resume_cannot_clear_unknown(tmp_path):
    run=setup_run(tmp_path,True)
    state=read(run/'STATE.json');state.update(status='outcome_unknown',pending='CALL',stage='REVIEW_00_REPAIR',reason='ValueError:review_coverage_incomplete');put(run/'STATE.json',state)
    with pytest.raises(ValueError,match='known_review_validation'):resume_review_validation(run,user_statement='修流程')
    assert read(run/'STATE.json')['pending']=='CALL'


def test_local_segment_overflow_cannot_hide_behind_full_film_average():
    draft='**【0—20秒｜20秒】**\n甲：“你好。”\n\n**【20—22秒｜2秒】**\n乙：“这段话比两秒可以容纳的字数明显长得多而且还需要停顿。”'
    result=timing_constraints(draft)
    assert len(result['segments'])==2 and len(result['blocking_issues'])==1
    assert result['blocking_issues'][0]['location']=='20—22秒'


def test_model_pass_cannot_override_numeric_overflow_and_writer_can_repair():
    context={'selected_original_chapters':[{'index':1,'text':'原文人物之间进行了一次普通对话。'}]}
    seed='### 0—1秒\n甲：“这么长的一句话一秒肯定说不完。”'
    calls=[]
    def call(name,role,prompt,payload,json_output=True):
        calls.append(name)
        if role=='writer':
            assert payload['required_revisions'][0]['check']=='dialogue_timing'
            return '### 0—8秒\n甲：“这么长的一句话现在有足够时间了。”'
        return review_for(payload)
    result,binding=run_cycle(call,context,lambda t:{},initial_draft=seed)
    assert binding['revisions']==1 and 'SCREENPLAY_REVISION_01' in calls
    assert not timing_constraints(result)['blocking_issues']


def test_unrecognized_headings_do_not_claim_timing_coverage():
    assert timing_constraints('普通自然文本，没有标秒。')['segments']==[]
