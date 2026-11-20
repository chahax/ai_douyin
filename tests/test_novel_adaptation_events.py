import pytest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.events import validate_requirements,require_review

CONTRACT={'events':[{'id':'leave','kind':'leave','scene_id':'s1','people':['child'],'place':'room','source_ids':['CH1-P001']},
 {'id':'bread','kind':'transfer','scene_id':'s1','prop':'bread','origin':'child','destination':'dad','source_ids':['CH1-P001']}]}

def test_internally_consistent_states_cannot_replace_required_source_events():
    draft={'scenes':[{'id':'s1','beats':[{'id':'b','action':'孩子停在门口，面包仍握在手里。'}]}]}
    with pytest.raises(c.ContractError) as exc:validate_requirements(draft,CONTRACT)
    assert {x.code for x in exc.value.issues}=={'required_leave_missing','required_transfer_not_once'}
    draft['scenes'][0]['beats'][0].update(moves=[{'person':'child','origin':'room','destination':'hall'}],
       transfers=[{'prop':'bread','origin':'child','destination':'dad'}])
    assert validate_requirements(draft,CONTRACT)

def test_event_contract_must_be_bound_to_independently_reviewed_source():
    source={'text':'孩子跑了出去'}
    good={'verdict':'accepted','source_sha256':c.digest(source),'contract_sha256':c.digest(CONTRACT)}
    require_review(CONTRACT,source,good)
    with pytest.raises(ValueError):require_review(CONTRACT,{'text':'孩子没有出去'},good)
