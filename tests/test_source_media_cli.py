"""CLI wiring only: synthetic acquisition services, no browser/network/model calls."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import acquire_source_media as acquisition_cli
from scripts import run_account_video_research as research_cli
from src.trend_intelligence.research_workflow import AccountVideoResearchResult
from src.trend_intelligence.source_policy import SourcePolicyGate, SourceProvider, SourceRequest
from test_research_workflow import _profile
from test_pre_video_script import _row


def _result(status='completed', **kwargs):
    values = {'status': status, 'manifest_path': 'fixture/media.json', 'selected_count': 20,
              'acquired_count': 1, 'cached_count': 0, 'attempted_count': 1,
              'stopped_reason': '', 'session_left_open': True, **kwargs}
    return SimpleNamespace(**values, to_dict=lambda: dict(values))


def test_saved_run_acquisition_uses_account_cohort_and_same_candidate_order_without_starting_browser():
    profile = _profile()
    first, _ = _row('first', '测试来源一', video_type='mixed', metric=5)
    second, _ = _row('second', '测试来源二', video_type='mixed', metric=9)
    rows = [replace(first, video_id='12345678901', url='https://www.douyin.com/video/12345678901', run_id='saved'),
            replace(second, video_id='12345678902', url='https://www.douyin.com/video/12345678902', run_id='saved')]
    repository = Mock()
    repository.list_observations.return_value = rows + [replace(rows[0], run_id='other')]
    service = Mock()
    service.acquire.return_value = _result()
    factory = Mock(return_value=service)
    result = acquisition_cli.acquire_for_saved_run(profile, collection_run_id='saved', repository=repository,
        max_content_candidates=1, max_items=1, service_factory=factory)
    assert result.status == 'completed'
    assert service.acquire.call_args.args[0] == [rows[1]]
    assert service.acquire.call_args.kwargs['account_uuid'] == profile.account_uuid
    assert service.acquire.call_args.kwargs['collection_run_id'] == 'saved'
    assert service.acquire.call_args.kwargs['max_items'] == 1
    assert repository.list_observations.call_args.kwargs['account_uuid'] == profile.account_uuid
    assert callable(factory.call_args.kwargs['session_factory'])


def test_acquisition_policy_limits_source_navigation_and_disallows_interactions():
    policy = acquisition_cli.build_acquisition_policy(acquisition_cli.DEFAULT_AUTHORIZATION_REFERENCE, max_items=1)
    gate = SourcePolicyGate()
    def decision(url, fields):
        return gate.evaluate(policy, SourceRequest(provider=SourceProvider.AUTHORIZED_WEB,
            purposes=frozenset({'trend_analysis'}), requested_fields=frozenset(fields), target_url=url),
            web_crawler_enabled=True)
    assert decision('https://www.douyin.com/video/12345678901', {'video_id','url','original_video'}).allowed
    assert decision('https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=12345678901', {'original_video'}).allowed
    assert not decision('https://www.douyin.com/aweme/v1/web/aweme/post/', {'original_video'}).allowed
    assert not decision('https://www.douyin.com/search/law', {'video_id'}).allowed
    assert not decision('https://www.douyin.com/video/12345678901', {'like','comment'}).allowed
    assert not decision('https://unobserved.example/video.mp4', {'original_video'}).allowed


def test_standalone_default_probe_uses_existing_authorization_and_never_invokes_models(monkeypatch, capsys):
    profiles = Mock()
    profiles.get.return_value = _profile()
    monkeypatch.setattr(acquisition_cli, 'AccountProfileRepository', Mock(return_value=profiles))
    acquire = Mock(return_value=_result('partial'))
    monkeypatch.setattr(acquisition_cli, 'acquire_for_saved_run', acquire)
    assert acquisition_cli.main(['--account-id', 'account01', '--resume-collection-run', 'saved']) == 0
    kwargs = acquire.call_args.kwargs
    assert kwargs['max_items'] == 1
    assert kwargs['authorization_reference'] == acquisition_cli.DEFAULT_AUTHORIZATION_REFERENCE
    payload = json.loads(capsys.readouterr().out)
    assert payload['analysis_submitted'] is False
    assert payload['script_generation_submitted'] is False
    assert payload['video_generation_submitted'] is False


def _stub_research(monkeypatch, tmp_path):
    profile = _profile()
    profiles = Mock()
    profiles.get.return_value = profile
    monkeypatch.setattr(research_cli, 'AccountProfileRepository', Mock(return_value=profiles))
    runtime = Mock()
    monkeypatch.setattr(research_cli, 'AccountRuntimeService', runtime)
    monkeypatch.setattr(research_cli, 'TrendRepository', Mock())
    result = AccountVideoResearchResult(workflow_run_id='fixture', account_uuid=profile.account_uuid,
        account_key=profile.account_key, profile_version=1, collection_run_id='saved',
        status='awaiting_media_analysis', sample_gate={'passed': True}, log_path=str(tmp_path/'research.json'))
    workflow = Mock()
    workflow.run.return_value = result
    monkeypatch.setattr(research_cli, 'AccountVideoResearchWorkflow', Mock(return_value=workflow))
    return workflow, runtime


def test_research_acquisition_passes_manifest_to_same_saved_batch_and_explicit_local_analysis(monkeypatch, tmp_path, capsys):
    workflow, runtime = _stub_research(monkeypatch, tmp_path)
    acquire = Mock(return_value=_result())
    monkeypatch.setattr(research_cli, 'acquire_for_saved_run', acquire)
    assert research_cli.main(['--account-id','account01','--resume-collection-run','saved',
        '--acquire-source-media','--max-source-media-items','1','--run-local-toolchain']) == 1
    runtime.assert_not_called()
    assert workflow.run.call_count == 2
    first, second = workflow.run.call_args_list
    assert first.kwargs['content_analysis_implementation'] == 'metadata_heuristic'
    assert first.kwargs['run_local_toolchain'] is False
    assert second.kwargs['resume_collection_run_id'] == 'saved'
    assert second.kwargs['local_media_manifest'] == 'fixture/media.json'
    assert second.kwargs['run_local_toolchain'] is True
    assert second.kwargs['content_analysis_implementation'] == 'local_qwen_paraformer'
    assert acquire.call_args.kwargs['max_items'] == 1
    assert json.loads(capsys.readouterr().out)['source_media_acquisition']['acquired_count'] == 1


def test_research_verification_stops_after_one_acquisition_without_analysis_or_authoring(monkeypatch, tmp_path, capsys):
    workflow, _ = _stub_research(monkeypatch, tmp_path)
    acquire = Mock(return_value=_result('human_required', acquired_count=0, stopped_reason='login_or_visible_verification'))
    monkeypatch.setattr(research_cli, 'acquire_for_saved_run', acquire)
    assert research_cli.main(['--account-id','account01','--resume-collection-run','saved',
        '--acquire-source-media','--run-local-toolchain','--generate-script-pair','--no-hold-browser']) == 1
    assert workflow.run.call_count == 1 and acquire.call_count == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['script_stage'] == 'blocked_by_research'
    assert payload['script_generation_submitted'] is False
    assert payload['source_media_acquisition']['session_left_open'] is False
    assert payload['source_media_acquisition']['cli_exit_reason'] == 'cli_exit_no_hold_browser'


def test_research_acquisition_does_not_run_local_models_without_explicit_flag(monkeypatch, tmp_path, capsys):
    workflow, _ = _stub_research(monkeypatch, tmp_path)
    monkeypatch.setattr(research_cli, 'acquire_for_saved_run', Mock(return_value=_result()))
    research_cli.main(['--account-id','account01','--resume-collection-run','saved','--acquire-source-media'])
    assert all(call.kwargs['run_local_toolchain'] is False for call in workflow.run.call_args_list)


def test_conflicting_acquisition_flags_fail_before_repository_or_browser(monkeypatch):
    repository = Mock()
    monkeypatch.setattr(research_cli, 'TrendRepository', repository)
    with pytest.raises(ValueError, match='不可混用'):
        research_cli.main(['--account-id','account01','--resume-collection-run','saved',
            '--acquire-source-media','--local-media-manifest','unused.json'])
    repository.assert_not_called()


def test_cli_holds_same_service_until_explicit_resume_and_closes_once():
    session = Mock()
    service = SimpleNamespace(session=session)
    calls, pauses = [], []
    def acquire(holder):
        if not holder:
            holder['service'] = service
        assert holder['service'] is service and service.session is session
        calls.append(holder)
        return _result('human_required', acquired_count=0) if len(calls) == 1 else _result('completed', cached_count=1)
    commands = iter(['invalid', 'resume'])
    def read(prompt):
        # Waiting and invalid commands do not retry the page or close the browser.
        assert len(calls) == 1
        session.stop.assert_not_called()
        return next(commands)
    result, state = acquisition_cli.run_cli_acquisition(acquire, input_fn=read, on_pause=pauses.append)
    assert result.status == 'completed' and len(calls) == 2
    assert calls[0] is calls[1]
    assert pauses[0]['cli_state'] == 'paused_waiting_for_user'
    assert pauses[0]['session_left_open'] is True
    assert state['session_left_open'] is False and state['manual_resume_count'] == 1
    session.stop.assert_called_once()
    assert service.session is None


@pytest.mark.parametrize('command,reason', [('stop','cli_exit_user_stop'), ('eof','cli_exit_stdin_eof'),
                                          ('interrupt','cli_exit_interrupted'), ('no_hold','cli_exit_no_hold_browser')])
def test_cli_stop_eof_and_no_hold_close_once_without_retry(command, reason):
    session = Mock()
    service = SimpleNamespace(session=session)
    acquire_count = 0
    def acquire(holder):
        nonlocal acquire_count
        acquire_count += 1
        holder['service'] = service
        return _result('human_required', acquired_count=0)
    def read(prompt):
        if command == 'eof': raise EOFError
        if command == 'interrupt': raise KeyboardInterrupt
        if command == 'no_hold': raise AssertionError('must not read stdin')
        return command
    result, state = acquisition_cli.run_cli_acquisition(acquire, no_hold_browser=command == 'no_hold',
        input_fn=read, on_pause=lambda payload: None)
    assert result.status == 'human_required' and acquire_count == 1
    assert not state['session_left_open'] and not result.session_left_open
    assert state['cli_exit_reason'] == reason and state['manual_resume_count'] == 0
    session.stop.assert_called_once()


def test_saved_run_helper_can_reuse_owned_service_without_creating_a_new_session():
    profile = _profile()
    row, _ = _row('first', '测试来源一', video_type='mixed', metric=5)
    row = replace(row, video_id='12345678901', url='https://www.douyin.com/video/12345678901', run_id='saved')
    repository = Mock()
    repository.list_observations.return_value = [row]
    service = Mock()
    service.acquire.return_value = _result()
    holder = {'service': service}
    factory = Mock()
    acquisition_cli.acquire_for_saved_run(profile, collection_run_id='saved', repository=repository,
        service_holder=holder, service_factory=factory)
    acquisition_cli.acquire_for_saved_run(profile, collection_run_id='saved', repository=repository,
        service_holder=holder, service_factory=factory)
    factory.assert_not_called()
    assert service.acquire.call_count == 2 and holder['service'] is service


def test_standalone_human_required_resumes_in_same_parent_and_outputs_final_closed_state(monkeypatch, capsys):
    profiles = Mock()
    profiles.get.return_value = _profile()
    monkeypatch.setattr(acquisition_cli, 'AccountProfileRepository', Mock(return_value=profiles))
    session = Mock()
    service = SimpleNamespace(session=session)
    calls = []
    def acquire(profile, **kwargs):
        holder = kwargs['service_holder']
        holder.setdefault('service', service)
        assert holder['service'] is service
        calls.append(holder)
        return _result('human_required', acquired_count=0) if len(calls) == 1 else _result('completed')
    monkeypatch.setattr(acquisition_cli, 'acquire_for_saved_run', acquire)
    monkeypatch.setattr('builtins.input', lambda prompt: 'resume')
    assert acquisition_cli.main(['--account-id','account01','--resume-collection-run','saved']) == 0
    output = capsys.readouterr().out
    decoder = json.JSONDecoder()
    pause, index = decoder.raw_decode(output)
    final = json.loads(output[index:].strip())
    assert pause['cli_state'] == 'paused_waiting_for_user'
    assert final['status'] == 'completed' and final['session_left_open'] is False
    assert final['manual_resume_count'] == 1
    assert calls[0] is calls[1]
    session.stop.assert_called_once()


def test_main_research_waits_for_resume_before_local_analysis(monkeypatch, tmp_path, capsys):
    workflow, _ = _stub_research(monkeypatch, tmp_path)
    session = Mock()
    service = SimpleNamespace(session=session)
    holders = []
    def acquire(profile, **kwargs):
        holder = kwargs['service_holder']
        holder.setdefault('service', service)
        holders.append(holder)
        return _result('human_required', acquired_count=0) if len(holders) == 1 else _result('completed')
    def read(prompt):
        assert workflow.run.call_count == 1 and len(holders) == 1
        session.stop.assert_not_called()
        return 'resume'
    monkeypatch.setattr(research_cli, 'acquire_for_saved_run', acquire)
    monkeypatch.setattr('builtins.input', read)
    assert research_cli.main(['--account-id','account01','--resume-collection-run','saved',
        '--acquire-source-media','--run-local-toolchain']) == 1
    assert workflow.run.call_count == 2 and holders[0] is holders[1]
    output = capsys.readouterr().out
    _, index = json.JSONDecoder().raw_decode(output)
    final = json.loads(output[index:].strip())
    assert final['source_media_acquisition']['manual_resume_count'] == 1
    assert final['source_media_acquisition']['session_left_open'] is False
    session.stop.assert_called_once()
