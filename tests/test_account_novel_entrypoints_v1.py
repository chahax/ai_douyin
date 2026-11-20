from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import run_account_novel_creation_v1 as cli
from src.operations_accounts.models import AccountProfile
from src.operations_accounts.repository import AccountProfileRepository
from src.trend_intelligence.models import ContentOpportunity
from src.trend_intelligence.repository import TrendRepository


@pytest.fixture
def context(tmp_path, monkeypatch):
    import src.content_factory.account_novel_creation_v1 as creation
    monkeypatch.setattr(creation, "DEFAULT_REGISTRY", tmp_path / "registry")
    profile = AccountProfile(account_uuid="account:novel", account_key="novel_test",
        domain_strategy_id="novel_promotion", seed_keywords=["重生"],
        workflow_profile="novel_drama", domain_config={"genres": ["重生"]})
    now = datetime.now(timezone.utc)
    opportunity = ContentOpportunity(
        opportunity_id="op:novel", account_uuid=profile.account_uuid,
        account_key=profile.account_key, profile_version=1,
        domain_strategy_id="novel_promotion", strategy_version="v1",
        cluster_id="cluster:1", brief_id="brief:1", title="重生逆袭",
        status="candidate", opportunity_score=88, score_breakdown={},
        selected_item_ids=["item:1"], recommended_presentation="story_drama",
        recommended_hook_type="conflict", recommended_pacing="fast",
        recommended_duration_seconds=60, recommended_publish_window="20:00-22:00",
        recommended_workflow_profile="novel_drama", topic_labels=["重生"],
        valid_from=(now-timedelta(hours=1)).isoformat(),
        valid_until=(now+timedelta(days=1)).isoformat())
    accounts = AccountProfileRepository(tmp_path / "accounts.db")
    trends = TrendRepository(tmp_path / "trends.db")
    accounts.save(profile)
    trends.save_opportunity(opportunity)
    return SimpleNamespace(profile=profile, opportunity=opportunity, accounts=accounts,
        trends=trends, run=tmp_path / "run", books=tmp_path / "books")


def prepare(ctx, **kwargs):
    return cli.prepare_from_repositories(account_key=ctx.profile.account_key,
        opportunity_id=ctx.opportunity.opportunity_id, run_dir=ctx.run,
        account_db=ctx.accounts.db_path, trend_db=ctx.trends.db_path,
        books_root=ctx.books, **kwargs)


def add_book(ctx):
    book = ctx.books / "book1"
    book.mkdir(parents=True)
    source = "第一章 重生\n" + "她重生回到昨日，握紧纸上的证据，决心改变命运。" * 25
    (book / "material.txt").write_text(source, encoding="utf-8")
    (book / "meta.json").write_text(json.dumps({"book_id": "book1", "book_name": "重生逆袭",
        "genres": ["重生"]}, ensure_ascii=False), encoding="utf-8")
    (book / "text_authorization.json").write_text(json.dumps({"book_id": "book1",
        "source_sha256": hashlib.sha256((book / "material.txt").read_bytes()).hexdigest(),
        "allow_text_adaptation": True, "allow_model_input": True,
        "reference": "离线测试夹具；不授予真实书籍权限"}), encoding="utf-8")


def test_prepare_missing_material_can_recover_same_context(context):
    first = prepare(context)
    assert first["status"] == "needs_materials"
    context_bytes = (context.run / cli.CONTEXT_FILE).read_bytes()
    add_book(context)
    result = prepare(context)
    assert result["status"] == "prepared"
    assert (context.run / cli.CONTEXT_FILE).read_bytes() == context_bytes
    assert cli.validate_current_context(context.run)[0] == context.profile
    assert not (context.run / "creative").exists()


