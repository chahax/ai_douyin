"""Human resume raises only the audited failure limit; serial media gates remain."""
from pathlib import Path

import pytest

from src.content_factory import video_campaign as campaign
from test_video_campaign import generated_review


def _script(action, *, dialogue="同一对白"):
    return {
        "schema": "detailed_video_script/v4",
        "title": "同一剧本",
        "target_duration_seconds": 45,
        "aspect_ratio": "9:16",
        "created_at": "fixture",
        "generation": {"method": "staged_screenplay_bundle"},
        "resolution": "双方停签并各自核对",
        "shots": [
            {"shot_id": "S01", "start_seconds": 0, "end_seconds": 7,
             "action": action, "dialogue": dialogue,
             "model_prompt_zh": f"执行：{action}"},
            {"shot_id": "S02", "start_seconds": 7, "end_seconds": 15,
             "action": "第二镜动作冻结", "dialogue": "第二镜对白冻结",
             "model_prompt_zh": "第二镜提示冻结"},
        ],
    }


def _write_json(path, value):
    campaign.write(path, value)
    return campaign.file_sha(path)


def _prepared_run(path, number, script):
    folder = path.parent / f"run_{number}"
    folder.mkdir()
    locked = folder / "locked_script.json"
    digest = _write_json(locked, script)
    source = folder / "source_script.json"
    campaign.write(source, script)
    manifest = {
        "shots": ["S01", "S02"], "api_model": "test-model", "provider": "ark_api",
        "script_sha256": digest, "source_script": str(source),
        "script_editorial_review": {"status": "current_passed"},
        "video_generation_submitted": False,
    }
    campaign.write(folder / "production.json", manifest)
    campaign.attach(folder, path)
    return folder, campaign.read(folder / "production.json"), {
        "shot": "S01", "provider": "ark_api", "script_sha256": digest,
        "prompt_sha256": f"{number:064x}",
    }


@pytest.fixture
def capped(tmp_path, monkeypatch):
    path = tmp_path / "campaign.json"
    campaign.write(path, {"schema": "sequential_video_campaign/v1",
        "max_failed_outputs": 10, "authorization": "initial fixture authorization",
        "provider": "ark_api", "model": "test-model", "shots": ["S01", "S02"],
        "attempts": [], "failed_outputs": 0, "status": "prepared"})
    for number in range(1, 11):
        folder, manifest, record = _prepared_run(path, number, _script(f"失败动作版本 {number}"))
        campaign.reserve(folder, manifest, record)
        campaign.review(folder, "S01", generated_review(folder, record, False))
    marker = path.with_name("HUMAN_REVIEW_REQUIRED.json")
    marker_bytes = marker.read_bytes()
    monkeypatch.setattr(campaign, "_project_script_binding", lambda folder, manifest: {
        "source_script": manifest["source_script"],
        "source_script_sha256": manifest["script_sha256"],
        "review_report": str(Path(folder) / "synthetic-review.json"),
        "review_report_sha256": "a" * 64,
        "review_status": "current_passed", "review_candidate_sha256": "b" * 64,
    })
    return path, marker, marker_bytes


def test_reassessment_preserves_failure_and_requires_new_review(capped):
    path, marker, marker_bytes = capped
    folder = path.parent / 'run_10'
    record = campaign.read(folder/'S01.json')
    previous = campaign.read(path)['attempts'][-1]
    reassess, accept = folder/'reassess.json', folder/'accept.json'
    campaign.write(reassess, {'source_video_sha256': record['video_sha256'],
        'script_sha256': record['script_sha256'],
        'decision': 'visually_usable_pending_user_sound_confirmation'})
    acceptance = {'source_video_sha256': record['video_sha256'], 'user_quote': '可以',
        'continuation_authorization': '继续',
        'checks': dict.fromkeys(('dialogue_pace', 'speaker_voice', 'lip_sync'), True)}
    campaign.write(accept, dict(acceptance, source_video_sha256='wrong'))
    with pytest.raises(ValueError, match='confirmation'):
        campaign.reopen_after_human_reassessment(folder, 'S01', reassess, accept)
    assert campaign.read(path)['attempts'][-1] == previous
    campaign.write(accept, acceptance)
    campaign.reopen_after_human_reassessment(folder, 'S01', reassess, accept)
    data = campaign.read(path)
    assert data['failed_outputs'] == 10 and campaign.failure_limit(data) == 11
    assert data['attempts'][-1]['status'] == 'awaiting_review'
    assert data['attempts'][-1]['reassessment_history'][0]['previous_attempt'] == previous
    assert marker.read_bytes() == marker_bytes
    campaign.review(folder, 'S01', generated_review(folder, record, True))
    assert campaign.read(path)['attempts'][-1]['status'] == 'passed'
    assert campaign.read(path)['failed_outputs'] == 10


def _authorize(capped, script=None, number=11):
    path, _, _ = capped
    target = script or _script("失败动作版本 10")
    folder, manifest, record = _prepared_run(path, number, target)
    result = campaign.authorize_human_resume(path, folder,
        authorization="接着来，同剧本10次失败", additional_failed_outputs=1)
    return folder, manifest, record, result


