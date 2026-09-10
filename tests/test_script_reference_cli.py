"""Focused author-reference CLI wiring only; all services are local test doubles."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import pre_video_script as standalone
from scripts import run_account_video_research as research
from src.trend_intelligence import pre_video_script as core
from src.trend_intelligence.research_workflow import AccountVideoResearchResult


def _flags(selected):
    return [part for sid in selected for part in ('--script-reference-source-id', sid)]


@pytest.mark.parametrize('selected', [[], ['douyin:two', 'douyin:one'], ['douyin:one', 'douyin:one']])
def test_standalone_cli_forwards_exact_tuple_to_readiness_without_generation(monkeypatch, capsys, selected):
    # Preserve duplicate input for core validation; the CLI must not silently deduplicate it.
    request_factory = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    service = Mock()
    service.source_media_readiness.return_value = {'ready': True, 'message': 'fixture only'}
    monkeypatch.setattr(standalone, 'PreVideoScriptRequest', request_factory)
    monkeypatch.setattr(standalone, 'PreVideoScriptService', Mock(return_value=service))
    monkeypatch.setattr(standalone.sys, 'argv', ['pre_video_script', '--account-key', 'account01',
        '--recent-video-types', 'mixed', '--collection-run-id', 'saved', '--check-sources-only', *_flags(selected)])
    assert standalone.main() == 0
    kwargs = request_factory.call_args.kwargs
    assert kwargs['script_reference_source_ids'] == tuple(selected)
    assert kwargs['max_source_videos'] == 20
    assert kwargs['collection_run_id'] == 'saved'
    assert service.source_media_readiness.call_args.kwargs == {'verify_artifacts': True}
    assert service.source_media_readiness.call_args.args[0].script_reference_source_ids == tuple(selected)
    service.generate.assert_not_called()
    assert json.loads(capsys.readouterr().out)['ready'] is True


def _research_doubles(monkeypatch, tmp_path, *, sample_passed=True):
    profile = SimpleNamespace(account_key='account01', account_uuid='account:test')
    monkeypatch.setattr(research, 'AccountProfileRepository', Mock(return_value=SimpleNamespace(get=lambda key: profile)))
    monkeypatch.setattr(research, 'AccountRuntimeService', Mock(side_effect=AssertionError('must resume existing batch')))
    monkeypatch.setattr(research, 'DouyinWebTrendProvider', SimpleNamespace(for_account=lambda key: Mock()))
    monkeypatch.setattr(research, 'TrendRepository', Mock())
    result = AccountVideoResearchResult(workflow_run_id='test', account_uuid=profile.account_uuid,
        account_key=profile.account_key, profile_version=1, collection_run_id='saved', status='completed',
        sample_gate={'passed': sample_passed}, log_path=str(tmp_path / 'research.json'))
    workflow = Mock()
    workflow.run.return_value = result
    monkeypatch.setattr(research, 'AccountVideoResearchWorkflow', Mock(return_value=workflow))
    request_factory = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    service = Mock()
    service.recent_video_type_counts.return_value = {'mixed': 20}
    service.source_media_readiness.return_value = {'ready': False, 'message': 'fixture source gate blocks author'}
    monkeypatch.setattr(core, 'PreVideoScriptRequest', request_factory)
    monkeypatch.setattr(core, 'PreVideoScriptService', Mock(return_value=service))
    return workflow, request_factory, service


@pytest.mark.parametrize('selected', [[], ['douyin:two', 'douyin:one'], ['douyin:one', 'douyin:one']])
def test_research_cli_passes_focus_only_to_script_request_and_keeps_media_gate(monkeypatch, tmp_path, capsys, selected):
    workflow, factory, service = _research_doubles(monkeypatch, tmp_path)
    assert research.main(['--account-id', 'account01', '--resume-collection-run', 'saved',
                          '--generate-script-pair', *_flags(selected)]) == 1
    assert factory.call_args.kwargs['script_reference_source_ids'] == tuple(selected)
    assert factory.call_args.kwargs['collection_run_id'] == 'saved'
    assert 'script_reference_source_ids' not in workflow.run.call_args.kwargs
    assert workflow.run.call_args.kwargs['max_content_candidates'] == 50
    assert workflow.run.call_args.kwargs['run_local_toolchain'] is False
    assert service.source_media_readiness.call_args.kwargs == {'verify_artifacts': True}
    service.generate.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload['sample_gate']['passed'] is True
    assert payload['script_stage'] == 'blocked_by_source_media'
    assert payload['video_generation_submitted'] is False


def test_focused_cli_cannot_bypass_original_research_sample_gate(monkeypatch, tmp_path, capsys):
    _, factory, service = _research_doubles(monkeypatch, tmp_path, sample_passed=False)
    assert research.main(['--account-id', 'account01', '--resume-collection-run', 'saved',
        '--generate-script-pair', '--script-reference-source-id', 'douyin:one']) == 1
    factory.assert_not_called()
    service.source_media_readiness.assert_not_called()
    service.generate.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload['script_stage'] == 'blocked_by_research'
    assert payload['video_generation_submitted'] is False
