"""Exercise the complete panel with isolated repositories and no subprocess."""
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from src.web import account_novel_creation_panel as panel
from tests import test_account_novel_entrypoints_v1 as entry_fixtures

context = entry_fixtures.context


def _app(ctx, monkeypatch):
    monkeypatch.setattr(panel, "BOOKS", ctx.books)
    monkeypatch.setattr(panel, "RUNS", ctx.run.parent / "panel_runs")
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    monkeypatch.setattr(panel, "_novel_panel_test_context", (
        ctx.profile, ctx.opportunity, ctx.trends, ctx.accounts,
    ), raising=False)
    app = AppTest.from_string(
        "from src.web import account_novel_creation_panel as panel\n"
        "panel.render_account_novel_creation(*panel._novel_panel_test_context)\n",
        default_timeout=30,
    ).run()
    run = panel.opportunity_run_dir(ctx.profile, ctx.opportunity)
    assert not app.exception
    return app, run, "account_novel_" + run.name


def test_panel_prepares_then_explicitly_launches_bound_cli(context, monkeypatch):
    entry_fixtures.add_book(context)
    launches = []
    monkeypatch.setattr(panel.subprocess, "Popen", lambda argv, **kwargs: (
        launches.append((argv, kwargs)) or SimpleNamespace(pid=4321)
    ))
    app, run, prefix = _app(context, monkeypatch)
    assert not launches and not run.exists()
    app.button(key=prefix + "prepare").click().run()
    assert not app.exception and (run / "BINDING.json").is_file()
    assert not launches and not (run / "creative").exists()
    app.button(key=prefix + "execute").click().run()
    assert not app.exception and len(launches) == 1
    argv, kwargs = launches[0]
    assert argv[-3:] == ["execute", "--run-dir", str(run)]
    assert kwargs["stdout"] is kwargs["stderr"]
    assert (run / "LAST_LAUNCH.json").is_file()


def test_panel_missing_source_is_visible_and_viewer_cannot_dispatch(context, monkeypatch):
    app, run, prefix = _app(context, monkeypatch)
    assert any("补齐" in row.value for row in app.info)
    assert not run.exists()
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    app.run()
    assert not app.exception
    assert app.button(key=prefix + "prepare").disabled
    assert not any(button.key == prefix + "execute" for button in app.button)
