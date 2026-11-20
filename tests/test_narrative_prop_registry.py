import pytest
from scripts.project_narrative_props import validate_initial_containers


def sample():
    return {'props':[{'id':'food','owner':'kitchen','initial_status':'present'},
                     {'id':'pot','owner':'kitchen','initial_status':'present'}],
            'initial_containers':[{'child':'food','container':'pot'}]}


def test_existing_local_container_relation_allowed():
    validate_initial_containers(sample())


@pytest.mark.parametrize('side',[0,1])
@pytest.mark.parametrize('status',['planned','consumed'])
def test_future_or_gone_prop_cannot_be_initially_contained(side,status):
    r=sample();r['props'][side]['initial_status']=status
    with pytest.raises(ValueError,match='future_or_consumed_initial_containment'):
        validate_initial_containers(r)


def test_all_initial_errors_reported_without_rewriting_registry():
    from copy import deepcopy
    r=sample();r['props'][0].update(owner='child',initial_status='planned');before=deepcopy(r)
    with pytest.raises(ValueError) as caught:validate_initial_containers(r)
    assert 'future_or_consumed' in str(caught.value)
    assert 'owner_mismatch' in str(caught.value)
    assert r==before
