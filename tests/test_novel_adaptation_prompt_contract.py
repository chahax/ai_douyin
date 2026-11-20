from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.workflow import run_workflow
from src.content_factory.novel_adaptation.scenes import compile_design
from test_novel_adaptation_workflow import SOURCE,PACKET,DESIGN


def test_enabled_unpack_is_not_forbidden_by_the_actual_scene_prompt(tmp_path):
    design=deepcopy(DESIGN);design['container_actions']=True
    design=compile_design(design,PACKET)
    class Captured(Exception):pass
    class Ledger:
        def call(self,name,role,prompt,payload,schema):
            variants=schema['properties']['beats']['items']['properties']['blocking']['items']['oneOf']
            assert any(v['properties']['kind']['enum']==['unpack'] for v in variants)
            assert '不支持取出' not in prompt and '显式unpack之后' in prompt
            raise Captured()
    with pytest.raises(Captured):
        run_workflow(tmp_path,Ledger(),SOURCE,PACKET,{'scene_count':2,'typed_blocking':True},design_checkpoint=design)
