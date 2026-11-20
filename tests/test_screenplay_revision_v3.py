import copy
import json
from types import SimpleNamespace
import pytest
from test_corpus_screenplay import Client,setup_run,put
from test_screenplay_review_cycle_v2 import review_for
from src.content_factory.corpus_screenplay_v1 import execute,read,prepare_rework
from src.content_factory.screenplay_revision_v3 import source_sha,validate_contract,validate_disposition,locate_contract_evidence
from src.content_factory.screenplay_revision_v3 import draft_quote_anchors


def test_review_anchors_preserve_words_across_markdown_and_omitted_paragraphs():
    draft='## 场次四·家中厨房\n**人物：** 母亲与女儿\n**环境：** 暖光照着餐桌。\n**衔接：** 女儿推门走进来。'
    quote='场次四·家中厨房\n人物：母亲与女儿\n衔接：女儿推门走进来。'
    anchors=draft_quote_anchors(quote,draft)
    assert len(anchors)==3 and anchors[1]['end']<anchors[2]['start']
    assert not draft_quote_anchors(quote.replace('母亲','父亲'),draft)
    assert not draft_quote_anchors('衔接：女儿推门走进来。\n人物：母亲与女儿',draft)
    assert not draft_quote_anchors('人物：母亲与女儿……衔接：女儿推门走进来。',draft)
    assert not draft_quote_anchors('人物：\n衔接：女儿推门走进来。',draft)


def test_quote_validator_does_not_weaken_source_or_draft_binding():
    from src.content_factory.screenplay_review_cycle_v2 import validate_review,text_sha
    draft='**人物：** 母亲与女儿\n**环境：** 家中厨房。'
    chapters=[{'index':1,'text':'母亲把钥匙交给女儿。'}]
    payload={'screenplay':draft,'reviewed_draft_sha256':text_sha(draft),'required_reviewed_chapter_indices':[1], 'selected_original_chapters':chapters}
    r=review_for(payload,fail=True)
    r['blocking_issues'][0]['draft_quote']='人物：母亲与女儿'
    validate_review(r,draft,chapters,draft_quote_validator=draft_quote_anchors)
    with pytest.raises(ValueError,match='binding'):
        validate_review(r,draft+'发生变化',chapters,draft_quote_validator=draft_quote_anchors)


class V3Client(Client):
    def __init__(self,mode='pass'):
        self.calls=0;self.writers=0;self.reviews=0;self.events=[];self.mode=mode
    def call(self,role,messages,**kwargs):
        p=json.loads(messages[-1]['content']);self.events.append((role,p))
        if 'chapters' in p or 'analysis_batches' in p:return super().call(role,messages,**kwargs)
        self.calls+=1
        if 'source_sha256' in p and 'screenplay' not in p and role=='director':
            c=p['selected_original_chapters'][0]
            out={'source_sha256':source_sha(p['selected_original_chapters']),
                'facts':[{'id':'F1','kind':'ownership','statement':'从来源核对物品归属',
                    'source_evidence':[{'chapter_index':c['index'],'quote':c['text'][:12]}]}]}
        elif role=='writer':
            self.writers+=1
            assert p['source_fact_contract']['facts']
            assert 'non_blocking_notes' not in p and 'previous_review' not in p
            out='### 0—20秒\n甲：“这是模型原生完整剧情，第'+str(self.writers)+'稿的对白。”'
        else:
            self.reviews+=1
            assert 'previous_review' not in p and 'selection' not in p
            fail=self.mode=='always_fail' or (self.mode=='revise' and self.writers==1)
            out=review_for(p,fail=fail)
            if 'candidate_issues' in p:
                candidates=p['candidate_issues']
                out['issue_dispositions']=[{'issue_id':c['issue_id'],'decision':'confirm' if fail else 'dismiss','reason':'对照原文及当前稿裁决'} for c in candidates]
                if fail:out['blocking_issues'][0]['confirmed_issue_ids']=[c['issue_id'] for c in candidates]
        return SimpleNamespace(text=out if isinstance(out,str) else json.dumps(out,ensure_ascii=False),
            metadata={'total_tokens':100,'finish_reason':'stop'},response_payload={})


def test_fact_grounded_rebuild_blind_reviews_rewrite_and_binding(tmp_path):
    run=setup_run(tmp_path,'v3');c=V3Client('revise');s=execute(run,c)
    assert s['status']=='reviewed_draft_ready' and c.writers==2 and c.reviews==5
    assert s['calls_started']==10
    assert read(run/'REVIEW_BINDING.json')['version']=='screenplay_revision/v3'
    assert read(run/'REVIEW_ADJUDICATION_00.json')['decision']=='revise'
    assert read(run/'FACT_CONTRACT.json')['facts']
    before=c.calls;execute(run,c);assert c.calls==before


def test_reviews_are_blind_and_pass_does_not_invoke_adjudicator(tmp_path):
    run=setup_run(tmp_path,'v3');c=V3Client();execute(run,c)
    assert c.reviews==2 and not (run/'REVIEW_ADJUDICATION_00.json').exists()
    p1=read(run/'CALL_005.json')['messages'][-1]['content']
    p2=read(run/'CALL_006.json')['messages'][-1]['content']
    assert json.loads(p1)==json.loads(p2)


