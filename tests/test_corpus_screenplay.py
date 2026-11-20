import hashlib
import json
from types import SimpleNamespace
import pytest
from src.content_factory.corpus_screenplay_v1 import prepare,execute,group_chapters,validate_analysis,evidence_matches,resume_known_analysis

def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8');return p

def setup_run(tmp_path, new_policy=False):
    chapters=[]
    for i in range(1,4):
        text=f'这是第{i}章真实的正文与人物因果。'*30
        c={'book_id':'book','index':i,'title':str(i),'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
        p=put(tmp_path/f'c{i}.json',c);chapters.append({'path':str(p),'sha256':c['sha256']})
    m=put(tmp_path/'m.json',{'status':'accessible_catalogue_complete','book_id':'book','book_name':'书','chapters':chapters})
    old=put(tmp_path/'old.json',{'calls_started':6,'reported_tokens':136045})
    run=tmp_path/'run';prepare(m,run,user_statement='修改流程重新跑啊',previous_status=old,parallel_analysis=False)
    if not new_policy:
        # Existing frozen v1 jobs must retain their original review semantics.
        p=json.loads((run/'PLAN.json').read_text(encoding='utf-8'));p.pop('review_cycle');p['schema']='corpus_screenplay/v1';put(run/'PLAN.json',p)
    elif new_policy is True:
        from src.content_factory.screenplay_review_cycle_v2 import policy
        p=json.loads((run/'PLAN.json').read_text(encoding='utf-8'));p['review_cycle']=policy();p['schema']='corpus_screenplay/v2';put(run/'PLAN.json',p)
    elif new_policy=='v3':
        from src.content_factory.screenplay_revision_v3 import policy
        p=json.loads((run/'PLAN.json').read_text(encoding='utf-8'));p['review_cycle']=policy();p['schema']='corpus_screenplay/v3';put(run/'PLAN.json',p)
    return run

class Client:
    calls=0
    def call(self,role,messages,**kwargs):
        self.calls+=1;c=json.loads(messages[-1]['content'])
        if 'chapters' in c:
            out={'chapters':[{'index':x['index'],'summary':'对应章节因果','evidence_quote':x['text'][:16]} for x in c['chapters']],
                 'world_facts':[],'characters':[],'candidate_scenes':[]}
        elif 'analysis_batches' in c:out={'selected_chapter_indices':[1,2]}
        elif role=='writer':out='完整自然剧本'
        else:out={'decision':'pass','whole_selected_source_reviewed':True,'checks':dict.fromkeys(['source_causality','character_relationships','opening_information','environment','emotion_and_gaze','parallel_action_dialogue','camera_continuity','dialogue_timing'],'pass'),'issues':[]}
        return SimpleNamespace(text=out if isinstance(out,str) else json.dumps(out),metadata={'total_tokens':100},response_payload={})

def test_full_pipeline_preserves_history_and_no_replay(tmp_path):
    run=setup_run(tmp_path);client=Client();result=execute(run,client)
    assert result['source_chapters']==3 and result['calls_started']==4
    assert result['total_calls_with_history']==10 and result['total_tokens_with_history']==136445
    assert result['automatic_video_dispatch'] is False
    execute(run,client);assert client.calls==4

def test_unknown_call_never_replayed(tmp_path):
    run=setup_run(tmp_path)
    class Broken(Client):
        def call(self,*a,**k):self.calls+=1;raise TimeoutError()
    c=Broken()
    with pytest.raises(TimeoutError):execute(run,c)
    assert execute(run,c)['status']=='outcome_unknown' and c.calls==1

def test_no_dropped_chapters_and_quote_binding():
    with pytest.raises(ValueError,match='coverage'):validate_analysis({'chapters':[]},[{'index':1,'text':'正文'}])
    with pytest.raises(ValueError,match='evidence'):validate_analysis({'chapters':[{'index':1,'summary':'s','evidence_quote':'错引文至少八个字'}]},[{'index':1,'text':'正文'}])
    groups=group_chapters([{'text':'a'*6,'index':i} for i in range(5)],10)
    assert [c['index'] for g in groups for c in g]==list(range(5))

def test_changed_source_refused_before_call(tmp_path):
    run=setup_run(tmp_path);v=json.loads((run/'SOURCE.json').read_text(encoding='utf-8'));v['chapters'][0]['text']='改动';put(run/'SOURCE.json',v)
    c=Client()
    with pytest.raises(ValueError,match='source_changed'):execute(run,c)
    assert c.calls==0

def test_evidence_only_normalizes_typography():
    assert evidence_matches('“他说话。然后走了”','他说话。\n\n然后走了，')
    assert not evidence_matches('他生气。然后走了','他说话。\n\n然后走了，')

def test_known_analysis_repair_preserves_failed_native(tmp_path):
    run=setup_run(tmp_path)
    class Repair(Client):
        def call(self,*a,**k):
            r=super().call(*a,**k)
            if self.calls==1:
                v=json.loads(r.text);v['chapters'][0]['evidence_quote']='不是原文的引用';r.text=json.dumps(v)
            return r
    c=Repair();state=execute(run,c)
    assert state['status']=='reviewed_draft_ready' and c.calls==5
    first=json.loads((run/'ANALYSIS_001.json').read_text(encoding='utf-8'))
    assert first['chapters'][0]['evidence_quote']=='不是原文的引用'
    assert (run/'ANALYSIS_001_REPAIR.json').exists()

def test_resume_never_unlocks_unknown(tmp_path):
    run=setup_run(tmp_path);s=json.loads((run/'STATE.json').read_text(encoding='utf-8'));s.update(status='outcome_unknown',pending='request');put(run/'STATE.json',s)
    with pytest.raises(ValueError,match='only_known'):resume_known_analysis(run)

def test_second_analysis_error_gets_only_bad_chapter_context(tmp_path):
    run=setup_run(tmp_path)
    class Focus(Client):
        def call(self,role,messages,**kwargs):
            payload=json.loads(messages[-1]['content'])
            r=super().call(role,messages,**kwargs)
            if self.calls<=2:
                v=json.loads(r.text);v['chapters'][0]['evidence_quote']='不是原文的引用';r.text=json.dumps(v)
            if self.calls==3:
                assert [x['index'] for x in payload['chapters']]==[1]
                assert len(payload['incorrect_chapter_rows'])==1
            return r
    c=Focus();s=execute(run,c)
    assert s['status']=='reviewed_draft_ready' and c.calls==6
    assert (run/'ANALYSIS_001_ACCEPTED.json').exists()

def test_fact_locator_only_moves_unique_exact_quote():
    from src.content_factory.corpus_screenplay_v1 import locate_fact_evidence
    original={'characters':[{'name':'甲','index':1,'quote':'原文中独有的句子'}]}
    chapters=[{'index':1,'text':'不同正文'},{'index':2,'text':'这是原文中独有的句子。'}]
    corrected=locate_fact_evidence(original,chapters)
    assert corrected['characters'][0]['index']==2 and original['characters'][0]['index']==1
    assert corrected['exact_quote_location_corrections'][0]['from_index']==1
    ambiguous=locate_fact_evidence(original,chapters+[{'index':3,'text':'原文中独有的句子'}])
    assert ambiguous['characters'][0]['index']==1

def test_writing_continuation_preserves_plan_and_cannot_add_analysis(tmp_path):
    from src.content_factory.corpus_screenplay_v1 import continue_writing
    run=setup_run(tmp_path);original=(run/'PLAN.json').read_bytes()
    s=json.loads((run/'STATE.json').read_text(encoding='utf-8'))
    limit=json.loads(original)['new_call_limit']
    s.update(status='needs_attention',stage='SELECTION',calls_started=limit,reported_tokens=900,reason='ValueError:new_scope_budget_exhausted')
    put(run/'STATE.json',s);put(run/'SELECTION.json',{'selected_chapter_indices':[1]})
    result=continue_writing(run,'same requested task; original estimate excluded failed analysis work')
    assert result['calls_started']==limit and (run/'PLAN.json').read_bytes()==original
    c=Client()
    with pytest.raises(ValueError,match='cannot_restart_analysis'):execute(run,c)
    assert c.calls==0

def test_received_length_can_settle_once_but_timeout_cannot(tmp_path):
    from src.content_factory.corpus_screenplay_v1 import recover_known_writer_truncation,digest,visible_script
    run=setup_run(tmp_path);plan=json.loads((run/'PLAN.json').read_text(encoding='utf-8'))
    put(run/'WRITING_CONTINUATION.json',{'original_plan_sha256':digest(plan),'additional_calls':4})
    state={'status':'outcome_unknown','stage':'SCREENPLAY','calls_started':2,'reported_tokens':100,'pending':'CALL_002.json'}
    put(run/'STATE.json',state);put(run/'ERROR_002.json',{'type':'TimeoutError','metadata':None,'response_payload':None})
    with pytest.raises(ValueError,match='unknown_or'):recover_known_writer_truncation(run)
    meta={'response_fault_code':'RESPONSE_TRUNCATED','finish_reason':'length','response_id':'known','response_model':'MiniMax-M3','requested_model':'MiniMax-M3','prompt_tokens':10,'completion_tokens':20,'total_tokens':30}
    put(run/'ERROR_002.json',{'type':'RoleResponseError','metadata':meta,'response_payload':{'id':'known','choices':[{'finish_reason':'length'}],'usage':{k:meta[k] for k in ('prompt_tokens','completion_tokens','total_tokens')}}})
    settled=recover_known_writer_truncation(run)
    assert settled['reported_tokens']==130 and settled['pending'] is None
    assert (run/'ERROR_002.json').exists() and (run/'KNOWN_TRUNCATION_RECOVERY.json').exists()
    with pytest.raises(ValueError):recover_known_writer_truncation(run)
    assert visible_script('<think>internal</think>正文')=='正文'

def test_dialogue_statistics_are_computed():
    from src.content_factory.corpus_screenplay_v1 import dialogue_stats
    v=dialogue_stats('苏墨：“我相信你。”\n叶东：“我没偷。”\n对白总数自报999轮。')
    assert v['matched_dialogue_lines']==2 and v['spoken_characters']==7
