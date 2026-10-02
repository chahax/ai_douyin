from pathlib import Path

from scripts import check_service_readiness
from src.shared.migration import _migration_heads


ROOT = Path(__file__).resolve().parents[1]


def test_migration_graph_resolves_declared_head_not_lexical_maximum():
    heads = _migration_heads(ROOT / "alembic" / "versions")

    assert heads == {"0008_task_execution_leases"}


def test_readiness_requires_migration_and_offline_provider_contract(monkeypatch):
    monkeypatch.setattr(check_service_readiness, "ensure_migrated", lambda strict: True)

    result = check_service_readiness.readiness()

    assert result["ready"] is True
    assert result["checks"] == {
        "migration_at_head": True,
        "offline_llm_contract": True,
        "web_liveness": None,
    }


def test_entrypoint_has_no_permissive_migration_fallback():
    source = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "alembic upgrade head" in source
    assert "check_service_readiness.py --migration-only" in source
    assert "continuing" not in source
    assert "INIT_DB_FALLBACK" not in source
