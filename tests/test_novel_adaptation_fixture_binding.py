from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.fixture_binding import apply
from src.content_factory.novel_adaptation.contracts import digest


def test_binding_only_replaces_reviewed_references():
    d={'props':[]};n={'s':{'beats':[{'id':'b','audio':[{'text':'keep'}],
        'blocking':[{'kind':'gesture','target':'kitchen'},{'kind':'gesture','target':'actor'}],
        'shot':{'subjects':['kitchen','actor']}}]}}
    scope={'design_sha256':digest(d),'scenes_sha256':digest(n),'fixture_id':'door','visible_from':['kitchen','hall'],
        'references':{'r':{'scene_id':'s','beat_id':'b','field':'blocking','index':0,'before':'kitchen'}}}
    proposal={'verdict':'supported','fixture':{'id':'door','stationary':True,'visible_from':['hall','kitchen']},'reference_ids':['r']}
    old=deepcopy(n);design,result=apply(d,n,proposal,scope)
    expected=deepcopy(n);expected['s']['beats'][0]['blocking'][0]['target']='door'
    assert n==old and result==expected and d=={'props':[]}
    proposal['reference_ids']=[]
    with pytest.raises(ValueError,match='coverage'):apply(d,n,proposal,scope)
