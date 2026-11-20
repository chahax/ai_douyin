from copy import deepcopy
import pytest
from test_narrative_revision_contract import VALUE,SOURCE,PACKET,DESIGN
from src.content_factory.novel_adaptation.contracts import digest
from src.content_factory.novel_adaptation.narrative_presence import replay
from src.content_factory.novel_adaptation.uncertainty_review import identity
from src.content_factory.novel_adaptation.text_validation import verify


def fixture():
    c=deepcopy(VALUE);packet=deepcopy(PACKET);packet['source_sha256']=digest(SOURCE)
    p={'candidate_sha256':digest(c),'initial_locations':{'a':'room','b':'room'},
       'segments':[{'id':'B1','moves':[]}],'uncertainties':[]}
    plan={'places':[{'id':'room'}],'scenes':[{'id':'S1','place':'room'}],
          'initial_locations':{'a':'room','b':'room'},'props':[],'container_actions':True}
    e={'candidate_sha256':digest(c),'plan_sha256':digest(plan),
       'segments':[{'id':'B1','events':[],'action_order':[]}],'uncertainties':[]}
    b={'source':SOURCE,'candidate':c,'packet':packet,'design':DESIGN,'plan':plan,'presence':p,'projection':e,
       'run_plan':{'source_sha256':digest(SOURCE)},'state':{'status':'done','pending':None}}
    b['replay']=replay(c,p,['a','b'],['room'],prop_plan=plan,prop_projection=e)
    b['uncertainty_review']={'artifact_hashes':identity({k:b[k] for k in ('candidate','plan','presence','projection','replay')}),'dispositions':[]}
    return b


def test_green_structure_and_empty_notes_are_not_semantic_acceptance():
    result=verify(fixture())
    assert result['replayed_segments']==1
    assert result['blocking_reasons']==['same_version_semantic_review_missing']
    assert not result['semantic_acceptance'] and not result['media_ready']


def test_registry_notes_are_preserved_and_require_explicit_review():
    from src.content_factory.novel_adaptation.uncertainty_review import inventory
    b=fixture();b['replay']['registry_uncertainties']=['书的初始所有者尚不明确']
    artifacts={k:b[k] for k in ('candidate','plan','presence','projection','replay')}
    b['uncertainty_review']['artifact_hashes']=identity(artifacts)
    with pytest.raises(ValueError,match='uncertainty_coverage'):verify(b)
    note=inventory(artifacts)[0]
    b['uncertainty_review']['dispositions']=[{'id':note['id'],'decision':'open','reason':'需核对原文',
        'evidence':[{'artifact':'replay','path':'/registry_uncertainties/0',
                     'value_sha256':digest(note['text'])}]}]
    result=verify(b)
    assert 'open_uncertainties' in result['blocking_reasons']
    assert b['replay']['registry_uncertainties']==[note['text']]


def test_only_documented_replay_metadata_can_be_separated():
    b=fixture();b['replay']['unexpected_metadata']=[]
    with pytest.raises(ValueError,match='stored_replay_not_reproducible'):verify(b)


def test_registry_metadata_does_not_hide_state_corruption():
    b=fixture();b['replay']['registry_uncertainties']=[]
    b['replay']['end_state']['locations']['a']='elsewhere'
    with pytest.raises(ValueError,match='stored_replay_not_reproducible'):verify(b)


@pytest.mark.parametrize('case',['source','pending','replay','candidate','review'])
def test_mixed_or_unsettled_artifacts_never_validate(case):
    b=fixture();review=None
    if case=='source':b['packet']['source_sha256']='old'
    elif case=='pending':b['state']['pending']=1
    elif case=='replay':b['replay']['end_state']['locations']['a']='elsewhere'
    elif case=='candidate':b['candidate']['world_and_relationships']='different'
    else:review={'artifact_hashes':{}}
    with pytest.raises(ValueError):verify(b,semantic_review=review)


def test_six_green_labels_without_source_evidence_do_not_accept():
    from src.content_factory.novel_adaptation.text_validation import DIMENSIONS
    b=fixture();identity=verify(b)['artifact_hashes']
    review={'artifact_hashes':identity,'dimensions':{k:{'decision':'accepted','reason':'pass'} for k in DIMENSIONS}}
    with pytest.raises(ValueError,match='semantic_evidence_coverage'):verify(b,semantic_review=review)


def test_evidence_must_match_bound_values_not_just_existing_addresses():
    from src.content_factory.novel_adaptation.text_validation import DIMENSIONS,validate_semantic_review
    b=fixture();identity=verify(b)['artifact_hashes']
    paths={'source':'/chapters','candidate':'/scenes','packet':'/entities','design':'/scenes','projection':'/segments'}
    evidence=[{'artifact':k,'path':path,'value_sha256':'wrong'} for k,path in paths.items()]
    review={'artifact_hashes':identity,'dimensions':{k:{'decision':'accepted','reason':'reviewed',
            'evidence':deepcopy(evidence)} for k in DIMENSIONS}}
    with pytest.raises(ValueError,match='semantic_evidence_changed'):validate_semantic_review(b,review,identity)
