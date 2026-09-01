from streamlit.testing.v1 import AppTest


def test_trend_dashboard_renders_without_side_effects(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TREND_DB_PATH", str(tmp_path / "trend.db"))
    monkeypatch.setenv("ACCOUNT_PROFILE_DB_PATH", str(tmp_path / "accounts.db"))
    app = AppTest.from_file("src/web/trend_dashboard.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "账号策略",
        "采集与分析",
        "选题卡",
        "运营复盘",
    ]
    assert len(app.metric) >= 5
    assert "扩展一层相关标签族" in [item.label for item in app.checkbox]
    assert "每个关键词最多扩展标签" in [item.label for item in app.slider]
    assert "领域策略" in [item.label for item in app.selectbox]
