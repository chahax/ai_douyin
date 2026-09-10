"""Synthetic bundle bindings and final-workflow routing; never call a model."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_script_screenplay import screenplay, production, production_v2, sources
from src.trend_intelligence import screenplay_bundle as bundle_module
from src.trend_intelligence import script_pair
from src.trend_intelligence.script_screenplay import STORY_REVIEW_CHECKS
from story_review_fixture import enrich_story_review


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    path.write_bytes(raw)
    return digest(raw)


def reviewed_sources():
    result = []
    for i in range(1, 21):
        source = copy.deepcopy(sources()[0])
        source['source_id'] = f'douyin:{i}'
        artifact, media = digest(f'artifact {i}'.encode()), digest(f'video {i}'.encode())
        source['independent_review'] = {'decision': 'passed_with_limits', 'blocked_for_script_generation': False,
                                        'review_sha256': digest(f'review {i}'.encode()),
                                        'artifact_sha256': artifact, 'source_video_sha256': media}
        source['media_evidence'].update(source_video_sha256=media, visual={'artifact_sha256': artifact})
        result.append(source)
    return result


def review(story, *, story_sha, workflow_sha, source_sha):
    shots = story['version']['shots']
    return enrich_story_review({'schema': 'screenplay_editorial_review/v1', 'decision': 'passed',
            'candidate_sha256': story_sha, 'workflow_request_sha256': workflow_sha,
            'source_evidence_sha256': source_sha, 'unresolved_issues': [],
            'checks': {key: True for key in STORY_REVIEW_CHECKS},
            'shot_reviews': [{'shot_id': shot['shot_id'], 'action_quote': shot['action'],
                              'decision': 'passed', 'finding': 'Synthetic protocol fixture only.'}
                             for shot in shots],
            'result_review': {'shot_id': shots[-1]['shot_id'], 'action_quote': shots[-1]['action'],
                              'decision': 'passed', 'finding': 'Synthetic result binding only.'}}, story)


@pytest.fixture
def packet(tmp_path):
    root = tmp_path / 'project'
    base = root / 'data/pre_video_scripts/_runs/original'
    full_sources = reviewed_sources()
    source_path = base / 'source_evidence.full.json'
    source_sha = write(source_path, full_sources)
    positioning = {'domain': 'legal_services', 'service_scope': ['合同'], 'audiences': ['消费者'], 'domain_config': {}}
    payload = {'account_positioning': positioning, 'short_seconds': 45, 'long_seconds': 180,
               'source_evidence': full_sources, 'expression_patterns': {}}
    workflow = [{'role': 'system', 'content': 'Synthetic original workflow prompt.'},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    workflow_path = base / 'request.json'
    workflow_sha = write(workflow_path, workflow)
    data = {'schema': bundle_module.SCHEMA, 'workflow_request_path': str(workflow_path),
            'workflow_request_sha256': workflow_sha, 'source_evidence_path': str(source_path),
            'source_evidence_sha256': source_sha, 'reference_source_ids': ['douyin:1']}
    for kind in ('short', 'long'):
        story = screenplay(kind)
        stage_dir = root / 'data/stages' / kind
        story_path, review_path, production_path = [stage_dir / name for name in
                                                   ('screenplay.json', 'review.json', 'production.json')]
        story_sha = write(story_path, story)
        report = review(story, story_sha=story_sha, workflow_sha=workflow_sha, source_sha=source_sha)
        data[kind] = {'screenplay_path': str(story_path), 'screenplay_sha256': story_sha,
                      'review_path': str(review_path), 'review_sha256': write(review_path, report),
                      'production_path': str(production_path),
                      'production_sha256': write(production_path, production(story, kind))}
    path = root / 'data/staged_bundle.json'
    write(path, data)
    current = copy.deepcopy(payload)
    current.update(source_overview=[{'source_id': s['source_id']} for s in full_sources],
                   script_reference_selection={
                       'requested_source_ids': ['douyin:1'],
                       'full_source_evidence_sha256': digest(script_pair._source_json(full_sources).encode('utf-8'))})
    return SimpleNamespace(root=root, path=path, data=data, current=current, workflow=workflow,
                           workflow_path=workflow_path, source_path=source_path)


def load(packet, **kwargs):
    return bundle_module.load_screenplay_bundle(packet.path, evidence=packet.current,
                                               reference_source_ids=('douyin:1',),
                                               project_root=packet.root, **kwargs)


def save_bundle(packet):
    write(packet.path, packet.data)


def update_artifact(packet, kind, component, mutate):
    item = packet.data[kind]
    path = Path(item[component + '_path'])
    value = json.loads(path.read_bytes())
    mutate(value)
    item[component + '_sha256'] = write(path, value)
    save_bundle(packet)
    return value


def rebind_story_review(packet, kind):
    item = packet.data[kind]
    story = json.loads(Path(item['screenplay_path']).read_bytes())
    report = review(story, story_sha=item['screenplay_sha256'],
                    workflow_sha=packet.data['workflow_request_sha256'], source_sha=packet.data['source_evidence_sha256'])
    item['review_sha256'] = write(Path(item['review_path']), report)
    save_bundle(packet)


def test_valid_bundle_compiles_exact_stories_and_records_every_bound_artifact(packet):
    original_files = {p: p.read_bytes() for p in packet.root.rglob('*.json')}
    before = copy.deepcopy(packet.current)
    pair, provenance = load(packet)
    assert packet.current == before
    assert {p: p.read_bytes() for p in original_files} == original_files
    assert pair['core_message'] == screenplay()['core_message']
    assert pair['short']['shots'][0]['action'] == screenplay()['version']['shots'][0]['action']
    assert pair['long']['shots'][-1]['end_seconds'] == 180
    assert provenance['status'] == 'bindings_verified_pending_final_pair_review'
    assert provenance['model_calls'] == 0 and provenance['media_generation'] is False
    for kind in ('short', 'long'):
        for component in ('screenplay', 'review', 'production'):
            assert provenance[kind][component]['sha256'] == packet.data[kind][component + '_sha256']
    assert provenance['compiled_pair_sha256'] == digest(script_pair._source_json(pair).encode('utf-8'))


@pytest.mark.parametrize('component', ['workflow_request', 'source_evidence', 'short.screenplay',
                                      'short.review', 'short.production', 'long.screenplay', 'long.review', 'long.production'])
def test_any_changed_file_bytes_invalidate_bundle_even_if_json_meaning_is_same(packet, component):
    if '.' in component:
        kind, component = component.split('.')
        path = Path(packet.data[kind][component + '_path'])
    else:
        path = Path(packet.data[component + '_path'])
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        load(packet)


@pytest.mark.parametrize('location', ['bundle', 'workflow', 'source', 'review'])
def test_all_paths_must_resolve_inside_project_data(packet, location):
    outside = packet.root / 'outside.json'
    if location == 'bundle':
        outside.write_bytes(packet.path.read_bytes())
        packet.path = outside
    else:
        row, component = (packet.data['short'], 'review') if location == 'review' else (
            packet.data, 'workflow_request' if location == 'workflow' else 'source_evidence')
        outside.write_bytes(Path(row[component + '_path']).read_bytes())
        row[component + '_path'] = str(outside)
        save_bundle(packet)
    with pytest.raises(ValueError, match='inside this project data'):
        load(packet)


def test_original_workflow_location_and_filename_are_mandatory(packet):
    wrong = packet.root / 'data/copied_request.json'
    wrong.write_bytes(packet.workflow_path.read_bytes())
    packet.data['workflow_request_path'] = str(wrong)
    save_bundle(packet)
    with pytest.raises(ValueError, match='_runs/request.json'):
        load(packet)


@pytest.mark.parametrize('mutation', ['source', 'account', 'selection', 'duration'])
def test_bundle_must_match_current_verified_context(packet, mutation):
    if mutation == 'source':
        packet.current['source_evidence'][0]['independent_review']['review_sha256'] = 'f' * 64
    elif mutation == 'account':
        packet.current['account_positioning']['audiences'] = ['另一个账号']
    elif mutation == 'selection':
        packet.current['script_reference_selection']['requested_source_ids'] = ['douyin:2']
    else:
        packet.current['short_seconds'] = 60
    with pytest.raises(ValueError):
        load(packet)


@pytest.mark.parametrize('selection', [['douyin:2'], ['douyin:1', 'douyin:1'], ['unknown'], []])
def test_bundle_cannot_change_or_invent_explicit_reference_selection(packet, selection):
    packet.data['reference_source_ids'] = selection
    save_bundle(packet)
    with pytest.raises(ValueError):
        load(packet)


def test_original_workflow_full_evidence_binding_cannot_be_substituted(packet):
    original = json.loads(packet.workflow[1]['content'])
    original['source_evidence'][0]['expression_analysis']['evidence'][0]['text'] = '替换原始证据'
    packet.workflow[1]['content'] = json.dumps(original, ensure_ascii=False)
    packet.data['workflow_request_sha256'] = write(packet.workflow_path, packet.workflow)
    save_bundle(packet)
    with pytest.raises(ValueError, match='per-source binding'):
        load(packet)


def test_focused_original_workflow_restores_exact_full_twenty_sources(packet):
    original = json.loads(packet.workflow[1]['content'])
    source = copy.deepcopy(original['source_evidence'][0])
    source['evidence_projection'] = {'full_source_sha256': digest(script_pair._source_json(source).encode('utf-8'))}
    original['script_reference_selection'] = copy.deepcopy(packet.current['script_reference_selection'])
    original['source_evidence'] = [source]
    packet.workflow[1]['content'] = json.dumps(original, ensure_ascii=False)
    packet.data['workflow_request_sha256'] = write(packet.workflow_path, packet.workflow)
    for kind in ('short', 'long'):
        rebind_story_review(packet, kind)
    assert load(packet)[0]['short']['shots'][-1]['end_seconds'] == 45
    original['script_reference_selection']['full_source_evidence_sha256'] = 'f' * 64
    packet.workflow[1]['content'] = json.dumps(original, ensure_ascii=False)
    packet.data['workflow_request_sha256'] = write(packet.workflow_path, packet.workflow)
    save_bundle(packet)
    with pytest.raises(ValueError, match='hash-bound'):
        load(packet)


@pytest.mark.parametrize('defect', ['fewer_than_twenty', 'unreviewed', 'blocked'])
def test_full_twenty_source_gate_is_rechecked_before_compilation(packet, defect):
    full = copy.deepcopy(packet.current['source_evidence'])
    if defect == 'fewer_than_twenty':
        full.pop()
    elif defect == 'unreviewed':
        full[-1]['independent_review']['decision'] = 'candidate'
    else:
        full[-1]['independent_review']['blocked_for_script_generation'] = True
    original = json.loads(packet.workflow[1]['content'])
    original['source_evidence'] = full
    packet.workflow[1]['content'] = json.dumps(original, ensure_ascii=False)
    packet.data['workflow_request_sha256'] = write(packet.workflow_path, packet.workflow)
    packet.data['source_evidence_sha256'] = write(packet.source_path, full)
    packet.current['source_evidence'] = full
    save_bundle(packet)
    with pytest.raises(ValueError):
        load(packet)


@pytest.mark.parametrize('defect', ['failed', 'stale', 'partial', 'fake_quote', 'unresolved', 'check_false'])
def test_story_review_must_be_current_complete_and_passed(packet, defect):
    def mutate(report):
        if defect == 'failed': report['decision'] = 'failed'
        elif defect == 'stale': report['candidate_sha256'] = 'f' * 64
        elif defect == 'partial': report['shot_reviews'].pop()
        elif defect == 'fake_quote': report['shot_reviews'][0]['action_quote'] = '不存在的原文'
        elif defect == 'unresolved': report['unresolved_issues'] = ['尚未解决']
        else: report['checks']['ending_complete'] = False
    update_artifact(packet, 'short', 'review', mutate)
    with pytest.raises(ValueError):
        load(packet)


def test_changed_story_cannot_use_old_review_even_when_bundle_sha_is_updated(packet):
    update_artifact(packet, 'short', 'screenplay', lambda value: value['version']['shots'][0].update(action='新动作。'))
    with pytest.raises(ValueError, match='旧SHA'):
        load(packet)


def test_production_cannot_smuggle_new_dialogue_into_approved_story(packet):
    update_artifact(packet, 'short', 'production', lambda value: value['shots'][0].update(dialogue='新对白'))
    with pytest.raises(ValueError, match='fields must'):
        load(packet)


@pytest.mark.parametrize('defect', ['core', 'identity'])
def test_individually_reviewed_versions_still_need_same_core_and_characters(packet, defect):
    def mutate(story):
        if defect == 'core': story['core_message'] = '另一个核心'
        else: story['characters'][0]['identity'] = '另一个身份'
    update_artifact(packet, 'long', 'screenplay', mutate)
    rebind_story_review(packet, 'long')
    with pytest.raises(ValueError, match='shared core|character names'):
        load(packet)


def test_long_must_add_three_shots_even_when_both_versions_validate_individually(packet):
    story = screenplay('long')
    for row in story['version']['shots']:
        row['duration_seconds'] = 5
    item = packet.data['short']
    item['screenplay_sha256'] = write(Path(item['screenplay_path']), story)
    item['production_sha256'] = write(Path(item['production_path']), production(story))
    rebind_story_review(packet, 'short')
    with pytest.raises(ValueError, match='at least three shots'):
        load(packet)


def workflow_context(packet):
    payload = copy.deepcopy(packet.current)
    source = copy.deepcopy(payload['source_evidence'][0])
    source['evidence_projection'] = {'full_source_sha256': digest(script_pair._source_json(source).encode('utf-8'))}
    payload['source_evidence'] = [source]
    return [{'role': 'system', 'content': 'Synthetic current validation context.'},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]


def run_bundle_workflow(packet, monkeypatch, *, passed=True, review_only=False):
    monkeypatch.setattr(bundle_module, 'PROJECT_ROOT', packet.root)
    monkeypatch.setattr(script_pair, 'build_messages', Mock(return_value=workflow_context(packet)))
    monkeypatch.setattr(script_pair, '_full_source_evidence', Mock(return_value=packet.current['source_evidence']))
    for name in ('_normalize_single_participants', '_fit_spoken_timing', 'bind_continuous_starts', 'bind_continuous_production'):
        monkeypatch.setattr(script_pair, name, Mock(side_effect=AssertionError('staged input must stay frozen')))
    author = SimpleNamespace(provider_name='configured', model_name='synthetic-author-not-called',
                             chat_completion_tracked=Mock(side_effect=AssertionError('no author call')))
    reviewer = SimpleNamespace(provider_name='configured', model_name='synthetic-reviewer')
    report = {'checks': {'source_semantic_fidelity': True}, 'passed': passed, 'issues': []}
    review_mock = Mock(return_value=report)
    monkeypatch.setattr(script_pair, 'review_pair', review_mock)
    profile = SimpleNamespace(account_uuid='test', domain_strategy_id='legal_services', strategy_version='test')
    kwargs = dict(created_at='2026-09-10T00:00:00+00:00', short_seconds=45, long_seconds=180,
                  trace_dir=packet.root / 'data/final_trace', script_reference_source_ids=('douyin:1',),
                  staged_screenplay_bundle_path=str(packet.path), review_client=reviewer, review_only=review_only)
    return lambda: script_pair.generate_script_pair(author, profile, [], None, **kwargs), author, review_mock


def test_generate_path_must_parse_and_review_before_returning_formal_scripts(packet, monkeypatch):
    call, author, reviewer = run_bundle_workflow(packet, monkeypatch)
    scripts = call()
    reviewer.assert_called_once()
    author.chat_completion_tracked.assert_not_called()
    for script in scripts:
        assert script.generation['method'] == 'staged_screenplay_bundle'
        assert script.generation['generation_api_calls'] == 0
        assert script.generation['model'] is None
        assert script.generation['review_only'] is True
        assert script.generation['revision_mode'] == 'frozen_stages_final_review_only'
        assert script.generation['accepted_attempt'] == 1
    trace = packet.root / 'data/final_trace'
    assert (trace / 'bundle.provenance.json').is_file()
    assert not list(trace.glob('call_*.json'))
    assert not list(trace.glob('revision_*.json'))
    assert json.loads((trace / 'draft_1.json').read_bytes())['short']['shots'][0]['action'] == screenplay()['version']['shots'][0]['action']


def test_v2_photography_bundle_preserves_story_review_bindings_and_still_uses_final_pair_gate(packet, monkeypatch):
    original_story_bindings = {kind: {key: packet.data[kind][key] for key in
                                     ('screenplay_sha256', 'review_sha256')} for kind in ('short', 'long')}
    for kind in ('short', 'long'):
        item = packet.data[kind]
        story = json.loads(Path(item['screenplay_path']).read_bytes())
        item['production_sha256'] = write(Path(item['production_path']), production_v2(story, kind))
    save_bundle(packet)
    pair, provenance = load(packet)
    assert pair['short']['expression_plan']['action_chain'][4]['visible_action'] == screenplay()['version']['shots'][4]['action']
    for kind in ('short', 'long'):
        assert provenance[kind]['screenplay']['sha256'] == original_story_bindings[kind]['screenplay_sha256']
        assert provenance[kind]['review']['sha256'] == original_story_bindings[kind]['review_sha256']
    call, author, reviewer = run_bundle_workflow(packet, monkeypatch)
    assert len(call()) == 2
    reviewer.assert_called_once()
    author.chat_completion_tracked.assert_not_called()


def test_final_review_failure_does_not_trigger_author_patch(packet, monkeypatch):
    call, author, reviewer = run_bundle_workflow(packet, monkeypatch, passed=False)
    with pytest.raises(ValueError, match='须返回对应故事或摄影阶段'):
        call()
    reviewer.assert_called_once()
    author.chat_completion_tracked.assert_not_called()
    assert not list((packet.root / 'data/final_trace').glob('revision_*.json'))


def test_staged_structural_failure_returns_to_stage_before_final_model_review(packet, monkeypatch):
    # Both stories remain valid alone, but copying the whole short dialogue
    # into the long opening still violates the pair contract. Shared setup is valid.
    short_story = json.loads(Path(packet.data['short']['screenplay_path']).read_bytes())
    def copy_short_dialogue(value):
        for target, original in zip(value['version']['shots'], short_story['version']['shots']):
            target['dialogue'] = original['dialogue']
    update_artifact(packet, 'long', 'screenplay', copy_short_dialogue)
    rebind_story_review(packet, 'long')
    call, author, reviewer = run_bundle_workflow(packet, monkeypatch)
    with pytest.raises(ValueError, match='须返回对应故事或摄影阶段'):
        call()
    reviewer.assert_not_called()
    author.chat_completion_tracked.assert_not_called()


def test_bundle_binding_failure_prevents_all_model_review_calls(packet, monkeypatch):
    packet.data['short']['review_sha256'] = 'f' * 64
    save_bundle(packet)
    call, author, reviewer = run_bundle_workflow(packet, monkeypatch)
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        call()
    reviewer.assert_not_called()
    author.chat_completion_tracked.assert_not_called()


def test_review_only_flag_is_compatible_with_bundle_without_fake_resume(packet, monkeypatch):
    call, author, reviewer = run_bundle_workflow(packet, monkeypatch, review_only=True)
    assert len(call()) == 2
    author.chat_completion_tracked.assert_not_called()
    reviewer.assert_called_once()


@pytest.mark.parametrize('field', ['initial_draft_path', 'baseline_draft_path', 'initial_revision_path', 'revision_feedback'])
def test_bundle_cannot_mix_with_any_existing_patch_or_resume_mode(field):
    from src.trend_intelligence.pre_video_script import PreVideoScriptRequest
    kwargs = {'staged_screenplay_bundle_path': 'data/bundle.json', field: 'nonempty'}
    with pytest.raises(ValueError, match='baseline/resume/revision'):
        PreVideoScriptRequest('account:test', ('mixed',), **kwargs)
    with pytest.raises(ValueError, match='baseline/resume/revision'):
        script_pair.generate_script_pair(None, None, None, None, created_at='unused',
                                          short_seconds=45, long_seconds=180, **kwargs)


def test_standalone_cli_passes_bundle_without_calling_generation_during_readiness(monkeypatch, capsys):
    from scripts import pre_video_script as cli
    factory = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    service = Mock()
    service.source_media_readiness.return_value = {'ready': True}
    monkeypatch.setattr(cli, 'PreVideoScriptRequest', factory)
    monkeypatch.setattr(cli, 'PreVideoScriptService', Mock(return_value=service))
    monkeypatch.setattr(cli.sys, 'argv', ['pre_video_script', '--account-key', 'account01',
        '--recent-video-types', 'mixed', '--staged-screenplay-bundle', 'data/approved_inputs.json', '--check-sources-only'])
    assert cli.main() == 0
    assert factory.call_args.kwargs['staged_screenplay_bundle_path'] == 'data/approved_inputs.json'
    service.generate.assert_not_called()
    assert json.loads(capsys.readouterr().out)['ready'] is True


def test_research_cli_passes_bundle_and_preserves_source_gate(monkeypatch, tmp_path, capsys):
    from scripts import run_account_video_research as cli
    from test_script_reference_cli import _research_doubles
    _, factory, service = _research_doubles(monkeypatch, tmp_path)
    assert cli.main(['--account-id', 'account01', '--resume-collection-run', 'saved',
                     '--generate-script-pair', '--staged-screenplay-bundle', 'data/approved_inputs.json']) == 1
    assert factory.call_args.kwargs['staged_screenplay_bundle_path'] == 'data/approved_inputs.json'
    service.source_media_readiness.assert_called_once()
    service.generate.assert_not_called()
    assert json.loads(capsys.readouterr().out)['video_generation_submitted'] is False


@pytest.mark.parametrize('extra', [[], ['--generate-script-pair', '--resume-draft', 'data/old.json'],
                                  ['--generate-script-pair', '--revision-feedback-file', 'data/feedback.md']])
def test_invalid_research_cli_bundle_mode_stops_before_research(monkeypatch, extra):
    from scripts import run_account_video_research as cli
    repository = Mock(side_effect=AssertionError('invalid CLI must not start research'))
    monkeypatch.setattr(cli, 'AccountProfileRepository', repository)
    with pytest.raises(SystemExit) as exc:
        cli.main(['--account-id', 'account01', '--staged-screenplay-bundle', 'data/bundle.json', *extra])
    assert exc.value.code == 2
    repository.assert_not_called()


def test_service_passes_bundle_after_original_sample_and_media_gates(monkeypatch):
    from src.trend_intelligence import pre_video_script as service_module
    class StopAtGenerator(Exception):
        pass
    rows = [SimpleNamespace(observation=object(), analysis=object()) for _ in range(20)]
    sample_gate = Mock()
    media_gate = Mock(return_value={'ready': True})
    monkeypatch.setattr(service_module, 'require_sample', sample_gate)
    monkeypatch.setattr(service_module, 'batch_media_readiness', media_gate)
    model_entry = Mock(side_effect=StopAtGenerator)
    monkeypatch.setattr(script_pair, 'generate_script_pair', model_entry)
    profile = SimpleNamespace(domain_strategy_id='legal_services')
    service = service_module.PreVideoScriptService(repository=Mock(),
        profile_repository=SimpleNamespace(get=lambda key: profile), script_client=object(), review_client=object())
    for name, value in (('_recent_candidates', rows), ('_high_traffic_cohort', rows),
                        ('_mine_overlap', object()), ('_fingerprint', 'synthetic'), ('_build_opportunity', object())):
        monkeypatch.setattr(service, name, Mock(return_value=value))
    request = service_module.PreVideoScriptRequest('account01', ('mixed',), staged_screenplay_bundle_path='data/bundle.json')
    with pytest.raises(StopAtGenerator):
        service.generate(request)
    assert sample_gate.call_args.args[0] == [r.observation for r in rows]
    assert media_gate.call_args.args[0] == [r.analysis for r in rows]
    assert model_entry.call_args.kwargs['staged_screenplay_bundle_path'] == 'data/bundle.json'
    service.repository.save_opportunity.assert_not_called()
