"""No-spend integration boundary; local test doubles are not approval reports."""
import json

import pytest

from scripts import run_script_video as runner
from src.trend_intelligence import saved_script_review
from test_script_video_run import setup_run, Client


def make_project_run(tmp_path):
    folder = setup_run(tmp_path)
    manifest = runner.read(folder / 'production.json')
    source = tmp_path / 'script.json'
    script = runner.read(source)
    script['generation'] = {'method': 'llm_script_pair', 'reviews': [{'passed': True}]}
    raw = json.dumps(script, ensure_ascii=False)
    source.write_text(raw, encoding='utf-8')
    (folder / 'locked_script.json').write_text(raw, encoding='utf-8')
    manifest['script_sha256'] = runner.sha(source)
    manifest['script_editorial_review'] = {'current_passed': True, 'synthetic_stale_proof': True}
    runner.write(folder / 'production.json', manifest)
    return folder, source


def test_project_pair_cannot_be_prepared_with_a_stale_review(tmp_path, monkeypatch):
    _, source = make_project_run(tmp_path)
    def reject(path):
        raise ValueError('current review required')
    monkeypatch.setattr(saved_script_review, 'require_current_saved_script_review', reject)
    output = tmp_path / 'new_run'
    with pytest.raises(ValueError, match='current review required'):
        runner.prepare(output, source, 'User authorization does not certify review coverage')
    assert not output.exists()


def test_submit_rechecks_current_report_before_paid_request_even_if_prepare_was_passed(tmp_path, monkeypatch):
    folder, source = make_project_run(tmp_path)
    calls = []
    def reject(path):
        calls.append(path)
        raise ValueError('review policy changed or script rejected')
    monkeypatch.setattr(saved_script_review, 'require_current_saved_script_review', reject)
    client = Client()
    with pytest.raises(ValueError, match='policy changed'):
        runner.submit(folder, 'S01', client, [])
    assert calls == [source.resolve()]
    assert client.calls == 0
    assert not (folder / 'S01.json').exists()


def test_locked_copy_cannot_borrow_a_report_for_changed_source(tmp_path, monkeypatch):
    folder, source = make_project_run(tmp_path)
    script = runner.read(source)
    script['shots'][0]['dialogue'] += 'This changed after locking.'
    source.write_text(json.dumps(script), encoding='utf-8')
    def forbidden(path):
        raise AssertionError('Changed text must fail before checking its report')
    monkeypatch.setattr(saved_script_review, 'require_current_saved_script_review', forbidden)
    client = Client()
    with pytest.raises(ValueError, match='锁定剧本与当前来源稿不一致'):
        runner.submit(folder, 'S01', client, [])
    assert client.calls == 0


def test_custom_script_uses_existing_path_without_claiming_project_review(monkeypatch):
    def forbidden(path):
        raise AssertionError('An explicitly custom script has no saved project pair')
    monkeypatch.setattr(saved_script_review, 'require_current_saved_script_review', forbidden)
    assert runner.require_project_script_review({'generation': {}}, 'not-read.json') is None
