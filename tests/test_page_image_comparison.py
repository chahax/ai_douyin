import io
from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest
from src.web.page_image_comparison import validate_image, save_screenshot, list_screenshots


def sample(color='red'):
    buffer = io.BytesIO()
    Image.new('RGB', (80, 120), color).save(buffer, format='PNG')
    return buffer.getvalue()


def test_original_saved_and_deduplicated(tmp_path):
    payload = sample()
    identity = save_screenshot(tmp_path, payload, '页面A', '测试')
    assert save_screenshot(tmp_path, payload, '重复', '') == identity
    records = list_screenshots(tmp_path)
    assert len(records) == 1
    assert records[0]['captured_at'] is None
    assert (tmp_path / records[0]['file']).read_bytes() == payload
    with pytest.raises((OSError, ValueError)):
        validate_image(b'not an image')


def test_compare_modes(tmp_path):
    folder = tmp_path / 'data/ui_style_baselines/screenshots'
    save_screenshot(folder, sample(), 'A', '')
    save_screenshot(folder, sample('blue'), 'B', '')
    app = AppTest.from_string(f'from pathlib import Path\nfrom src.web.page_image_comparison import render_screenshot_comparison\nrender_screenshot_comparison(Path({str(tmp_path)!r}))').run()
    assert not app.exception
    for mode in ['左右并排', '透明叠加', '切换查看']:
        app.radio[0].set_value(mode).run()
        assert not app.exception