def test_human_resume_preserves_ten_failures_marker_and_original_cap(capped, monkeypatch):
    path, marker, marker_bytes = capped
    folder, manifest, record, result = _authorize(capped)
    data = campaign.read(path)
    assert data["failed_outputs"] == data["max_failed_outputs"] == 10
    assert campaign.failure_limit(data) == data["effective_failure_limit"] == 11
    assert marker.read_bytes() == marker_bytes
    assert len(data["attempts"]) == 10
    authorization = data["human_resume_authorizations"][0]
    assert authorization["authorization"] == "接着来，同剧本10次失败"
    assert authorization["authorized_at_beijing"].endswith("+08:00")
    assert authorization["provider_requests_created"] == 0
    assert authorization["media_reviews_changed"] == 0
    assert authorization["human_review_marker"]["sha256"] == campaign.file_sha(marker)
    assert authorization["authorized_source_revision_from_sha256"] == data["attempts"][-1]["script_sha256"]
    assert authorization["resulting_script_sha256"] == manifest["script_sha256"]
    assert result["effective_failure_limit"] == 11

    seen = []
    monkeypatch.setattr(campaign, "_execution_text_revision",
        lambda f, m, r, previous, script_revision=None: seen.append(script_revision) or {
            "schema": "video_upstream_revision/v1", "type": "execution_text_revision",
            "previous_failed_attempt_id": previous["id"]})
    campaign.reserve(folder, manifest, record)
    after = campaign.read(path)
    assert len(after["attempts"]) == 11
    assert after["attempts"][-1]["human_resume_authorization_id"] == "human_resume_001"
    assert seen[0]["authorization"] == "接着来，同剧本10次失败"


def test_changed_formal_sha_is_limited_to_reviewed_s01_action(capped, monkeypatch):
    target = _script("M3 修订后的首镜动作")
    folder, manifest, record, _ = _authorize(capped, target)
    row = campaign.read(capped[0])["human_resume_authorizations"][0]
    assert row["revision"]["kind"] == "m3_s01_action_revision"
    assert row["revision"]["changed_fields"] == ["shots/S01/action", "shots/S01/model_prompt_zh"]
    assert row["authorized_source_revision_from_sha256"] != row["resulting_script_sha256"]
    captured = []
    monkeypatch.setattr(campaign, "_execution_text_revision",
        lambda f, m, r, previous, script_revision=None: captured.append(script_revision) or {
            "schema": "video_upstream_revision/v1", "type": "m3_s01_action_and_execution_revision",
            "previous_failed_attempt_id": previous["id"]})
    campaign.reserve(folder, manifest, record)
    assert captured[0]["resulting_script_sha256"] == manifest["script_sha256"]


@pytest.mark.parametrize("changed", ["dialogue", "later_shot"])
def test_resume_rejects_story_or_later_shot_changes(capped, changed):
    target = _script("M3 修订后的首镜动作",
                     dialogue="偷改后的对白" if changed == "dialogue" else "同一对白")
    if changed == "later_shot":
        target["shots"][1]["action"] = "偷改第二镜"
    path = capped[0]
    folder, _, _ = _prepared_run(path, 11, target)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="same story|later shots|frozen fields"):
        campaign.authorize_human_resume(path, folder,
            authorization="接着来，同剧本10次失败")
    assert path.read_bytes() == before


def test_resume_rejects_unknown_work_and_requires_new_authorization_at_new_limit(capped, monkeypatch):
    path = capped[0]
    folder, _, _ = _prepared_run(path, 11, _script("失败动作版本 10"))
    data = campaign.read(path)
    data["attempts"].append({"id": "unknown", "status": "awaiting_generation_or_review",
                             "series_id": "legacy", "shot": "S01"})
    campaign.write(path, data)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="outstanding|unknown"):
        campaign.authorize_human_resume(path, folder,
            authorization="接着来，同剧本10次失败")
    assert path.read_bytes() == before

    data["attempts"].pop()
    campaign.write(path, data)
    campaign.authorize_human_resume(path, folder,
        authorization="接着来，同剧本10次失败")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="current audited failure limit"):
        campaign.authorize_human_resume(path, folder,
            authorization="重复调用不能继续加额")
    assert path.read_bytes() == before

    monkeypatch.setattr(campaign, "_execution_text_revision",
        lambda *args, **kwargs: {"schema": "video_upstream_revision/v1",
                                 "type": "execution_text_revision"})
    target_manifest = campaign.read(folder / "production.json")
    record = {"shot": "S01", "provider": "ark_api",
              "script_sha256": target_manifest["script_sha256"], "prompt_sha256": "f" * 64}
    campaign.reserve(folder, target_manifest, record)
    campaign.review(folder, "S01", generated_review(folder, record, False))
    assert campaign.read(path)["failed_outputs"] == 11
    assert campaign.read(path)["status"] == "paused_for_human_review"


def test_eleventh_failure_keeps_original_marker_and_writes_new_pause_record(capped, monkeypatch):
    path, marker, marker_bytes = capped
    folder, manifest, record, _ = _authorize(capped)
    monkeypatch.setattr(campaign, "_execution_text_revision",
        lambda *args, **kwargs: {"schema": "video_upstream_revision/v1",
                                 "type": "execution_text_revision"})
    campaign.reserve(folder, manifest, record)
    campaign.review(folder, "S01", generated_review(folder, record, False))
    data = campaign.read(path)
    assert data["failed_outputs"] == data["effective_failure_limit"] == 11
    assert data["max_failed_outputs"] == 10 and data["status"] == "paused_for_human_review"
    assert marker.read_bytes() == marker_bytes
    resumed_marker = path.with_name("HUMAN_REVIEW_REQUIRED_011.json")
    assert resumed_marker.is_file()
    assert campaign.read(resumed_marker)["failed_outputs"] == 11


@pytest.mark.parametrize("increment", [0, 4, True])
def test_resume_increment_is_explicit_and_small(capped, increment):
    path = capped[0]
    folder, _, _ = _prepared_run(path, 11, _script("失败动作版本 10"))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="one to three"):
        campaign.authorize_human_resume(path, folder,
            authorization="接着来，同剧本10次失败", additional_failed_outputs=increment)
    assert path.read_bytes() == before
