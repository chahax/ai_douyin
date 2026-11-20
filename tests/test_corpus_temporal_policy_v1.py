"""Temporal interpretation is semantic; repaired prompts must reach real ledger calls."""
import json
from types import SimpleNamespace

from src.content_factory import corpus_chapter_materials_v6 as material
from src.content_factory import corpus_temporal_policy_v1 as policy
from src.content_factory import corpus_production_v8 as p
from tests.test_corpus_production_v8 import configured, prepared
from tests.test_corpus_production_v6 import Classifier


def test_temporal_mislabel_has_downstream_effect_but_is_not_a_source_error():
    # Both are legal enums: a source/string validator cannot decide what was told.
    assert material.state_application('actual','earlier') == 'blocked_noncurrent_modality_or_time'
    assert material.state_application('actual','chapter_present') == 'candidate_requires_review'
    assert material.state_application('plan','later') == 'blocked_noncurrent_modality_or_time'
    assert material.policy()['validation_is_semantic_approval'] is False


def test_initial_and_protocol_repair_both_receive_same_temporal_contract(tmp_path, configured):
    run,plan=prepared(tmp_path)
    good=Classifier()
    class OnceInvalid:
        def __init__(self):self.calls=[]
        def call(self,role,messages,**kwargs):
            self.calls.append(messages)
            if len(self.calls)==1:
                return SimpleNamespace(text='{}',metadata={'prompt_tokens':10,'completion_tokens':10,'total_tokens':20,'finish_reason':'stop'},response_payload={'fixture':True})
            return good.call(role,messages,**kwargs)
    client=OnceInvalid()
    assert p.execute_materials(run,client)['status']=='materials_ready'
    assert len(client.calls)==4
    for messages in client.calls:
        assert policy.RULES in messages[0]['content']
        payload=json.loads(messages[-1]['content'])
        fields=payload['output_schema']['properties']['facts']['items']['properties']
        assert set(fields)==set(material.FACT_KEYS)
        assert 'statement' in fields['event_time']['description']
    assert 'validation_error' in json.loads(client.calls[1][-1]['content'])
    assert plan['temporal_policy_version']==policy.VERSION


def test_schema_annotations_do_not_mutate_shared_definition(tmp_path, configured):
    run,plan=prepared(tmp_path)
    source=p.read(run/'SOURCE.json')
    cp=plan['chapters'][0]
    payload=material.chapter_payload(source['chapters'],cp)
    original=material.chapter_schema(cp,payload)
    frozen=json.dumps(original,sort_keys=True)
    annotated=policy.extraction_schema(original)
    assert json.dumps(original,sort_keys=True)==frozen
    assert annotated['properties']['facts']['items']['properties']['modality']['enum']==original['properties']['facts']['items']['properties']['modality']['enum']


def test_material_stage_restrictions_do_not_leak_into_snapshot_or_screenplay():
    prompt=policy.downstream_prompt('current stage schema')
    assert policy.RULES not in prompt and policy.REVIEW_RULES not in prompt
    assert '本集快照阶段需要完整状态和动作链' in prompt
