"""Evidence-aware provenance views. Database access is strictly read-only."""
import json
import sqlite3
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from src.trend_intelligence.sample_gate import POLICY_TEXT, evaluate_sample


def display_time(value):
    if not value:
        return '未记录'
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return value + '（时区未记录）'
        return dt.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return '时间格式无效'


def source_history(run, root):
    rows = [dict(s) for s in run['provenance'].get('source_videos', [])]
    cutoff = run['provenance'].get('opportunity', {}).get('created_at')
    account = run['provenance'].get('account_uuid')
    db = root / 'data/trend_intelligence.db'
    conn = None
    try:
        if db.is_file() and cutoff and account:
            conn = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
        for row in rows:
            row['time_basis'] = '原审计字段' if row.get('collected_at') or row.get('analyzed_at') else '未记录'
            if conn is None:
                continue
            # Historical audit omitted observation ids. Match before the selection cutoff,
            # and explicitly label this as a reconstruction, not an exact provenance join.
            if not row.get('collected_at'):
                found = conn.execute('SELECT collected_at FROM trend_observations WHERE item_id=? AND metric_value=? AND julianday(collected_at)<=julianday(?) ORDER BY julianday(collected_at) DESC LIMIT 1',
                                     (row.get('item_id'), row.get('visible_metric'), cutoff)).fetchone()
                if found:
                    row['collected_at'] = found[0]
                    row['time_basis'] = '数据库回溯匹配（非原审计精确关联）'
            if not row.get('analyzed_at'):
                found = conn.execute('SELECT created_at FROM trend_content_analyses WHERE item_id=? AND account_uuid=? AND provider_id=? AND julianday(created_at)<=julianday(?) ORDER BY julianday(created_at) DESC LIMIT 1',
                                     (row.get('item_id'), account, row.get('analysis_provider'), cutoff)).fetchone()
                if found:
                    row['analyzed_at'] = found[0]
                    row['time_basis'] = '数据库回溯匹配（非原审计精确关联）'
    except sqlite3.Error:
        # Missing legacy tables must not break production playback.
        for row in rows:
            row.setdefault('time_basis', '数据库暂不可用；仅展示审计字段')
    finally:
        if conn:
            conn.close()
    return rows


def source_direction(source):
    """Single-label title rules, distinct from the original model analysis."""
    title = source.get('title', '')
    if any(t in title for t in ('婚姻', '亲生', '婚家', '家庭')):
        return '婚姻家事'
    if any(t in title for t in ('劳动', '旷工', '解除合同')):
        return '劳动用工'
    if any(t in title for t in ('刑事辩护', '重伤', '注销')):
        return '刑事／侵权'
    if '日常生活' in title:
        return '律师日常'
    return '其他／未分类'


