from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.handoff import inherit_design,opening_delta_schema,bind_opening_delta,export_handoff,continue_state
from src.content_factory.novel_adaptation.workflow import run_workflow
from src.content_factory.novel_adaptation import contracts as c
from test_novel_adaptation_workflow import DESIGN,SOURCE,PACKET,ENT,Fake


def fixture():
    candidate={'design':deepcopy(DESIGN),'end_state':{'locations':deepcopy(DESIGN['initial_locations']),
        'props':{'bread':'a'}}}
    candidate['design']['visual_design']=[{'aspect':'style','description':'fixed style','basis':'adaptation_design'}]
    review={'verdict':'accepted','candidate_sha256':c.digest(candidate),'source_sha256':c.digest(SOURCE)}
    return export_handoff(candidate,{'entities':ENT},SOURCE,review,book_id='book',episode_id='one',timeline_id='now')


def test_inherited_registry_is_copied_only_new_opening_values_are_authored():
    h=fixture();old=deepcopy(h)
    raw={'places':[{'id':'kitchen','description':'new room','basis':'adaptation_design'}],
         'props':[{'id':'knife','kind':'knife','description':'small knife'}],'scenes':deepcopy(DESIGN['scenes']),
         'visual_design':[]}
    design=inherit_design(raw,h)
    assert h==old and design['visual_design']==h['visual_design']
    schema=opening_delta_schema(design,{'entities':ENT},h)
    assert schema['properties']['locations']['properties']=={}
    assert set(schema['properties']['owners']['properties'])=={'knife'}
    bound=bind_opening_delta(design,{'entities':ENT},h,{'locations':{},'owners':{'knife':'kitchen'}})
    assert bound['initial_locations']==h['state']['locations']
    assert next(x for x in bound['props'] if x['id']=='bread')['owner']=='a'
    with pytest.raises(c.ContractError):bind_opening_delta(design,{'entities':ENT},h,{'locations':{},'owners':{'knife':'kitchen','bread':'b'}})


@pytest.mark.parametrize('kind',['places','props'])
def test_even_identical_old_asset_cannot_be_redefined(kind):
    h=fixture();raw={'places':[],'props':[],'visual_design':[]}
    raw[kind]=[deepcopy(next(iter(h['registry'][kind].values())))]
    with pytest.raises(ValueError,match='redefinition'):inherit_design(raw,h)


def test_fresh_continuation_workflow_inherits_without_requesting_old_state(tmp_path):
    h=fixture()
    class Continued(Fake):
        def call(self,name,role,prompt,payload,schema):
            if name=='DESIGN':
                self.calls.append((name,deepcopy(payload)))
                raw=deepcopy(DESIGN);raw.pop('initial_locations');raw['places']=[];raw['props']=[]
                return raw
            if name=='OPENING_STATE':
                self.calls.append((name,deepcopy(payload)))
                assert schema['properties']['locations']['properties']=={}
                assert schema['properties']['owners']['properties']=={}
                return {'locations':{},'owners':{}}
            return super().call(name,role,prompt,payload,schema)
    fake=Continued()
    result,_=run_workflow(tmp_path,fake,SOURCE,PACKET,{'scene_count':2,'book_id':'book','episode_id':'two','timeline_id':'now','handoff_sha256':c.digest(h)},continuation=h)
    assert fake.calls[0][1]['previous_episode']['registry']==h['registry']
    assert result['design']['visual_design']==h['visual_design']
    assert result['end_state']['props']['bread']=='b'


def test_design_only_never_generates_scenes_or_claims_event_gate_pass(tmp_path):
    fake=Fake()
    result,review=run_workflow(tmp_path,fake,SOURCE,PACKET,{'scene_count':2,'require_source_events':True},design_only=True)
    assert [name for name,_ in fake.calls]==['DESIGN','OPENING_STATE']
    assert review is None and result['source_event_gate']=='not_executed'
    assert result['scene_generation_executed'] is False
    assert not (tmp_path/'EPISODE.json').exists()


def test_legacy_handoff_implicit_present_cannot_become_planned():
    h=fixture();design=deepcopy(DESIGN);design['planned_props']=['bread']
    with pytest.raises(ValueError,match='lifecycle_reset'):
        continue_state(h,c.digest(h),design,{'entities':ENT},book_id='book',episode_id='two',timeline_id='now')
