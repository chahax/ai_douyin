import pytest
from src.content_factory.novel_adaptation.scenes import advance_knowledge
from src.content_factory.novel_adaptation.contracts import ContractError

AUDIO=[{'kind':'inner','speaker':'su','text':'我是穿书来的。'},
       {'kind':'narration','speaker':'NARRATOR','text':'他想给孩子找师父。'},
       {'kind':'dialogue','speaker':'su','text':'下次不要了。'}]

@pytest.mark.parametrize('index',[0,1])
def test_other_character_cannot_hear_inner_or_narration(index):
    with pytest.raises(ContractError,match='private_or_missing'):
        advance_knowledge({},[{'person':'child','fact_id':'origin','channel':'heard_dialogue','audio_index':index}],
                          {'su','child'},AUDIO,{'origin'})

def test_knowledge_accumulates_without_changing_prior_and_absent_actor_cannot_learn():
    old={'child':['old']}
    change={'person':'child','fact_id':'new','channel':'heard_dialogue','audio_index':2}
    assert advance_knowledge(old,[change],{'su','child'},AUDIO,{'new'})=={'child':['old','new']}
    assert old=={'child':['old']}
    with pytest.raises(ContractError,match='absent'):
        advance_knowledge(old,[change],{'su'},AUDIO,{'new'})


def test_audible_history_records_access_not_narrator_knowledge():
    from src.content_factory.novel_adaptation.scenes import audible_information
    result=audible_information({},'scene1',{'id':'b1','audio':AUDIO},{'su','child'})
    assert [r['id'] for r in result['child']]==['scene1:b1:a2']
    assert [r['id'] for r in result['su']]==['scene1:b1:a0','scene1:b1:a2']
    assert 'NARRATOR' not in result
