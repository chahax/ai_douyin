from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.cooking_assets import validate_proposal

DESIGN={'props':[{'id':'food'},{'id':'meal'}],'recipes':[{'id':'cook','inputs':['food'],'outputs':['meal'],'retained_inputs':[]}]}
PROPOSAL={'new_props':[{'id':'pan'}],'bindings':[{'recipe':'cook','input_prop':'food','vessel':'pan'}],
          'existing_display_names':[],'action_requirements':[{'target':'pan','instrument':''}]}


def test_valid_distinct_processing_vessel():validate_proposal(PROPOSAL,DESIGN)


def test_retained_input_still_cannot_contain_itself():
    p=deepcopy(PROPOSAL);d=deepcopy(DESIGN)
    d['recipes'][0]['retained_inputs']=['food'];p['bindings'][0]['vessel']='food'
    with pytest.raises(ValueError,match='self_containment'):validate_proposal(p,d)


def test_selection_reuses_exact_native_rows_without_accepting_other_bindings():
    from src.content_factory.novel_adaptation.cooking_assets import apply_reviewed_selection
    from src.content_factory.novel_adaptation.contracts import digest
    p=deepcopy(PROPOSAL);p['bindings'].append({'recipe':'cook','input_prop':'food','vessel':'meal'})
    source={'text':'test'}
    review={'verdict':'accepted_selection','proposal_sha256':digest(p),'design_sha256':digest(DESIGN),'source_sha256':digest(source),
            'selection':{'new_prop_ids':['pan'],'bindings':[['cook','food']]}}
    # Ambiguous duplicate keys cannot be silently selected.
    with pytest.raises(ValueError,match='missing_or_duplicate'):apply_reviewed_selection(p,DESIGN,source,review)
    p['bindings'].pop();review['proposal_sha256']=digest(p)
    out,selected=apply_reviewed_selection(p,DESIGN,source,review)
    assert selected['new_props']==p['new_props'] and selected['bindings']==p['bindings']
    assert out['recipes'][0]['input_containers']=={'food':'pan'} and 'input_containers' not in DESIGN['recipes'][0]
    review['source_sha256']='stale'
    with pytest.raises(ValueError,match='stale'):apply_reviewed_selection(p,DESIGN,source,review)


@pytest.mark.parametrize('case', ['collision','output_vessel','unknown_vessel','duplicate_binding','bad_input','bad_tool'])
def test_invalid_asset_relations_rejected(case):
    p=deepcopy(PROPOSAL)
    if case=='collision':p['new_props'][0]['id']='food'
    elif case=='output_vessel':p['bindings'][0]['vessel']='meal'
    elif case=='unknown_vessel':p['bindings'][0]['vessel']='missing'
    elif case=='duplicate_binding':p['bindings']*=2
    elif case=='bad_input':p['bindings'][0]['input_prop']='meal'
    else:p['action_requirements'][0]['instrument']='missing'
    with pytest.raises(ValueError):validate_proposal(p,DESIGN)
