from copy import deepcopy
import pytest
from test_novel_adaptation_workflow import SOURCE,PACKET,Fake
from src.content_factory.novel_adaptation.workflow import run_workflow
from src.content_factory.novel_adaptation.reference_repair import checkpoint
from src.content_factory.corpus_screenplay_v1 import read


def test_compiled_prefix_is_replayed_without_regeneration_and_stale_state_rejected(tmp_path):
    original=tmp_path/'original';original.mkdir()
    candidate,_=run_workflow(original,Fake(),SOURCE,PACKET,{'scene_count':2})
    design=candidate['design'];previous=read(original/'INITIAL_STATE.json');checkpoints={}
    for scene in candidate['scenes']:
        checkpoints[scene['id']]={**checkpoint(scene,SOURCE,design,previous),'representation':'compiled'}
        previous=read(original/(scene['id']+'_END_STATE.json'))
    class ReviewOnly(Fake):
        def call(self,name,*args):
            assert name=='FINAL_REVIEW'
            return super().call(name,*args)
    resumed=tmp_path/'resumed';resumed.mkdir()
    result,_=run_workflow(resumed,ReviewOnly(),SOURCE,PACKET,{'scene_count':2,'typed_blocking':True},design_checkpoint=design,native_scene_checkpoints=checkpoints)
    assert result['scenes']==candidate['scenes'] and result['end_state']==candidate['end_state']
    bad=deepcopy(checkpoints);bad['s2']['previous_sha256']='stale'
    failed=tmp_path/'failed';failed.mkdir()
    with pytest.raises(ValueError,match='stale_native_checkpoint:previous_sha256'):
        run_workflow(failed,ReviewOnly(),SOURCE,PACKET,{'scene_count':2,'typed_blocking':True},design_checkpoint=design,native_scene_checkpoints=bad)
