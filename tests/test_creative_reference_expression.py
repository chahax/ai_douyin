from copy import deepcopy
from pathlib import Path
import json
import pytest
from scripts.run_creative_workflow import parser, _resolve_reference_paths
from src.content_factory.creative_reference_expression import bind_reference_expression, enrich_reference_context
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE
from src.content_factory.creative_original_prompt import bind_original_prompt
from src.content_factory.creative_full_script_revision import bind_full_script_revision
from tests.test_creative_full_script_revision import script_fixture
from tests.test_creative_event_script import as_events
from tests.test_creative_workflow import FakeClients


def args(tmp_path):
    return parser().parse_args(['--source-driver','original','--title','test','--run-dir',str(tmp_path)])


def test_new_default_and_exact_legacy_resume_reference_selection(tmp_path):
    value=args(tmp_path)
    defaults=_resolve_reference_paths(value)
    assert len(defaults)==1 and defaults[0].is_file()
    assert '刺激与反应' in defaults[0].read_text(encoding='utf-8') or '触发' in defaults[0].read_text(encoding='utf-8')
    (tmp_path/'state.json').write_text('{}',encoding='utf-8')
    (tmp_path/'materials.json').write_text(json.dumps({'files':{}}),encoding='utf-8')
    assert _resolve_reference_paths(value)==[]
    (tmp_path/'materials.json').write_text(json.dumps({'files':{'reference_1':{'path':'old.md'}}}),encoding='utf-8')
    assert _resolve_reference_paths(value)==[Path('old.md')]
    value.reference=[Path('explicit.md')]
    assert _resolve_reference_paths(value)==[Path('explicit.md')]


def test_bound_references_reach_complete_model_revision_and_full_review(tmp_path):
    script,candidate,bundle=script_fixture(tmp_path)
    refs=[{'id':'R01','path':'fixture.md','text':'具体刺激改变人物选择；反应镜头承担新增信息。'}]
    w=CreativeWorkflow(tmp_path/'run',clients=FakeClients([as_events(script),{'ok':True}]),model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version='original_events_v3')
    w.run_dir.mkdir()
    w.state={'calls_started':0,'contract_repairs_used':0,'revision_rounds':0,'stages':[],
        'writer_prompt_binding':bind_original_prompt({'schema':'creative_brief/v1','theme':'关系变化'}),
        'script_revision_binding':bind_full_script_revision(),
        'reference_expression_binding':bind_reference_expression(refs)}
    revised=w._stage('writer_revise__01','writer',{'previous_script':script,'affected_beat_ids':[script['beats'][0]['id']]},lambda x:None)
    w._stage('script_review__01','director',{'script':revised},lambda x:None)
    for name in ['writer_revise__01','script_review__01']:
        record=json.loads((w.run_dir/(name+'.json')).read_text(encoding='utf-8'))
        payload=json.loads(record['request']['messages'][-1]['content'])
        assert payload['reference_pack']==refs
        assert '不照搬' in payload['reference_expression_rule']
    assert w.state['reference_expression_binding']['reference_pack']==refs


def test_existing_materials_not_duplicated_and_conflicts_cannot_silently_replace_reference():
    pack=[{'id':'R01','text':'选择相关的表达机制'}];binding=bind_reference_expression(pack)
    payload={'materials':{'reference_pack':deepcopy(pack)}}
    result=enrich_reference_context(binding,'writer_script',payload)
    assert 'reference_pack' not in result and result['materials']==payload['materials']
    with pytest.raises(CreativeContractError,match='不一致'):
        enrich_reference_context(binding,'writer_revise',{'reference_pack':[]})
    assert enrich_reference_context(None,'writer_revise',payload)==payload
