"""Chinese capability catalogue with introductions before runtime details."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import streamlit as st

from src.web.components.ui import page_header, section_header

# Display metadata only. Registry identifiers and execution policy are unchanged.
SKILL_DISPLAY = {
 'rag_search': ('知识检索', '知识与记忆', '从知识库查找与问题相关的内容，为回答和脚本提供依据。'),
 'generate_audio': ('文本配音', '内容制作', '把文字或关键词转换为配音音频，可使用已配置的语音服务。'),
 'publish_douyin': ('发布抖音作品', '账号与运营', '通过已绑定的抖音账号发布经过审核的视频。'),
 'sync_douyin_videos': ('同步账号作品', '账号与运营', '将已绑定账号的作品列表同步到本地作品库。'),
 'fetch_comments': ('采集作品评论', '账号与运营', '读取指定作品或账号作品的评论，供运营分析与回复使用。'),
 'auto_reply_comments': ('自动回复评论', '账号与运营', '此能力已停用。当前外部评论回复需要人工确认。'),
 'get_user_preferences': ('读取用户偏好', '知识与记忆', '读取用户保存的内容方向与使用偏好。'),
 'update_user_preferences': ('更新用户偏好', '知识与记忆', '保存常用配音方式、内容主题等个性化设置。'),
 'fanqie_login': ('番茄账号登录', '素材采集', '打开番茄创作者中心，完成后续素材操作所需的登录。'),
 'fanqie_apply_promotion': ('申请作品推广', '素材采集', '按书名和内容类型申请番茄小说推广。'),
 'fanqie_fetch_book': ('采集小说内容', '素材采集', '按书名获取小说元信息与指定数量的章节。'),
 'fanqie_list_promotions': ('查看推广列表', '素材采集', '读取推广申请状态，并可同步本地任务记录。'),
 'fanqie_list_books': ('查看已采集小说', '素材采集', '浏览本地已采集的小说素材。'),
 'fanqie_batch_add': ('添加采集书单', '素材采集', '将书名加入待采集清单，供后续批量处理。'),
 'fanqie_batch_list': ('查看采集清单', '素材采集', '按状态查看清单中的书籍与采集进度。'),
 'fanqie_batch_run': ('执行批量采集', '素材采集', '依次采集清单中的待处理小说，记录每本书的结果。'),
 'fanqie_batch_enqueue': ('提交采集队列', '素材采集', '将待采集小说交给后台队列异步处理。'),
 'fanqie_batch_seed': ('导入初始书单', '素材采集', '从本地清单文件导入待采集书籍。'),
 'fanqie_batch_fetch_filtered': ('筛选并采集小说', '素材采集', '按榜单与筛选条件选书，然后采集章节内容。'),
 'fanqie_batch_enqueue_filtered': ('筛选并排队采集', '素材采集', '按榜单条件选书并加入后台队列，便于持续跟踪。'),
 'douyin_maintenance': ('账号运营维护', '账号与运营', '按已授权的模式执行账号健康检查或运营维护。'),
 'douyin_warmup': ('账号维护兼容入口', '账号与运营', '旧版账号维护名称，实际转交账号运营维护能力处理。'),
 'douyin_warmup_login': ('账号登录与验真', '账号与运营', '辅助管理员绑定运营账号，并人工确认昵称与身份。'),
 'douyin_warmup_account_list': ('查看运营账号', '账号与运营', '查看运营账号、身份绑定和登录健康状态。'),
 'douyin_warmup_report': ('查看维护报告', '账号与运营', '查看指定账号的健康检查与运营维护记录。'),
 'import_knowledge': ('导入知识素材', '知识与记忆', '把本地书籍导入知识库，供后续检索使用。'),
 'reply_single_comment': ('回复单条评论', '账号与运营', '向指定作品的一条评论发送已确认的回复。'),
 'open_upload_page': ('打开作品上传页', '账号与运营', '打开抖音上传页面，交由用户手动上传作品。'),
 'run_bash_command': ('执行系统命令', '系统工具', '执行指定命令，是需要谨慎使用的系统工具。'),
 'investigate_problems': ('调查未解决问题', '系统工具', '为未解决的问题生成调查摘要并保存到问题记录。'),
}


def skill_display(skill):
    return SKILL_DISPLAY.get(skill.name, (skill.description.split('，')[0][:18] or '扩展能力',
                                         '其他能力', skill.description or '暂无介绍。'))


def skill_label(name):
    return SKILL_DISPLAY.get(name, (name or '未记录能力', '', ''))[0]


def call_counts(calls):
    return Counter('成功' if c.tool_success is True else '失败' if c.tool_success is False else '未记录结果' for c in calls)


def page_skill_center():
    page_header('技能中心', '技能是 AI 助手可调用的具体能力。先了解用途，再查看调用规则与运行记录。',
                icon='✦', eyebrow='CAPABILITY STUDIO')
    from src.agent.registry import SkillRegistry
    try:
        skills = SkillRegistry().list_all()
    except Exception as exc:
        st.error(f'能力目录暂时无法读取：{exc}')
        return
    overview, runtime = st.tabs(['能力与设置', '运行记录'])
    with overview, st.container(key='skill_layout'):
        catalogue, details = st.columns([1.5, 1], gap='large')
        with catalogue:
            section_header('选择你想了解的能力', '中文名称与简介用于浏览；内部标识保留在详情中。')
            search = st.text_input('搜索能力', placeholder='例如：配音、评论、知识检索', key='skill_search')
            groups = ['全部', *dict.fromkeys(skill_display(s)[1] for s in skills)]
            filters = st.columns(2)
            group = filters[0].selectbox('能力分类', groups, key='skill_group')
            matches = [s for s in skills if (group == '全部' or skill_display(s)[1] == group)
                       and (not search or search.casefold() in (' '.join(skill_display(s)) + s.name).casefold())]
            if not matches:
                st.info('没有匹配的能力，试试其他关键词或分类。')
            else:
                page_count = (len(matches) + 5) // 6
                page = filters[1].selectbox('目录页', range(page_count), format_func=lambda i: f'第 {i+1} / {page_count} 页 · 共 {len(matches)} 项', key=f'skill_page_{group}_{search}')
                if st.session_state.get('skill_selected') not in {s.name for s in matches}:
                    st.session_state['skill_selected'] = matches[0].name
                visible = matches[page*6:page*6+6]
                for offset in range(0, len(visible), 2):
                    for col, skill in zip(st.columns(2), visible[offset:offset+2]):
                        name, category, intro = skill_display(skill)
                        with col, st.container(border=True):
                            st.markdown(f'**{name}**')
                            st.caption(intro)
                            if st.button('查看介绍与设置', key=f'skill_card_{skill.name}', width='stretch',
                                         type='primary' if st.session_state['skill_selected'] == skill.name else 'secondary'):
                                st.session_state['skill_selected'] = skill.name
                                st.rerun()
        with details:
            selected = next((s for s in matches if s.name == st.session_state.get('skill_selected')), None)
            if selected:
                _render_skill_detail(selected)
    with runtime:
        _render_runtime(skills)


def _render_skill_detail(skill):
    name, category, intro = skill_display(skill)
    with st.container(border=True, key='skill_detail_panel'):
        st.caption(category + ' / 能力详情')
        st.subheader(name)
        st.write(intro)
        if skill.name == 'auto_reply_comments':
            st.warning('已停用：不能通过本页恢复或执行。')
        else:
            st.caption('已注册仅表示助手可识别此能力；可执行性取决于权限、依赖与账号状态。')
        section_header('调用设置', '集中展示当前规则；此处只读，点击卡片不会运行能力。')
        a, b = st.columns(2)
        a.metric('执行前确认', '需要' if skill.requires_confirmation else '不要求')
        b.metric('超时上限', f'{skill.timeout_s:g} 秒' if skill.timeout_s else '不限制')
        st.write(f'失败重试：{skill.retries} 次　·　重复调用保护：{"启用" if skill.idempotent else "未启用"}')
        with st.expander('参数与使用示例'):
            params = [p for p in skill.params if not p.is_absorber()]
            if params:
                st.dataframe([{'参数': p.name, '用途': p.description or '未提供说明',
                               '必填': '是' if p.required else '否', '类型': p.type.value,
                               '默认值': str(p.default) if p.default is not None else '—'} for p in params],
                             hide_index=True, width='stretch')
            else:
                st.caption('无显式参数。')
            for example in skill.examples:
                st.code(example, language=None)
            if not skill.examples:
                st.caption('当前注册表未提供示例。')
        with st.expander('实现与维护信息'):
            st.code(skill.name, language=None)
            st.text(skill.description)
            st.caption('重试条件：' + ('、'.join(skill.retry_on) or '无'))
            st.caption('这些规则由技能注册配置维护，本页不改变执行策略。')


def _render_runtime(skills):
    section_header('近期调用质量', '统计范围：最近 7 天内最新 50 次记录；没有结果的记录单独统计。')
    chosen = st.selectbox('查看能力', ['全部', *[s.name for s in skills]],
                          format_func=lambda name: '全部能力' if name == '全部' else skill_label(name), key='skill_runtime_filter')
    try:
        from src.shared.database import SessionLocal
        from src.memory.models import ConversationMessage
        from src.memory.error_review_model import ErrorReview
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        with SessionLocal() as session:
            query = session.query(ConversationMessage).filter(ConversationMessage.skill_name.isnot(None), ConversationMessage.created_at >= cutoff)
            if chosen != '全部':
                query = query.filter(ConversationMessage.skill_name == chosen)
            calls = query.order_by(ConversationMessage.created_at.desc()).limit(50).all()
            counts = call_counts(calls)
            for col, label, value in zip(st.columns(4), ['记录数', '成功', '失败', '未记录结果'], [len(calls), counts['成功'], counts['失败'], counts['未记录结果']]):
                col.metric(label, value)
            if calls:
                st.dataframe([{'能力': skill_label(c.skill_name), '状态': '成功' if c.tool_success is True else '失败' if c.tool_success is False else '未记录结果',
                               '时间': c.created_at.strftime('%m-%d %H:%M') if c.created_at else '—',
                               '错误摘要': c.tool_error or '—'} for c in calls], hide_index=True, width='stretch')
            else:
                st.info('该范围内暂无调用记录。')
            query = session.query(ErrorReview).filter(ErrorReview.last_seen_at >= cutoff)
            if chosen != '全部':
                query = query.filter(ErrorReview.location == 'skill:' + chosen)
            reviews = query.order_by(ErrorReview.occurrence_count.desc()).limit(50).all()
            section_header('错误诊断', '最近 7 天出现过的诊断，最多 50 条；次数为该诊断累计次数。')
            if reviews:
                st.dataframe([{'能力': skill_label(r.location.removeprefix('skill:')),
                               '严重程度': {'critical':'严重','high':'高','medium':'中','low':'低'}.get(r.severity,r.severity),
                               '累计次数': r.occurrence_count, '问题摘要': r.summary or '—',
                               '建议处理': r.suggested_fix or '—'} for r in reviews], hide_index=True, width='stretch')
                with st.expander('诊断技术详情'):
                    st.dataframe([{'能力标识': r.location, '错误代码': r.error_type,
                                   '诊断分类': r.category, '问题分组': r.cluster_key,
                                   '首次出现': r.first_seen_at.strftime('%Y-%m-%d %H:%M') if r.first_seen_at else '—',
                                   '最近出现': r.last_seen_at.strftime('%Y-%m-%d %H:%M') if r.last_seen_at else '—'}
                                  for r in reviews], hide_index=True, width='stretch')
            else:
                st.info('该范围内暂无错误诊断。')
    except Exception as exc:
        st.error(f'运行记录暂时无法读取：{exc}')
