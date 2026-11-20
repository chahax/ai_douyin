from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.contracts import digest
from src.content_factory.novel_adaptation.handoff import export_handoff,continue_state,qualify_information

SOURCE={'chapters':[{'index':1,'text':'甲把面包交给乙。'}]}
ENT={'entities':[{'id':x,'kind':'character','display_name':x} for x in ('a','b')]}
DESIGN={'places':[{'id':'room','description':'屋内'}],'props':[{'id':'bread','kind':'面包','description':'一块面包','owner':'a'}],
        'scenes':[{'id':'s1','place':'room'}],'initial_locations':{'a':'room','b':'room'}}
CANDIDATE={'design':DESIGN,'end_state':{'locations':{'a':'room','b':'room'},'props':{'bread':'b'},
    'information':{'b':[{'id':'s1:b1:a0','kind':'dialogue','speaker':'a','text':'给你。'}]}}}
REVIEW={'verdict':'accepted_text_pilot','candidate_sha256':digest(CANDIDATE),'source_sha256':digest(SOURCE)}

def fixture():
    handoff=export_handoff(CANDIDATE,ENT,SOURCE,REVIEW,book_id='book',episode_id='E01',timeline_id='CURRENT')
    plan=deepcopy(DESIGN);plan['props'][0]['owner']='b'
    return handoff,plan

def test_reviewed_handoff_keeps_owner_and_namespaces_known_information():
    h,p=fixture()
    state=continue_state(h,digest(h),p,ENT,book_id='book',episode_id='E02',timeline_id='CURRENT')
    assert state['props']=={'bread':'b'}
    assert state['information']['b'][0]['id']=='E01:s1:b1:a0'
    state['information']['b'].append({'id':'s1:b1:a0','kind':'dialogue','speaker':'b','text':'谢谢。'})
    next_state=qualify_information(state,'E02')
    assert [x['id'] for x in next_state['information']['b']]==['E01:s1:b1:a0','E02:s1:b1:a0']

@pytest.mark.parametrize('problem',['owner_reset','person_changed','wrong_book','wrong_timeline','replay','tamper'])
def test_continuation_rejects_reset_aliasing_replay_and_changed_snapshot(problem):
    h,p=fixture();e=deepcopy(ENT);sha=digest(h);book='book';episode='E02';timeline='CURRENT'
    if problem=='owner_reset':p['props'][0]['owner']='a'
    if problem=='person_changed':e['entities'][1]['display_name']='另一个乙'
    if problem=='wrong_book':book='other'
    if problem=='wrong_timeline':timeline='FLASHBACK'
    if problem=='replay':episode='E01'
    if problem=='tamper':h['state']['props']['bread']='a'
    with pytest.raises(ValueError):continue_state(h,sha,p,e,book_id=book,episode_id=episode,timeline_id=timeline)

def test_unreviewed_or_changed_candidate_cannot_export():
    with pytest.raises(ValueError,match='not_reviewed'):
        export_handoff(CANDIDATE,ENT,SOURCE,{**REVIEW,'verdict':'pass'},book_id='book',episode_id='E01',timeline_id='CURRENT')
    with pytest.raises(ValueError,match='stale'):
        export_handoff({**CANDIDATE,'extra':'change'},ENT,SOURCE,REVIEW,book_id='book',episode_id='E01',timeline_id='CURRENT')

def test_source_reviewed_refinement_versions_description_without_state_reset():
    from src.content_factory.novel_adaptation.handoff import refine_registry
    h,plan=fixture();before=deepcopy(h)
    proposals=[{'kind':'props','id':'bread','before_sha256':digest(h['registry']['props']['bread']),
        'description':'原文明确的一块面包','source_ids':['CH1-P001']}]
    review={'verdict':'accepted','proposals_sha256':digest(proposals),'source_sha256':digest(SOURCE),'handoff_sha256':digest(h)}
    refined=refine_registry(h,digest(h),proposals,SOURCE,review)
    assert h==before and refined['state']==h['state']
    assert refined['registry']['props']['bread']['description']=='原文明确的一块面包'
    assert refined['registry_revisions'][0]['parent_handoff_sha256']==digest(h)
    plan['props'][0]['description']='原文明确的一块面包'
    assert continue_state(refined,digest(refined),plan,ENT,book_id='book',episode_id='E02',timeline_id='CURRENT')['props']['bread']=='b'
    bad=deepcopy(proposals);bad[0]['owner']='a'
    bad_review={**review,'proposals_sha256':digest(bad)}
    with pytest.raises(ValueError,match='field_scope'):refine_registry(h,digest(h),bad,SOURCE,bad_review)
    with pytest.raises(ValueError,match='unreviewed'):
        refine_registry(h,digest(h),proposals,SOURCE,{**review,'verdict':'pass'})

def test_description_span_keeps_all_unselected_characters_and_checks_sha():
    from src.content_factory.novel_adaptation.handoff import description_span
    record={'id':'potatoes','description':'小半袋表皮发青、已长出短芽的土豆。'}
    result=description_span(record,digest(record),0,3,'大半袋')
    assert result=='大半袋'+record['description'][3:]
    assert record['description'].startswith('小半袋')
    with pytest.raises(ValueError,match='changed'):description_span(record,'stale',0,3,'大半袋')
    with pytest.raises(ValueError,match='invalid'):description_span(record,digest(record),-1,3,'大半袋')
