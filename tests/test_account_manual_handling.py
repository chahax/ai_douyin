from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.operations_accounts.manual_handling import (
    CREATOR_CONTENT_URL,
    DEFAULT_MAINTENANCE_LOG_ROOT,
    resolve_manual_handling_target,
)
from src.platform_adapter.douyin_identity import DOUYIN_SELF_URL
from src.trend_intelligence.providers.douyin_web import build_douyin_search_url


@pytest.fixture
def context():
    profile = SimpleNamespace(account_uuid="account:test-01", account_key="account01")
    maintenance_id = "maintenance:" + "a" * 32
    run = dict(run_id="1" * 32, account_uuid=profile.account_uuid, account_key=profile.account_key,
        status="blocked", started_at=1000.0, finished_at=1020.0,
        detail={"error_code": "human_required", "maintenance_run_id": maintenance_id})
    snapshot = dict(controls=[dict(account_uuid=profile.account_uuid, account_key=profile.account_key,
        state="paused", error_code="human_required", updated_at=1020.0)], playback_runs=[run])
    receipt = dict(run_id=maintenance_id, account_uuid=profile.account_uuid, account_key=profile.account_key,
        mode="playback", status="blocked", error_code="human_required", runtime_lease_acquired=True,
        started_at=datetime.fromtimestamp(1002, timezone.utc).isoformat(),
        finished_at=datetime.fromtimestamp(1018, timezone.utc).isoformat(), login_healthy=True,
        research_keywords=["装修合同", "租房押金"], playback_items=[])
    return profile, snapshot, receipt


def resolve(context, **kwargs):
    profile, snapshot, receipt = context
    return resolve_manual_handling_target(profile, snapshot=snapshot,
        maintenance_receipts={receipt["run_id"]: receipt}, **kwargs)


def test_search_uses_recorded_first_keyword_and_does_not_claim_exact_failed_query(context):
    target = resolve(context)
    assert target.url == build_douyin_search_url("装修合同")
    assert target.source == "recorded_research_keyword"
    assert "不是精确失败查询" in target.message
    assert target.run_id == "1" * 32 and target.maintenance_run_id == "maintenance:" + "a" * 32


@pytest.mark.parametrize("video_id", ["7681138441245269931", 7681138441245269931])
def test_video_id_creates_canonical_url_and_ignores_item_url(context, video_id):
    context[2]["playback_items"] = [{"error_code": "human_required", "video_id": video_id,
        "url": "https://evil.example/?token=must-not-copy"}]
    target = resolve(context)
    assert target.url == "https://www.douyin.com/video/7681138441245269931"
    assert target.source == "playback_video"
    assert "must-not-copy" not in repr(target)


def test_creator_sync_challenge_uses_fixed_content_page(context):
    profile, snapshot, receipt = context
    snapshot["runs"] = snapshot.pop("playback_runs")
    receipt["mode"] = "post-publish"
    receipt["url"] = "file:///C:/Users/c/.aws/credentials"
    target = resolve(context)
    assert target.url == CREATOR_CONTENT_URL and target.source == "creator_content"


@pytest.mark.parametrize("field,value", [("state", "active"), ("state", "recovering"),
    ("state", "recovery_requested"), ("error_code", "login_expired"),
    ("error_code", "recovery_probe_failed"), ("account_key", "account02"),
    ("account_uuid", "account:other"), ("updated_at", 1021.0)])
def test_only_current_same_account_paused_human_context_can_select_target(context, field, value):
    context[1]["controls"][0][field] = value
    assert resolve(context).url == DOUYIN_SELF_URL


@pytest.mark.parametrize("field,value", [("status", "running"), ("status", "outcome_unknown"),
    ("finished_at", None), ("finished_at", 999.0), ("account_key", "account02"),
    ("account_uuid", "account:other"), ("run_id", "../../.aws/credentials")])
