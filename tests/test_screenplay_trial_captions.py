import json
import pytest
from scripts import render_clean_script_captions as captions
from scripts import run_screenplay_trial as trial


def test_trial_caption_dialogue_must_match_reviewed_story(tmp_path, monkeypatch):
    story = {'version': {'shots': [{'shot_id': 'S02', 'dialogue': '先核清楚。'}]}}
    plan = tmp_path / 'trial_plan.json'
    plan.write_text(json.dumps({'bindings': {'story': {'sha256': 'story-sha'}}}))
    manifest = {'trial_schema': 'reviewed_screenplay_segment/v1',
                'trial_plan_sha256': captions.sha(plan), 'script_sha256': 'story-sha'}
    monkeypatch.setattr(trial, 'verify_inputs', lambda p: (story, {}, 'reviewed prompt'))
    assert captions.caption_shots(tmp_path, manifest, story) == story['version']['shots']
    with pytest.raises(ValueError, match='differs'):
        captions.caption_shots(tmp_path, manifest, {'version': {'shots': []}})
    plan.write_text('{}')
    with pytest.raises(ValueError, match='plan changed'):
        captions.caption_shots(tmp_path, manifest, story)