def test_execute_reloads_database_and_dispatch_validator(context, monkeypatch):
    add_book(context)
    prepare(context)
    import src.content_factory.account_novel_creation_v1 as creation
    calls = []
    def execute(run_dir, *, runner, validator):
        validator()
        calls.append(run_dir)
        return {"status": "offline", "automatic_media_submit": False}
    monkeypatch.setattr(creation, "execute_account_novel_run", execute)
    assert cli.execute_from_repositories(context.run)["status"] == "offline"
    assert calls == [context.run]
    context.trends.update_opportunity_status(context.opportunity.opportunity_id, "rejected")
    with pytest.raises(ValueError, match="rejected"):
        cli.execute_from_repositories(context.run)
    assert len(calls) == 1


def test_account_disable_switch_is_checked_separately(context):
    add_book(context)
    prepare(context)
    with context.accounts.connection() as conn:
        conn.execute("UPDATE douyin_accounts SET status = 'disabled'")
    with pytest.raises(ValueError, match="暂停或禁用"):
        cli.validate_current_context(context.run)


@pytest.mark.parametrize("change", ["profile", "opportunity", "expired", "db"])
def test_resume_rejects_changed_identity_or_freshness(context, tmp_path, change):
    add_book(context)
    prepare(context)
    if change == "profile":
        context.accounts.save(replace(context.profile, profile_version=2, seed_keywords=["都市"]))
    elif change == "opportunity":
        context.trends.save_opportunity(replace(context.opportunity, selected_item_ids=["different:item"]))
    elif change == "expired":
        context.trends.save_opportunity(replace(context.opportunity,
            valid_until=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()))
    else:
        other = AccountProfileRepository(tmp_path / "other.db")
        other.save(context.profile)
        with pytest.raises(ValueError, match="绑定已改变"):
            cli.prepare_from_repositories(account_key=context.profile.account_key,
                opportunity_id=context.opportunity.opportunity_id, run_dir=context.run,
                account_db=other.db_path, trend_db=context.trends.db_path, books_root=context.books)
        return
    with pytest.raises(ValueError):
        cli.validate_current_context(context.run)


def test_approval_preserves_source_identity(context):
    add_book(context)
    prepare(context)
    context.trends.update_opportunity_status(context.opportunity.opportunity_id, "approved")
    assert cli.validate_current_context(context.run)[1].status == "approved"


def test_entry_context_is_part_of_verified_binding(context):
    add_book(context)
    prepare(context)
    path = context.run / cli.CONTEXT_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["account_db"] = str(context.trends.db_path)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        cli.validate_current_context(context.run)


def test_cli_prepare_and_preview_are_local(context, capsys):
    add_book(context)
    assert cli.main(["prepare", "--account-key", context.profile.account_key,
        "--opportunity-id", context.opportunity.opportunity_id, "--run-dir", str(context.run),
        "--account-db", str(context.accounts.db_path), "--trend-db", str(context.trends.db_path),
        "--books-root", str(context.books)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"
    assert cli.main(["preview", "--run-dir", str(context.run)]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["automatic_media_submit"] is False
    assert "重生逆袭" in json.dumps(preview, ensure_ascii=False)
    assert not (context.run / "creative").exists()


def test_cli_bad_catalog_preserves_original_context(context, tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON数组"):
        prepare(context, catalog=catalog)
    assert not context.run.exists()


def test_panel_stable_path_and_windows_background_launch(context, monkeypatch):
    from src.web import account_novel_creation_panel as panel
    add_book(context)
    prepare(context)
    assert panel.opportunity_run_dir(context.profile, context.opportunity) == panel.opportunity_run_dir(
        context.profile, replace(context.opportunity, status="approved"))
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    calls = []
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["stdout"] is kwargs["stderr"]
        assert kwargs["creationflags"] == getattr(panel.subprocess, "CREATE_NO_WINDOW", 0)
        return SimpleNamespace(pid=12345)
    monkeypatch.setattr(panel.subprocess, "Popen", popen)
    receipt = panel.launch_account_novel_creation(context.run)
    assert receipt["pid"] == 12345
    assert calls[0][0][-3:] == ["execute", "--run-dir", str(context.run)]
    assert (context.run / "execution.log").exists()
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    with pytest.raises(PermissionError):
        panel.launch_account_novel_creation(context.run)
    assert len(calls) == 1