def test_nonterminal_cross_account_or_invalid_run_falls_back(context, field, value):
    context[1]["playback_runs"][0][field] = value
    assert resolve(context).url == DOUYIN_SELF_URL


def test_latest_unfinished_run_prevents_reusing_older_failure_context(context):
    later = copy.deepcopy(context[1]["playback_runs"][0])
    later.update(run_id="2" * 32, started_at=1030.0, finished_at=None, status="running")
    context[1]["playback_runs"].append(later)
    assert resolve(context).url == DOUYIN_SELF_URL


@pytest.mark.parametrize("field,value", [("run_id", "maintenance:" + "b" * 32),
    ("account_uuid", "account:other"), ("account_key", "account02"), ("mode", "post-publish"),
    ("error_code", "login_expired"), ("status", "running"), ("finished_at", ""),
    ("started_at", "malformed"), ("started_at", "2026-10-18T00:00:00"),
    ("finished_at", "2030-01-01T00:00:00+00:00"), ("runtime_lease_acquired", False)])
def test_receipt_requires_matching_identity_complete_terminal_and_bounded_timing(context, field, value):
    profile, snapshot, receipt = context
    original_id = receipt["run_id"]
    receipt[field] = value
    target = resolve_manual_handling_target(profile, snapshot=snapshot, maintenance_receipts={original_id: receipt})
    assert target.url == DOUYIN_SELF_URL


@pytest.mark.parametrize("video_id", ["../../credentials", "https://evil.example", "１２３４５６７８", True, "12"])
def test_bad_video_identity_never_falls_through_to_another_handling_page(context, video_id):
    context[2]["playback_items"] = [{"error_code": "human_required", "video_id": video_id}]
    assert resolve(context).url == DOUYIN_SELF_URL


@pytest.mark.parametrize("keyword", ["", "https://evil.example/?token=secret", "file:///C:/private", "a\\b", "a\nb"])
def test_invalid_recorded_first_keyword_does_not_select_arbitrary_url_or_second_keyword(context, keyword):
    context[2]["research_keywords"] = [keyword, "租房押金"]
    assert resolve(context).url == DOUYIN_SELF_URL


def test_identity_not_confirmed_falls_back_to_self_even_with_keyword(context):
    context[2]["login_healthy"] = False
    assert resolve(context).url == DOUYIN_SELF_URL


@pytest.mark.parametrize("items", [[], [{"video_id": "7681138441245269931", "error_code": "human_required"}]])
def test_feed_challenge_reopens_feed_without_keywords_or_video_detail(context, items):
    context[2].update(playback_source="recommend_feed", failure_stage="playback",
                      research_keywords=[], playback_items=items)
    target = resolve(context)
    assert target.url == "https://www.douyin.com/?recommend=1"
    assert target.source == "recommend_feed"
    assert target.maintenance_run_id == context[2]["run_id"]


@pytest.mark.parametrize("stage,healthy", [("identity", True), ("playback", False), ("", True)])
def test_feed_marker_does_not_override_identity_failure_or_unknown_stage(context, stage, healthy):
    context[2].update(playback_source="recommend_feed", failure_stage=stage, login_healthy=healthy)
    assert resolve(context).url == DOUYIN_SELF_URL


def test_feed_marker_still_requires_current_matching_receipt(context):
    context[2].update(playback_source="recommend_feed", failure_stage="playback",
                      account_uuid="account:other")
    assert resolve(context).url == DOUYIN_SELF_URL


@pytest.mark.parametrize('recommend',[True,False])
def test_feed_not_ready_target_is_limited_to_original_recommendation_receipt(context,recommend):
    context[1]['controls'][0]['error_code']='feed_not_ready'
    context[1]['playback_runs'][0]['detail']['error_code']='feed_not_ready'
    context[2].update(error_code='feed_not_ready',failure_stage='playback',
                      playback_source='recommend_feed' if recommend else 'search')
    assert resolve(context).source == ('recommend_feed' if recommend else 'fallback')


