from copy import deepcopy
import pytest
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE
from src.content_factory.creative_original_prompt import VERSION as WRITER_VERSION
from src.content_factory.creative_review_v3 import CHECKS
from src.content_factory.reusable_production import read, write
from test_creative_model_profile import setup
from test_creative_event_script import as_events
from test_creative_workflow import FakeClients


def screenplay_review(script):
    coverage=[]
    for index, beat in enumerate(script['beats']):
        checks={}
        for name in CHECKS:
            na=name in ('assets','first_frame','dialogue_timing')
            checks[name]={'status':'not_applicable' if na else 'pass','reason':'离线fixture：无对白或尚无资产' if na else '离线fixture：引用本拍正文，不代表真实内容审核', 'evidence_refs':[] if na else [{'path':f'script.beats.{index}.before','quote':beat['before']}], 'issue_ids':[]}
        coverage.append({'id':beat['id'],'checks':checks})
    return dict(story_preserved=True,issues=[],suggestions=[],calibration_focus=[],coverage=coverage)


def test_v4_routes_new_workflow_and_keeps_real_review_gate(tmp_path):
    answers,bundle=setup(tmp_path)
    bundle.metadata['creative_brief']['duration_seconds']=[20,20]
    clients=FakeClients([answers[0],answers[1],as_events(answers[2]),screenplay_review(answers[2])])
    root=tmp_path/'run'
    state=CreativeWorkflow(root,clients=clients,model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=WRITER_VERSION,review_policy_version='evidence_review_v4').run(bundle)
    assert state['status']=='script_review_pending'
    assert state['segmented_director_binding']['version']=='reviewed_beat_storyboard_v3'
    record=read(root/'script_review__story_00_00.json')
    from src.content_factory.creative_review_v4 import build_review_prompt
    import json
    context=json.loads(record['request']['messages'][1]['content'])
    from src.content_factory.creative_narrative_focus import prompt_for_stage
    assert record['request']['messages'][0]['content']==build_review_prompt(context)+prompt_for_stage(state['narrative_focus_binding'],'script_review__story_00_00')
    before=(root/'script_review__story_00_00.json').read_bytes()
    restored=CreativeWorkflow(root,clients=FakeClients([])).run(bundle)
    assert restored['calls_started']==state['calls_started']
    assert (root/'script_review__story_00_00.json').read_bytes()==before
    assert not list(root.glob('director_shots*'))
    assert not (root/'MEDIA_HANDOFF.json').exists()


def test_old_run_cannot_be_silently_migrated_or_reset(tmp_path):
    write(tmp_path/'state.json',dict(model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=WRITER_VERSION,review_policy_version='evidence_review_v3'))
    assert CreativeWorkflow(tmp_path).review_policy_version=='evidence_review_v3'
    with pytest.raises(RuntimeError,match='审核流程版本'):
        CreativeWorkflow(tmp_path,review_policy_version='evidence_review_v4')
