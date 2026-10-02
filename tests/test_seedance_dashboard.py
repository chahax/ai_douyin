from streamlit.testing.v1 import AppTest


def _dashboard_app() -> None:
    from src.shared.config import settings
    from src.web.seedance_dashboard import page_seedance_usage
    settings.SEEDANCE_PROVIDER='dreamina_cli'
    page_seedance_usage()


def test_seedance_dashboard_defaults_to_dreamina_channel() -> None:
    from src.web.seedance_dashboard import PROVIDER_LABELS

    app = AppTest.from_function(_dashboard_app).run(timeout=20)

    assert not app.exception
    assert any("视频用量与余额" in item.value for item in app.markdown)
    assert app.selectbox[0].label == "生成渠道"
    assert app.selectbox[0].value == "dreamina_cli"
    assert app.selectbox[0].options == list(PROVIDER_LABELS.values())

    app.selectbox[0].set_value("byteplus_api").run(timeout=20)
    assert not app.exception
    assert app.selectbox[0].value == "byteplus_api"
    app.selectbox[0].set_value('ark_api').run(timeout=20)
    assert not app.exception
    assert any('Seedance 2.0 Mini' in str(item.value) for item in app.dataframe)
    assert any(m.label=='API 返回的生成用量' for m in app.metric)