def test_identity_preflight_after_selection_is_not_misrepresented_as_search_failure(context):
    context[2]["playback_candidates"] = 3
    assert resolve(context).url == DOUYIN_SELF_URL


@pytest.mark.parametrize("items", [None, {}])
def test_malformed_playback_items_are_not_reinterpreted_as_research(context, items):
    context[2]["playback_items"] = items
    assert resolve(context).url == DOUYIN_SELF_URL


def test_default_log_root_is_project_absolute_and_only_fixed_receipt_filename_is_read(context, tmp_path):
    profile, snapshot, receipt = context
    assert DEFAULT_MAINTENANCE_LOG_ROOT.is_absolute()
    assert DEFAULT_MAINTENANCE_LOG_ROOT == Path(__file__).resolve().parents[1] / "data" / "account_maintenance"
    root = tmp_path / "receipts"
    target = root / profile.account_key / (receipt["run_id"].replace(":", "_") + ".json")
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(receipt), encoding="utf-8")
    snapshot["playback_runs"][0]["detail"] = json.dumps({**snapshot["playback_runs"][0]["detail"],
        "maintenance_log": "C:/Users/c/.aws/credentials", "url": "https://evil.example"})
    result = resolve_manual_handling_target(profile, snapshot=snapshot, log_root=root)
    assert result.source == "recorded_research_keyword"


def test_missing_expected_receipt_does_not_read_detail_supplied_path(context, tmp_path, monkeypatch):
    profile, snapshot, receipt = context
    outside = tmp_path / "credentials.json"
    outside.write_text(json.dumps(receipt), encoding="utf-8")
    snapshot["playback_runs"][0]["detail"]["maintenance_log"] = str(outside)
    original = Path.open
    def guarded(path, *a, **k):
        assert path != outside, "a detail supplied credential path must never be read"
        return original(path, *a, **k)
    monkeypatch.setattr(Path, "open", guarded)
    assert resolve_manual_handling_target(profile, snapshot=snapshot, log_root=tmp_path / "fixed_root").url == DOUYIN_SELF_URL


def test_receipt_id_path_escape_and_credential_log_root_are_not_read(context, tmp_path, monkeypatch):
    profile, snapshot, receipt = context
    def forbidden(*a, **k):
        pytest.fail("unsafe target must not read a local file")
    monkeypatch.setattr(Path, "open", forbidden)
    snapshot["playback_runs"][0]["detail"]["maintenance_run_id"] = "../../.aws/credentials"
    assert resolve_manual_handling_target(profile, snapshot=snapshot, log_root=tmp_path).url == DOUYIN_SELF_URL
    snapshot["playback_runs"][0]["detail"]["maintenance_run_id"] = receipt["run_id"]
    assert resolve_manual_handling_target(profile, snapshot=snapshot, log_root=tmp_path / ".aws").url == DOUYIN_SELF_URL


@pytest.mark.parametrize("injected", ["C:/Users/c/.aws/credentials", {"maintenance:" + "a" * 32: "C:/Users/c/.aws/credentials"}])
def test_injected_receipts_are_decoded_objects_never_paths(context, injected, monkeypatch):
    profile, snapshot, _ = context
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("receipt injection must not read paths"))
    assert resolve_manual_handling_target(profile, snapshot=snapshot, maintenance_receipts=injected).url == DOUYIN_SELF_URL


def test_explicit_account_disagreement_is_rejected_and_no_snapshot_reads_nothing(context, monkeypatch):
    profile, _, _ = context
    with pytest.raises(ValueError):
        resolve_manual_handling_target(profile, account_key="account02")
    with pytest.raises(ValueError):
        resolve_manual_handling_target(account_uuid="account:test", account_key="../account01")
    monkeypatch.setattr("src.operations_accounts.manual_handling._read_receipt", lambda *a: pytest.fail("unexpected file read"))
    assert resolve_manual_handling_target(profile).url == DOUYIN_SELF_URL