def test_contract_refuses_misattributed_source():
    chapters=[{'index':1,'text':'钥匙原本在哥哥手里，后来交给妹妹。'}]
    fact={'source_sha256':source_sha(chapters),'facts':[{'id':'F','kind':'ownership','statement':'钥匙交接',
        'source_evidence':[{'chapter_index':2,'quote':'钥匙原本在哥哥手里'}]}]}
    with pytest.raises(ValueError,match='quote_invalid'):validate_contract(fact,chapters)


def test_unique_exact_quote_location_is_audited_without_rewriting_fact():
    chapters=[{'index':4,'text':'这里是另一个章节。'},{'index':5,'text':'钥匙原本在哥哥手里，后来交给妹妹。'}]
    fact={'source_sha256':source_sha(chapters),'facts':[{'id':'F','kind':'ownership','statement':'钥匙交接',
        'source_evidence':[{'chapter_index':4,'quote':'钥匙原本在哥哥手里'}]}]}
    fixed=locate_contract_evidence(fact,chapters)
    assert fixed['facts'][0]['statement']==fact['facts'][0]['statement']
    assert fact['facts'][0]['source_evidence'][0]['chapter_index']==4
    assert fixed['exact_quote_location_corrections'][0]['to_chapter']==5
    assert validate_contract(fixed,chapters)
    ambiguous=chapters+[{'index':6,'text':chapters[1]['text']}]
    fixed=locate_contract_evidence(fact,ambiguous)
    assert fixed['facts'][0]['source_evidence'][0]['chapter_index']==4


def test_fact_resume_never_clears_unknown(tmp_path):
    from src.content_factory.corpus_screenplay_v1 import resume_fact_validation
    run=setup_run(tmp_path,'v3');state=read(run/'STATE.json')
    state.update(status='outcome_unknown',pending='call',stage='FACT_CONTRACT_REPAIR',reason='ValueError:fact_contract_quote_invalid');put(run/'STATE.json',state)
    with pytest.raises(ValueError,match='known_fact'):resume_fact_validation(run,user_statement='修复继续')
    assert read(run/'STATE.json')['pending']=='call'


def test_adjudication_cannot_silently_drop_confirmed_issue():
    candidates=[{'issue_id':'R1-1'},{'issue_id':'R2-1'}]
    v={'issue_dispositions':[{'issue_id':x['issue_id'],'decision':'confirm','reason':'确有证据'} for x in candidates],
        'blocking_issues':[{'confirmed_issue_ids':['R1-1']}]}
    with pytest.raises(ValueError,match='confirmed_issue_dropped'):validate_disposition(v,candidates)
    v['blocking_issues'][0]['confirmed_issue_ids'].append('R2-1')
    assert validate_disposition(v,candidates)==v


def test_failed_v3_stops_with_original_reviews(tmp_path):
    run=setup_run(tmp_path,'v3');c=V3Client('always_fail')
    with pytest.raises(ValueError,match='revision_limit'):execute(run,c)
    assert c.writers==3 and read(run/'STATE.json')['pending'] is None
    assert not (run/'剧本_全可读范围选段.md').exists()
    before=c.calls;execute(run,c);assert c.calls==before


def test_rework_accepts_v2_native_failed_seed_without_resetting_history(tmp_path,monkeypatch):
    from src.content_factory import corpus_screenplay_v1 as module
    from src.content_factory.screenplay_revision_v3 import policy
    monkeypatch.setattr(module,'review_policy',policy)
    from test_screenplay_review_cycle_v2 import CycleClient
    previous=setup_run(tmp_path,True);c=CycleClient('always_fail')
    with pytest.raises(ValueError,match='revision_limit'):execute(previous,c)
    originals={p.name:p.read_bytes() for p in previous.iterdir() if p.is_file()}
    run=tmp_path/'rework'
    plan=prepare_rework(previous,run,user_statement='找原因接着改',previous_status=previous/'STATE.json')
    assert plan['review_cycle']['version']=='screenplay_revision/v3'
    assert plan['inherited_consumption']['calls_started']==6+c.calls
    new=V3Client();s=execute(run,new)
    assert new.writers==1 and new.reviews==2 and s['analysis_reused']
    assert all((previous/n).read_bytes()==v for n,v in originals.items())


@pytest.mark.parametrize('text',[
    '车钥匙原本在母亲手里，她当面交给女儿，父亲仍在车库。',
    '辞职申请是经理带来的，员工始终没有提出辞职。',
    '船票由姐姐购买，弟弟拿着船票站在渡口等她。',
])
def test_contract_is_reusable_across_unrelated_stories(text):
    chapters=[{'index':8,'text':text}]
    value={'source_sha256':source_sha(chapters),'facts':[{'id':'F1','kind':'ownership','statement':text,
        'source_evidence':[{'chapter_index':8,'quote':text}]}]}
    assert validate_contract(value,chapters)==value
