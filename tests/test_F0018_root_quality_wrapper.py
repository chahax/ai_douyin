"""CPU root-quality layer contracts. Fake delegate is not a VLM acceptance."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

PATH=Path(__file__).resolve().parents[1]/'data/video_generation/novel_5min_20261106_v1/review_F0018_with_root_quality.py'
spec=importlib.util.spec_from_file_location('F0018_root_quality_cpu_only',PATH)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def case():
    _,proof=m.verify_root_proof();frame=proof['frame'];crops=frame['static_start']['identity_crops']
    characters=[dict(id=c['source_identity']['entity_id'],path=c['source_path']) for c in crops]
    checks=dict(identity=True,view=True,clothing=True,anatomy=True,layout=True)
    def result(reference=None):return dict(decision='accepted',target_sha256=m.REJECTED_SHA,reference_sha256=reference,
        checks=deepcopy(checks),completion_known=True,outcome_unknown=False,retryable=False,issues=[])
    raw=result();raw['primary_checks_before_inventory']=dict(layout=True)
    raw['subreviews']=[result(c['source_identity']['sha256']) for c in crops]+[result('f'*64)]
    return dict(image=Path(frame['path']),characters=characters,raw=raw)


class FakeDelegate:
    def __init__(self,raw):self.raw=raw;self.calls=0
    def review_composition(self,target,characters,place,expectation=None,evidence_dir=None,*,resume=False):
        self.calls+=1
        if evidence_dir:
            m.assets.write(Path(evidence_dir)/'COMPOSITION_REVIEW.json',self.raw)
            m.assets.write(Path(evidence_dir)/'RESULTS.json',dict(fixture_raw=True,results=self.raw['subreviews']))
            m.assets.write(Path(evidence_dir)/'NATIVE.json',dict(fixture_only=True,original='untouched'))
        return self.raw
    def other_method(self,value):return ('delegated',value)


def invoke(reviewer,case,folder):
    return reviewer.review_composition(case['image'],case['characters'],dict(id='qa_room',path=str(case['image'])),evidence_dir=folder)


def test_exact_rejected_sha_and_child_get_explicit_root_downgrade(case,tmp_path):
    delegate=FakeDelegate(case['raw']);reviewer=m.ConservativeRootReviewer(delegate)
    result=invoke(reviewer,case,tmp_path)
    assert result['decision']=='repair_required' and result['checks']['identity'] is False
    assert result['model_decision_before_root']=='accepted'
    assert result['root_quality_adjustment']['proof']['sha256']==m.ROOT_PROOF_SHA
    assert result['root_quality_adjustment']['not_a_model_verdict'] is True
    assert result['root_quality_adjustment']['child_subreview_indices']==[1]
    child=result['subreviews'][1]
    assert child['decision']=='repair_required' and child['checks']['identity'] is False
    assert child['root_quality_adjustment']['component']=='child_ye_xijue'
    assert 'six-year-old' in result['root_quality_adjustment']['positive_repair_requirements']


def test_root_source_proof_tamper_blocks_before_delegate(case,tmp_path):
    copied=tmp_path/'ROOT_PROOF.json';copied.write_bytes(m.ROOT_PROOF.read_bytes())
    delegate=FakeDelegate(case['raw']);reviewer=m.ConservativeRootReviewer(delegate,proof_binding=dict(path=str(copied),sha256=m.ROOT_PROOF_SHA))
    copied.write_text('{}',encoding='utf-8')
    with pytest.raises(m.RootQualityBlocked,match='proof_changed'):invoke(reviewer,case,tmp_path/'evidence')
    assert delegate.calls==0


def test_unknown_top_or_child_is_never_converted_to_a_known_root_repair(case,tmp_path):
    for kind in ('top','child'):
        raw=deepcopy(case['raw']);unknown=raw if kind=='top' else raw['subreviews'][1]
        unknown.update(decision='unavailable',completion_known=False,outcome_unknown=True)
        before=deepcopy(raw);delegate=FakeDelegate(raw);reviewer=m.ConservativeRootReviewer(delegate)
        with pytest.raises(m.RootQualityBlocked,match='outcome_unknown_preserved'):invoke(reviewer,case,tmp_path/kind)
        assert raw==before and 'root_quality_adjustment' not in raw
        assert m.assets.read(tmp_path/kind/'COMPOSITION_REVIEW.json')==before


def test_primary_false_and_all_other_null_or_false_checks_remain(case,tmp_path):
    raw=case['raw'];raw['decision']='needs_review';raw['checks'].update(layout=False,clothing=None)
    raw['primary_checks_before_inventory']['layout']=False;raw['subreviews'][1]['checks'].update(view=False,clothing=None)
    before=deepcopy(raw);result=invoke(m.ConservativeRootReviewer(FakeDelegate(raw)),case,tmp_path)
    assert result['checks']['layout'] is False and result['checks']['clothing'] is None
    assert result['primary_checks_before_inventory']==dict(layout=False)
    assert result['model_checks_before_root']==before['checks']
    assert result['subreviews'][1]['checks']['view'] is False and result['subreviews'][1]['checks']['clothing'] is None


def test_other_sha_and_other_methods_are_unchanged(case,tmp_path):
    image=tmp_path/'other.fixture';image.write_bytes(b'A different image fixture, not the root-rejected SHA')
    raw=deepcopy(case['raw']);raw['target_sha256']=m.sha(image);before=deepcopy(raw)
    delegate=FakeDelegate(raw);reviewer=m.ConservativeRootReviewer(delegate)
    output=reviewer.review_composition(image,case['characters'],dict(id='qa'),evidence_dir=tmp_path/'other')
    assert output is raw and output==before and 'root_quality_adjustment' not in output
    assert reviewer.other_method('value')==('delegated','value')


def test_original_dict_and_native_composition_files_are_not_modified(case,tmp_path):
    raw=case['raw'];before=deepcopy(raw);delegate=FakeDelegate(raw)
    result=invoke(m.ConservativeRootReviewer(delegate),case,tmp_path)
    assert raw==before and result is not raw
    assert m.assets.read(tmp_path/'COMPOSITION_REVIEW.json')==before
    assert m.assets.read(tmp_path/'RESULTS.json')==dict(fixture_raw=True,results=before['subreviews'])
    assert m.assets.read(tmp_path/'NATIVE.json')==dict(fixture_only=True,original='untouched')
    originals=list(tmp_path.glob('root_quality/*/MODEL_RESULT_BEFORE_ROOT.json'))
    adjusted=list(tmp_path.glob('root_quality/*/ROOT_QUALITY_ADJUSTED_RESULT.json'))
    assert len(originals)==len(adjusted)==1 and m.assets.read(originals[0])==before and m.assets.read(adjusted[0])==result