def direction_counts(sources):
    counts = Counter(source_direction(s) for s in sources)
    return [{'方向': name, '条数': count, '占比': count / len(sources)}
            for name, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def render_analysis(run, root):
    st.subheader('来源时间与方向分布')
    sources = source_history(run, root)
    st.caption(POLICY_TEXT)
    gate = evaluate_sample(sources)
    cols = st.columns(3)
    cols[0].metric('有效来源视频', f'{gate.unique_videos} / 20')
    cols[1].metric('已记录主要标签', f'{len(gate.primary_tags)} / 2')
    cols[2].metric('已确认' + gate.metric_label, f'{gate.total_count:,} / 1,000,000')
    if gate.passed:
        st.success(gate.message)
    else:
        st.warning('按新门槛，此来源集不能用于后续分析。' + '；'.join(gate.reasons))
        st.caption('历史产物保留展示；下方标题规则归类不能替代原始主要标签和指标证据。')
    if not sources:
        st.info('暂无来源记录，无法计算占比。')
        return
    st.caption('统一显示北京时间（UTC+8）。发布时间 ≠ 获取时间 ≠ 分析时间；不以文件修改时间推断任务完成时间。')
    table = [{'来源': s.get('title', ''), '发布': display_time(s.get('published_at')),
              '获取': display_time(s.get('collected_at')), '元数据分析': display_time(s.get('analyzed_at')),
              '时间依据': s.get('time_basis', '未记录')} for s in sources]
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.caption('选题汇总记录：' + display_time(run['provenance'].get('opportunity', {}).get('created_at')))
    st.caption('生成提交记录：' + '；'.join(s['id'] + ' ' + display_time(s.get('created_at')) for s in run['shots']))
    st.caption('视频生成完成、下载完成和人工审核的精确时刻：本批未记录。')
    counts = direction_counts(sources)
    st.subheader('来源题材方向占比')
    st.caption(f'分母为当前批次 {len(sources)} 条来源，每条仅分入一个方向；本次标题规则归类，不是原模型结论、流量占比或平台总体分布。')
    import altair as alt
    chart = alt.Chart(pd.DataFrame(counts)).mark_bar(color='#655cf6', cornerRadiusEnd=4).encode(
        x=alt.X('占比:Q', axis=alt.Axis(format='%'), scale=alt.Scale(domain=[0, 1])),
        y=alt.Y('方向:N', sort='-x'),
        tooltip=['方向:N', '条数:Q', alt.Tooltip('占比:Q', format='.1%')]).properties(height=180)
    st.altair_chart(chart, use_container_width=True)
    st.caption('点击方向节点可展开对应来源。')
    for col, item in zip(st.columns(len(counts)), counts):
        with col:
            if st.button(f'{item["方向"]} · {item["条数"]} 条 · {item["占比"]:.1%}', key='direction_' + item['方向']):
                st.session_state['production_direction'] = item['方向']
    chosen = st.session_state.get('production_direction', counts[0]['方向'])
    st.write('当前方向：' + chosen)
    for s in sources:
        if source_direction(s) == chosen:
            st.write(s.get('title'))
            if str(s.get('video_id', '')).isdigit():
                st.link_button('打开来源内容', 'https://www.douyin.com/video/' + s['video_id'])
    st.caption('原审计的重合特征支持率是多标签指标，不能作为合计 100% 的方向占比。')


def compare_styles(baseline, candidate):
    a, b = baseline.get('dimensions', {}), candidate.get('dimensions', {})
    return [{'维度': key, '当前基线': a.get(key, '未记录'), '对比页面': b.get(key, '未记录'),
             '差异': '相同' if a.get(key) == b.get(key) else '不同／缺失'} for key in sorted(a.keys() | b.keys())]


def render_style(root):
    from src.web.page_image_comparison import render_screenshot_comparison
    render_screenshot_comparison(root)
    st.divider()
    folder = root / 'data/ui_style_baselines'
    baseline_file = folder / 'video-production-v1.json'
    report_file = folder / 'video-production-v1.md'
    if not baseline_file.is_file():
        st.info('暂无风格基线')
        return
    baseline = json.loads(baseline_file.read_text(encoding='utf-8'))
    st.subheader('页面风格基线 · 可复用对比')
    st.caption('来源为主题配置和页面源码审查；不是尚未完成的浏览器截图验收。')
    st.dataframe([{'维度': k, '当前页面': v} for k, v in baseline['dimensions'].items()], hide_index=True, use_container_width=True)
    st.download_button('下载风格基线 JSON', baseline_file.read_bytes(), file_name=baseline_file.name)
    if report_file.is_file():
        with st.expander('完整风格分析与文件展示规范'):
            st.markdown(report_file.read_text(encoding='utf-8'))
        st.download_button('下载风格分析文档', report_file.read_bytes(), file_name=report_file.name)
    uploaded = st.file_uploader('导入其他页面的风格基线 JSON 进行比较', type=['json'], key='style_candidate')
    if uploaded:
        if uploaded.size > 1_000_000:
            st.error('对比文件请控制在 1 MB 内')
            return
        try:
            candidate = json.loads(uploaded.getvalue())
            if not isinstance(candidate, dict) or not isinstance(candidate.get('dimensions'), dict):
                raise ValueError('需要包含 dimensions 对象')
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in candidate['dimensions'].items()):
                raise ValueError('dimensions 的键和值必须是文本')
            diff = compare_styles(baseline, candidate)
            st.dataframe(diff, hide_index=True, use_container_width=True)
            st.download_button('下载风格差异 CSV', pd.DataFrame(diff).to_csv(index=False).encode('utf-8-sig'), file_name='style-comparison.csv')
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f'无法读取对比基线：{exc}')
