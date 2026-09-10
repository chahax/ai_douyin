"""Reviewer coverage hints are actual IDs/types, never model evidence or approval."""
import copy

from script_pair_fixture import pair_payload
from test_script_pair import parse
from src.trend_intelligence.script_pair import build_script_review_rows, _review_structural_facts


def rows():
    return build_script_review_rows(parse(pair_payload()))


def silence(shot):
    shot.update(dialogue='', dialogue_speaker='', dialogue_mode='none')


def test_visible_silent_character_uses_participants_not_speech_and_has_no_report_text():
    scripts = rows()
    short = scripts[0]
    silent = {**short['characters'][0], 'name': '见证人', 'identity': '在场同事'}
    short['characters'].append(silent)
    for shot in short['shots']:
        shot['participants'].append('见证人')
    original = copy.deepcopy(scripts)
    coverage = _review_structural_facts(scripts)['required_audit_coverage']
    character = coverage['short']['characters'][1]
    assert character == {'character_name': '见证人', 'spoken_shot_ids': [],
                         'first_last_visible_shot_ids': ['S01', 'S06']}
    assert coverage['short']['shot_ids'] == [f'S{i:02d}' for i in range(1, 7)]
    assert scripts == original
    def check(value):
        if isinstance(value, dict):
            assert not set(value) & {'quote', 'decision', 'passed', 'status', 'finding', 'assessment'}
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(coverage)


def test_long_speaker_coverage_keeps_middle_s11_and_actual_order():
    scripts = rows()
    long = scripts[1]
    for shot in long['shots']:
        if shot['shot_id'] not in ('S01', 'S05', 'S11', 'S12'):
            silence(shot)
    original = copy.deepcopy(scripts)
    coverage = _review_structural_facts(scripts)['required_audit_coverage']['long']
    assert coverage['characters'][0]['spoken_shot_ids'] == ['S01', 'S05', 'S11', 'S12']
    assert coverage['characters'][0]['first_last_visible_shot_ids'] == ['S01', 'S12']
    assert coverage['shot_ids'] == [f'S{i:02d}' for i in range(1, 13)]
    assert scripts == original


def test_silent_conflict_stage_requires_action_only_without_inventing_dialogue():
    scripts = rows()
    long = scripts[1]
    for shot in long['shots'][:2]:
        silence(shot)
    original = copy.deepcopy(scripts)
    facts = _review_structural_facts(scripts)
    groups = facts['required_audit_coverage']['long']['conflict_groups']
    assert groups['opening'] == {'allowed_shot_ids': ['S01', 'S02'], 'required_evidence_fields': ['action']}
    assert groups['dispute'] == {'allowed_shot_ids': ['S03', 'S04', 'S05', 'S06'],
                                 'required_evidence_fields': ['action', 'dialogue']}
    assert facts['verification'] == 'recomputed_from_current_review_scripts_not_inherited_approval'
    assert scripts == original