@pytest.mark.parametrize("field", ["controls", "runs", "smart_runs", "playback_runs"])
def test_malformed_snapshot_collections_fall_back_without_exception(context, field):
    context[1][field] = None
    assert resolve(context).url == DOUYIN_SELF_URL


def test_smart_operations_need_explicit_research_stage_to_disambiguate_search_from_backend(context):
    _, snapshot, receipt = context
    snapshot["smart_runs"] = snapshot.pop("playback_runs")
    receipt["mode"] = "smart-operations"
    assert resolve(context).url == DOUYIN_SELF_URL
    receipt["failure_stage"] = "research"
    assert resolve(context).source == "recorded_research_keyword"


LEGACY_SMART_WARNING = "本轮关联视频搜索需要人工验证；继续同步作品后台数据，运营报告使用最近成功采集的缓存样本。"


def smart_search_context(context):
    _, snapshot, receipt = context
    snapshot["smart_runs"] = snapshot.pop("playback_runs")
    receipt.update(mode="smart-operations", failure_stage="research", blocked_search={
        "query": "租房押金 法律", "query_kind": "keyword", "sort_key": "most_liked",
        "detection": "visible_challenge"})
    return receipt


@pytest.mark.parametrize("stage", ["research", "trend_collection"])
@pytest.mark.parametrize("query,kind", [("租房押金 法律", "keyword"), ("#劳动合同", "hashtag")])
def test_new_smart_search_recovers_actual_blocked_query_not_first_planned_keyword(context, stage, query, kind):
    from urllib.parse import quote
    receipt = smart_search_context(context)
    receipt["failure_stage"] = stage
    receipt["blocked_search"].update(query=query, query_kind=kind)
    target = resolve(context)
    assert target.source == "blocked_search"
    assert target.url == f"https://www.douyin.com/search/{quote(query, safe='')}?type=video"
    assert "装修合同" not in target.url
    assert "原请求排序为“最多点赞”" in target.message and "未自动恢复排序" in target.message
    assert "不代表当前页面仍有同一提示" in target.message
    assert "sort" not in target.url


@pytest.mark.parametrize("sort", ["comprehensive", "most_liked", "latest"])
@pytest.mark.parametrize("detection", ["visible_challenge", "security_text_without_results",
    "login_prompt_without_results", "unclassified"])
def test_known_search_enums_are_accepted_without_claiming_current_captcha(context, sort, detection):
    receipt = smart_search_context(context)
    receipt["blocked_search"].update(sort_key=sort, detection=detection)
    target = resolve(context)
    assert target.source == "blocked_search"
    assert "原记录分类" in target.message and "当前验证码" not in target.message


@pytest.mark.parametrize("field,value", [
    ("query", "https://evil.example/"), ("query", "//evil.example"),
    ("query", "javascript:alert(1)"), ("query", "file:///private"),
    ("query", "a\\b"), ("query", "a\nb"), ("query", "a\x7fb"),
    ("query", "a\ud800b"), ("query", "a" * 201), ("query", ""),
    ("query", True), ("query", ["装修合同"]), ("query_kind", "url"),
    ("query_kind", []), ("sort_key", "https://evil.example"), ("sort_key", {}),
    ("detection", "captcha_solved"), ("detection", False),
])
def test_invalid_blocked_metadata_never_downgrades_to_planned_keyword(context, field, value):
    receipt = smart_search_context(context)
    receipt["blocked_search"][field] = value
    assert resolve(context).source == "fallback"


@pytest.mark.parametrize("metadata", [None, [], True, {"query": "装修合同"}])
def test_malformed_blocked_metadata_falls_back(context, metadata):
    receipt = smart_search_context(context)
    receipt["blocked_search"] = metadata
    assert resolve(context).url == DOUYIN_SELF_URL


