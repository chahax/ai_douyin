from streamlit.testing.v1 import AppTest


def test_workflow_dashboard_renders_catalog_and_profile_editor() -> None:
    app = AppTest.from_file("src/web/workflow_dashboard.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "节点设置",
        "实现目录",
        "方案管理",
    ]
    assert {metric.label for metric in app.metric} >= {
        "当前方案",
        "配置版本",
        "已接线节点",
        "已停用节点",
    }
    assert "配置方案" in [item.label for item in app.selectbox]
    assert "保存并设为当前" in [item.label for item in app.button]
