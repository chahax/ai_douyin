"""Persist original page screenshots and compare without altering source images."""
import base64
import hashlib
import io
import json
from datetime import datetime, timezone

from PIL import Image
import streamlit as st


def validate_image(payload):
    if len(payload) > 10 * 1024 * 1024:
        raise ValueError('每张图片不得超过10 MB')
    with Image.open(io.BytesIO(payload)) as im:
        if im.format not in {'PNG', 'JPEG', 'WEBP'}:
            raise ValueError('仅支持PNG、JPEG和WebP截图')
        if im.width * im.height > 24_000_000:
            raise ValueError('截图不得超过2400万像素')
        info = dict(width=im.width, height=im.height,
                    extension={'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}[im.format])
        im.verify()
    return info


def save_screenshot(folder, payload, title, note):
    info = validate_image(payload)
    identity = hashlib.sha256(payload).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (identity + '.' + info['extension'])
    metadata = folder / (identity + '.json')
    if not path.exists():
        path.write_bytes(payload)
    if not metadata.exists():
        record = dict(info, id=identity, title=title.strip()[:100] or '未命名页面',
                      note=note.strip()[:500], file=path.name,
                      saved_at=datetime.now(timezone.utc).isoformat(),
                      captured_at=None)
        metadata.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return identity


def list_screenshots(folder):
    records = []
    for path in sorted(folder.glob('*.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            expected = record['id'] + '.' + record['extension']
            if record.get('file') != expected or len(record['id']) != 64 or any(c not in '0123456789abcdef' for c in record['id']):
                continue
            if record['extension'] not in {'png', 'jpg', 'webp'}:
                continue
            image = folder / expected
            if image.is_file():
                records.append(record)
        except (ValueError, OSError, KeyError, TypeError):
            continue
    return sorted(records, key=lambda r: r.get('saved_at', ''), reverse=True)


def render_screenshot_comparison(root):
    folder = root / 'data/ui_style_baselines/screenshots'
    st.subheader('页面截图对比')
    st.caption('保存不同页面或版本的真实截图，再选择基准A和新版B。不会把JSON参数表当作真实页面截图。')
    with st.expander('添加页面截图', expanded=not list_screenshots(folder)):
        with st.form('save_page_screenshot', clear_on_submit=True):
            title = st.text_input('页面 / 版本名称', placeholder='例如：视频制作流程 · 当前版')
            note = st.text_input('截图说明', placeholder='页面地址、选中节点、浏览器缩放、截图时间等')
            upload = st.file_uploader('页面截图', type=['png', 'jpg', 'jpeg', 'webp'], key='page_screenshot_upload')
            save = st.form_submit_button('保存到本地截图库')
        if save:
            if upload is None:
                st.warning('请先选择一张截图')
            else:
                try:
                    save_screenshot(folder, upload.getvalue(), title, note)
                    st.success('截图已保存；相同图片不会重复入库。')
                except (ValueError, OSError, Image.DecompressionBombError) as exc:
                    st.error(f'无法保存：{exc}')
    records = list_screenshots(folder)
    if not records:
        st.info('还没有真实页面截图。添加当前页面与新版截图后即可比较。')
        return
    label = lambda i: f'{records[i]["title"]} · {records[i]["width"]}×{records[i]["height"]} · {records[i]["id"][:6]}'
    left, right = st.columns(2)
    a = left.selectbox('基准页面 A', range(len(records)), format_func=label, key='screenshot_a')
    b = right.selectbox('对比页面 B', range(len(records)), index=min(1, len(records)-1), format_func=label, key='screenshot_b')
    aa, bb = records[a], records[b]
    if a == b:
        st.info('当前A、B是同一张图；可添加或选择另一页面。')
    mode = st.radio('对比方式', ['切换查看', '左右并排', '透明叠加'], horizontal=True)
    def show(record):
        path = folder / record['file']
        st.image(str(path), caption=record['title'], use_container_width=True)
        st.caption(record['note'] or '无截图说明')
        st.caption(f'{record["width"]}×{record["height"]} px；入库时间 {record["saved_at"]}（不是自动获取的截图时间）')
    same_size = (aa['width'], aa['height']) == (bb['width'], bb['height'])
    if not same_size:
        st.warning('两张截图尺寸不同。预览按容器宽度等比显示；叠加已禁用，请使用相同视口、缩放和滚动位置重截。')
    if mode == '切换查看':
        chosen = st.radio('显示页面', ['A', 'B'], horizontal=True)
        show(aa if chosen == 'A' else bb)
    elif mode == '左右并排':
        for col, record in zip(st.columns(2), (aa, bb)):
            with col:
                show(record)
    elif same_size:
        opacity = st.slider('新版B的透明度', 0, 100, 50) / 100
        def data_url(record):
            mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp'}[record['extension']]
            return 'data:' + mime + ';base64,' + base64.b64encode((folder / record['file']).read_bytes()).decode('ascii')
        # Original bytes stay intact. CSS layers use identical geometry, without cropping.
        st.html(f'<div style="display:grid"><img alt="基准页面A" src="{data_url(aa)}" style="grid-area:1/1;width:100%"><img alt="对比页面B" src="{data_url(bb)}" style="grid-area:1/1;width:100%;opacity:{opacity}"></div>')
    st.caption('截图保存位置：' + str(folder))
