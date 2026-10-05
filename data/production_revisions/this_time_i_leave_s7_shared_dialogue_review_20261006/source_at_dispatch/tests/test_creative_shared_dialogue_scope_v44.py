from copy import deepcopy
import json,re,pytest
from scripts import run_creative_s7_full_review_wire_v43 as old
from scripts import creative_review_projection_v12 as view
from scripts import creative_joint_source_binding_v13 as joint
from scripts import creative_review_id_transport_v19 as ids
from jsonschema import Draft202012Validator

@pytest.fixture(scope="module")
def ctx():
    c,compiled=old.final_context(1);c['shots']=view.project_storyboard(c['shots'],c)
    return c

def test_shared_whole_paragraph_once_and_windows_preserved(ctx):
    paragraph=ctx['state_plan']['beats'][4]['dialogue_performance'];text=ctx['shots']['shots'][4]['visible_performance']
    assert text.count(paragraph)==1 and text.count('本窗口仅对应上述原句')==2
    proof=joint.preflight(ctx);assert len(proof['mapping'])==10

def test_schema_real_ten_shots_and_exact_compressed_id_membership(ctx):
    schema=ids.schema(ctx);Draft202012Validator.check_schema(schema);catalog=ids.catalog(ctx)
    assert len(schema['properties']['coverage']['prefixItems'])==10
    pattern=schema['$defs']['EvidenceID']['pattern'];assert all(re.fullmatch(pattern,k) for k in catalog)
    assert not re.fullmatch(pattern,next(iter(catalog)).rsplit('-',1)[0]+'-9999')
    sets=[d['pattern'] for n,d in schema['$defs'].items() if n.startswith('SourceSet')]
    assert sets and len(json.dumps(schema))<150000

def test_allows_exact_set_and_no_extras():
    names=['Eabc-0001','Eabc-0002','Eabc-0010','Eabc-0100'];pattern=ids.id_pattern(names)
    assert {f'Eabc-{i:04}' for i in range(10000) if re.fullmatch(pattern,f'Eabc-{i:04}')}==set(names)

def test_source_change_still_rejected(ctx):
    bad=deepcopy(ctx);bad['raw_linear_script']['title']+=' changed'
    with pytest.raises(joint.JointSourceBindingError):ids.schema(bad)
