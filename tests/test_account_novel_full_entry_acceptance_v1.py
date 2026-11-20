"""Independent database -> CLI adapter -> actual workflow acceptance, offline."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from scripts import run_account_novel_creation_v1 as cli
from src.content_factory import account_novel_creation_v1 as creation
from src.content_factory.creative_workflow_roles import CreativeRoleClients
from src.operations_accounts import AccountProfile, stable_account_uuid
from src.operations_accounts.repository import AccountProfileRepository
from src.trend_intelligence.models import ContentOpportunity
from src.trend_intelligence.repository import TrendRepository
from tests.test_account_novel_selection_v1 import book
from tests.test_creative_workflow import FakeClients, SOURCE, _answers


def _prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(creation, "DEFAULT_REGISTRY", tmp_path / "claims")
    profile = AccountProfile(
        account_uuid=stable_account_uuid("acceptance_novel"), account_key="acceptance_novel",
        domain_strategy_id="novel_promotion", seed_keywords=["校园"],
        domain_config={"genres": ["校园"]},
    )
    accounts = AccountProfileRepository(tmp_path / "accounts.db")
    accounts.save(profile)
    trends = TrendRepository(tmp_path / "trends.db")
    now = datetime.now(timezone.utc)
    opportunity = ContentOpportunity(
        opportunity_id="op:acceptance_novel", account_uuid=profile.account_uuid,
        account_key=profile.account_key, profile_version=1, domain_strategy_id="novel_promotion",
        strategy_version="v1", cluster_id="fixture:cluster", brief_id="fixture:brief",
        title="校园误会与和解", status="candidate", opportunity_score=80,
        score_breakdown={}, selected_item_ids=["fixture:source"],
        recommended_presentation="story_drama", recommended_hook_type="misunderstanding",
        recommended_pacing="natural", recommended_duration_seconds=60,
        recommended_publish_window="20:00", recommended_workflow_profile="novel_drama",
        topic_labels=["校园"], evidence=["离线集成夹具，不代表真实选题研究"],
        valid_from=(now - timedelta(hours=1)).isoformat(),
        valid_until=(now + timedelta(days=1)).isoformat(),
    )
    trends.save_opportunity(opportunity)
    book(tmp_path / "books", body=SOURCE)
    run = tmp_path / "run"
    result = cli.prepare_from_repositories(
        account_key=profile.account_key, opportunity_id=opportunity.opportunity_id,
        run_dir=run, account_db=accounts.db_path, trend_db=trends.db_path,
        books_root=tmp_path / "books",
    )
    assert result["status"] == "prepared"
    return run, trends, opportunity


def _answers_in_account_duration_range():
    answers = deepcopy(_answers())
    answers[0]["candidates"][0]["duration_seconds"] = 60
    answers[2]["duration_seconds"] = 60
    for beat in answers[2]["beats"]:
        beat["duration_seconds"] = 30
    expanded = []
    for original in answers[3]["shots"]:
        for index in range(3):
            shot = deepcopy(original)
            shot["id"] += chr(ord("a") + index)
            expanded.append(shot)
    answers[3]["shots"] = expanded
    return answers


def test_database_entry_reaches_real_complete_workflow_without_runner_stub(tmp_path, monkeypatch):
    run, _, _ = _prepare(tmp_path, monkeypatch)
    fake = FakeClients(_answers_in_account_duration_range())
    monkeypatch.setattr(CreativeRoleClients, "call", lambda self, *args, **kwargs: fake.call(*args, **kwargs))
    result = cli.execute_from_repositories(run)
    assert result["status"] == "machine_text_complete"
    assert result["creative_state"]["calls_started"] == len(fake.calls) == 5
    assert (run / "creative/SCREENPLAY.md").is_file()
    assert (run / "creative/STORYBOARD.json").is_file()
    assert result["automatic_media_submit"] is False
    assert SOURCE in fake.calls[0][1][1]["content"]
    assert cli.execute_from_repositories(run)["status"] == "machine_text_complete"
    assert len(fake.calls) == 5
    (run / "creative/SCREENPLAY.md").write_bytes(b"")
    assert creation.inspect_account_novel_run(run)["status"] == "incomplete_artifacts"


def test_opportunity_rejection_between_stages_blocks_next_provider_dispatch(tmp_path, monkeypatch):
    run, trends, opportunity = _prepare(tmp_path, monkeypatch)
    fake = FakeClients(_answers_in_account_duration_range())

    def call(self, *args, **kwargs):
        response = fake.call(*args, **kwargs)
        trends.update_opportunity_status(opportunity.opportunity_id, "rejected")
        return response

    monkeypatch.setattr(CreativeRoleClients, "call", call)
    try:
        result = cli.execute_from_repositories(run)
    except (RuntimeError, ValueError):
        result = creation.inspect_account_novel_run(run)
    assert len(fake.calls) == 1
    assert result["status"] == "needs_attention"
    assert not (run / "creative/SCREENPLAY.md").exists()
    import json
    receipt = json.loads((run / "creative/director_brief.json").read_text(encoding="utf-8"))
    assert receipt["provider_dispatch_started"] is False
    assert receipt["status"] == "blocked_before_dispatch"
