"""Creator-oriented home, backed by existing production artifacts and services."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path

import streamlit as st

from src.web.components.ui import section_header

ROOT = Path(__file__).resolve().parents[2]


def recent_projects(root: Path = ROOT, limit: int = 3, account_uuid: str | None = None) -> list[dict]:
    from src.services.production_registry import list_projects, read_record
    projects = []
    for group in list_projects(root, account_uuid=account_uuid)[:limit]:
        path = (group['assemblies'] or group['attempts'])[0]
        manifest = read_record(path)
        image = (root / str(manifest.get('contact_sheet', ''))).resolve()
        if not (image.is_relative_to((root / 'data').resolve()) and image.is_file()
                and image.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}):
            image = None
        stamp = group['recorded_at']
        projects.append(dict(title=group['title'], batch=group['key'], image=image,
                             status='已有合成记录 · 查看审核' if group['assemblies'] else '制作中 · 查看审核',
                             shots=len(manifest.get('inputs') or manifest.get('shots') or []),
                             date=stamp.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m.%d') if stamp.year > 1 else '时间未记录',
                             recorded_at=stamp))
    return projects


def render_studio_home(destinations: dict) -> None:
    st.markdown('<div class="studio-topline"><strong>创作工作台</strong>'
                '<span class="studio-status">本地工作空间</span></div>', unsafe_allow_html=True)
    st.subheader('继续制作，查看账号与用量')
    st.caption('逐段审核、成片归档与运营管理。生成成功、质量通过和平台发布分别记录。')
    quick = [(key, label, icon) for key, label, icon in [
        ('accounts', '管理抖音账号', 'manage_accounts'),
        ('video_usage', '查看视频用量与余额', 'account_balance_wallet'),
    ] if key in destinations]
    if quick:
        for col, (key, label, icon) in zip(st.columns(len(quick)), quick):
            with col:
                st.page_link(destinations[key], label=label, icon=f':material/{icon}:', width='stretch')

    entries = [
        ('research', '01 / DISCOVER', '发现热门选题', '追踪趋势 · 内容调研 · 脚本草案', '↗', '', '开始选题'),
        ('production', '02 / CREATE', '打磨视频作品', '剧本与分镜 · 制作进度 · 成片审核', '▷', 'violet', '进入制作空间'),
        ('library', '03 / OPERATE', '管理内容运营', '作品同步 · 人工发布 · 互动反馈', '◫', 'blue', '打开作品库'),
    ]
    visible = [entry for entry in entries if entry[0] in destinations]
    for column, entry in zip(st.columns(len(visible)), visible):
        key, index, title, description, glyph, tone, action = entry
        with column:
            st.markdown(f'<div class="studio-feature studio-feature--{tone}">'
                        f'<div class="studio-feature-index">{index}</div>'
                        f'<span class="studio-feature-glyph" aria-hidden="true">{glyph}</span>'
                        f'<h3>{title}</h3><p>{description}</p></div>', unsafe_allow_html=True)
            st.page_link(destinations[key], label=action, icon=':material/arrow_forward:', width='stretch')

    section_header('最近制作', '继续查看分镜、生成回执与审核结果')
    scope = st.session_state.get('active_account_uuid', '*')
    projects = recent_projects(account_uuid=None if scope == '*' else scope)
    if not projects:
        with st.container(border=True):
            st.markdown('**你的第一部作品，从这里开始**')
            st.caption('尚未发现制作项目。可先进入选题调研整理方向，已有制作批次会自动展示在这里。')
    else:
        for column, project in zip(st.columns(3), projects):
            with column, st.container(border=True, key=f'studio_project_{project["batch"]}'):
                if project['image']:
                    st.image(str(project['image']), width='stretch')
                else:
                    st.markdown('<div class="studio-empty" aria-label="暂无分镜预览">▤</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="studio-project-title">{escape(project["title"])}</div>', unsafe_allow_html=True)
                st.caption(f'{project["shots"]} 个镜头 · {project["date"]} 记录 · {project["status"]}')
                if st.button('查看制作详情 ↗', key=f'project_{project["batch"]}', width='stretch'):
                    st.session_state['studio_selected_batch'] = project['batch']
                    st.switch_page(destinations['production'])

    section_header('运营一览', '全部账号汇总' if scope == '*' else '当前账号作品与互动数据')
    from src.services.video_service import count_videos
    from src.services.comment_service import count_comments, count_replied_comments, get_reply_rate
    for column, label, value in zip(st.columns(4),
                                   ['已发布作品', '收到评论', '已回复评论', '评论回复率'],
                                   [count_videos(status='published', account_uuid=scope) if scope != '*' else count_videos(status='published'),
                                    count_comments(account_uuid=None if scope == '*' else scope) or 0,
                                    count_replied_comments(account_uuid=None if scope == '*' else scope) or 0,
                                    f'{get_reply_rate(account_uuid=None if scope == "*" else scope) or 0:.1f}%']):
        column.metric(label, value)
    st.markdown('<div class="studio-note">制作提示 · 当前作品需逐项检查并通过审核；发布使用已审核的本地成片。自动生成并发布流程暂未开放。</div>', unsafe_allow_html=True)
