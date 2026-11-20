import json
from types import SimpleNamespace
import pytest
from test_corpus_screenplay import setup_run,put
from test_screenplay_revision_v3 import V3Client
from test_screenplay_review_cycle_v2 import review_for
from src.content_factory.corpus_screenplay_v1 import execute,read,prepare_rework
from src.content_factory.screenplay_revision_v4 import segments,validate_timing,speech_constraints


class V4Client(V3Client):
    def call(self,role,messages,**kwargs):
        p=json.loads(messages[-1]['content'])
        if role!='writer' and 'screenplay' not in p:return super().call(role,messages,**kwargs)
        self.calls+=1;self.events.append((role,p))
        if role=='writer':
            self.writers+=1
            if self.writers==1:assert 'previous_draft' not in p and 'selection' not in p
            out='### 【0—20秒】\n动作：甲把钥匙交给乙，两人对视。\n甲：“钥匙交给你。”'
            if self.mode=='overflow_first' and self.writers==1:
                out='### 【0—2秒】\n动作：甲把钥匙交给乙，两人对视。\n甲：“'+('重复交代已经清楚的信息。'*8)+'”'
        else:
            self.reviews+=1
            fail=self.mode=='always_fail' or (self.mode=='revise' and self.writers==1)
            out=review_for(p,fail=fail)
            if 'segment_timing' in messages[0]['content']:
                out['segment_timing']=[{'range':'0—20','serial_actions':[{'quote':'甲把钥匙交给乙，两人对视。','seconds':2}],
                    'parallel_actions':[],'reason':'交接后短对白，有足够停顿'}]
                out['segment_timing'][0]['serial_actions'][0]={'evidence_id':p['measured_segments'][0]['evidence'][0]['id'],'seconds':2}
        return SimpleNamespace(text=out if isinstance(out,str) else json.dumps(out,ensure_ascii=False),
            metadata={'total_tokens':100,'finish_reason':'stop'},response_payload={})


def test_fresh_source_draft_and_independent_timing_rewrite(tmp_path):
    run=setup_run(tmp_path,'v4');c=V4Client('revise');s=execute(run,c)
    assert s['status']=='reviewed_draft_ready' and c.writers==2 and c.reviews==4
    assert read(run/'REVIEW_BINDING.json')['version']=='screenplay_revision/v4'
    before=c.calls;execute(run,c);assert c.calls==before


def test_segment_count_includes_inline_speech_and_rejects_gaps():
    rows=segments('### 【0—5秒】\n孩子：“一句台词。”\n厨房里父亲转身：“再来一句。”')
    assert rows[0]['spoken_units']==8
    with pytest.raises(ValueError,match='gap'):segments('### 0—5秒\n动作\n### 6—9秒\n动作')
    with pytest.raises(ValueError,match='coverage'):segments('没有秒数的稿件')


def test_numeric_overflow_cannot_be_cleared_by_semantic_pass():
    draft='### 【0—5秒】\n甲：“这是十个字的对白测试。”\n动作：走到桌旁再坐下。'
    measured=segments(draft)
    value={'decision':'pass','segment_timing':[{'range':'0—5',
        'serial_actions':[{'evidence_id':measured[0]['evidence'][0]['id'],'seconds':4}], 'parallel_actions':[],'reason':'走后再坐'}]}
    assert validate_timing(value,draft,measured)['blocking_issues']
    value['segment_timing'][0]['serial_actions'][0]['evidence_id']='S99-P1'
    with pytest.raises(ValueError,match='evidence'):validate_timing(value,draft,measured)


def test_overflow_is_rewritten_before_any_expensive_review(tmp_path):
    run=setup_run(tmp_path,'v4');c=V4Client('overflow_first');s=execute(run,c)
    assert s['status']=='reviewed_draft_ready' and c.writers==2 and c.reviews==2
    assert read(run/'SPEECH_PREFLIGHT_00.json')['blocking_issues']
    assert not (run/'REVIEW_00.json').exists()
    assert read(run/'REVIEW_BINDING.json')['review_name']=='REVIEW_01'


def test_both_drafts_overflow_stops_without_semantic_calls(tmp_path):
    from src.content_factory.screenplay_revision_v4 import run_cycle
    from src.content_factory.screenplay_revision_v3 import source_sha
    chapters=[{'index':1,'text':'原文中钥匙属于母亲。'}];names=[]
    def call(name,role,*args):
        names.append(name)
        if name=='FACT_CONTRACT':return {'source_sha256':source_sha(chapters),'facts':[{'id':'F1','kind':'ownership','statement':'钥匙属于母亲','source_evidence':[{'chapter_index':1,'quote':chapters[0]['text']}]}]}
        assert role=='writer'
        return '### 【0—1秒】\n甲：“这是一句根本说不完的很长的话。”'
    with pytest.raises(ValueError,match='speech_preflight_revision_limit'):
        run_cycle(call,{'selected_original_chapters':chapters},lambda s:{})
    assert names==['FACT_CONTRACT','SCREENPLAY_FRESH','SCREENPLAY_REVISION_01']


def test_remaining_scope_transfer_is_once_and_keeps_history(tmp_path):
    old=setup_run(tmp_path,'v3');c=V3Client('always_fail')
    with pytest.raises(ValueError):execute(old,c)
    state=read(old/'STATE.json');p=read(old/'PLAN.json');p['new_call_limit']=state['calls_started']+5;put(old/'PLAN.json',p)
    target=tmp_path/'new'
    plan=prepare_rework(old,target,user_statement='找原因接着改',previous_status=old/'STATE.json',reuse_remaining_budget=True)
    assert plan['new_call_limit']==5 and plan['new_token_limit']==p['new_token_limit']-state['reported_tokens']
    assert read(target/'FACT_CONTRACT.json')['facts']
    with pytest.raises(ValueError,match='transferred'):execute(old,V3Client())
    with pytest.raises(ValueError,match='transferred'):
        prepare_rework(old,tmp_path/'again',user_statement='继续',previous_status=old/'STATE.json',reuse_remaining_budget=True)
    result=execute(target,V4Client());assert result['calls_started']==3
    assert result['total_calls_with_history']==plan['inherited_consumption']['calls_started']+3


def test_invalid_reused_facts_cannot_transfer_or_create_new_run(tmp_path):
    old=setup_run(tmp_path,'v3')
    with pytest.raises(ValueError):execute(old,V3Client('always_fail'))
    facts=read(old/'FACT_CONTRACT_ACCEPTED.json');facts['source_sha256']='changed';put(old/'FACT_CONTRACT_ACCEPTED.json',facts)
    with pytest.raises(ValueError,match='source_binding'):
        prepare_rework(old,tmp_path/'new',user_statement='继续修',previous_status=old/'STATE.json',reuse_remaining_budget=True)
    assert not (old/'REWORK_BUDGET_TRANSFER.json').exists() and not (tmp_path/'new').exists()


@pytest.mark.parametrize('rows',[[None],[{'range':'0—5','serial_actions':[None],'parallel_actions':[]}]])
def test_bad_timing_structure_is_known_validation_failure(rows):
    draft='### 【0—5秒】\n动作：人物停步转身。'
    with pytest.raises(ValueError):validate_timing({'segment_timing':rows},draft,segments(draft))