@pytest.mark.parametrize("query", ["劳动合同", "#", "#  "])
def test_hashtag_metadata_requires_actual_hashtag_query(context, query):
    receipt = smart_search_context(context)
    receipt["blocked_search"].update(query_kind="hashtag", query=query)
    assert resolve(context).source == "fallback"


def test_search_path_encodes_delimiters_and_ignores_no_receipt_url(context):
    receipt = smart_search_context(context)
    receipt["blocked_search"]["query"] = "装修/押金?type=user&sort=latest#tag"
    target = resolve(context)
    assert target.source == "blocked_search"
    assert "%2F" in target.url and "%3F" in target.url and "%23" in target.url
    assert target.url.count("?") == 1
    receipt["blocked_search"]["url"] = "https://evil.example"
    assert resolve(context).url == DOUYIN_SELF_URL


def test_exact_legacy_smart_warning_allows_only_nonexact_recorded_first_keyword(context):
    receipt = smart_search_context(context)
    receipt.pop("failure_stage")
    receipt.pop("blocked_search")
    receipt["warnings"] = [LEGACY_SMART_WARNING]
    target = resolve(context)
    assert target.source == "recorded_research_keyword"
    assert target.url == build_douyin_search_url("装修合同")
    assert "不是精确失败查询" in target.message
    receipt["warnings"] = [LEGACY_SMART_WARNING[:-1]]
    assert resolve(context).source == "fallback"


@pytest.mark.parametrize("stage", ["published_data_sync", "identity", "playback", "unknown", None, []])
@pytest.mark.parametrize("new_metadata", [False, True])
def test_later_or_unknown_stage_never_uses_earlier_search_warning_or_metadata(context, stage, new_metadata):
    receipt = smart_search_context(context)
    receipt["failure_stage"] = stage
    receipt["warnings"] = [LEGACY_SMART_WARNING]
    if not new_metadata:
        receipt.pop("blocked_search")
    assert resolve(context).source == "fallback"


def test_new_metadata_still_requires_original_identity_latest_run_and_bound_receipt(context):
    receipt = smart_search_context(context)
    receipt["login_healthy"] = False
    assert resolve(context).source == "fallback"
    receipt["login_healthy"] = True
    receipt["account_uuid"] = "account:other"
    assert resolve(context).source == "fallback"
    receipt["account_uuid"] = context[0].account_uuid
    later = copy.deepcopy(context[1]["smart_runs"][0])
    later.update(run_id="2" * 32, started_at=1030, finished_at=None, status="outcome_unknown")
    context[1]["smart_runs"].append(later)
    assert resolve(context).source == "fallback"


def test_new_search_report_displays_bounded_probe_evidence_not_arbitrary_payload(context):
    receipt=smart_search_context(context)
    receipt['challenge_evidence']=dict(version=2,frame_count=2,actionable_frames=1,visible_dialogs=0,
        confirmations=2,url='https://private/?token=secret')
    target=resolve(context)
    assert '连续确认2次' in target.message and '候选验证帧2' in target.message
    assert 'secret' not in target.message and 'secret' not in target.url
    receipt.pop('challenge_evidence')
    assert '旧记录未保存' in resolve(context).message


def test_unconfirmed_surface_preserves_original_target_and_explains_blank_content(context):
    receipt=smart_search_context(context)
    control=context[1]['controls'][0]
    control['error_code']='verification_ui_unconfirmed'
    run=context[1]['smart_runs'][0]
    run['detail']['error_code']='verification_ui_unconfirmed'
    receipt['error_code']='verification_ui_unconfirmed'
    receipt['blocked_search']['detection']='verification_ui_unconfirmed'
    receipt['challenge_evidence']=dict(version=3,frame_count=1,actionable_frames=1,visible_dialogs=0,
        confirmations=0,surface_state='blank')
    target=resolve(context)
    assert target.source=='blocked_search' and '验证内容：空白' in target.message
    assert '未确认可操作验证码' in target.message
