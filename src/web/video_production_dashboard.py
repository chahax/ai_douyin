"""Read-only, artifact-backed video production workflow and review dashboard."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import streamlit as st
from src.web.components.ui import page_header
from src.web.production_insights import render_analysis, render_style, display_time

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'data' / 'video_generation'


def local_file(root: Path, value: str) -> Path | None:
    """Only expose explicitly registered artifacts inside the project data folder."""
    if not value:
        return None
    path = (root / value).resolve()
    if not path.is_relative_to((root / 'data').resolve()) or not path.is_file():
        return None
    return path


def load_run(manifest_path: Path, root: Path = ROOT) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    folder = manifest_path.parent
    shots, errors = [], []
    for name in manifest['shots']:
        # Shot ids are filenames, never arbitrary paths supplied by a manifest.
        if not isinstance(name, str) or not name.isalnum():
            errors.append('无效镜头编号')
            continue
        try:
            receipt = json.loads((folder / f'{name}.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            receipt = {'status': 'pending_submission'}
        except (OSError, ValueError) as exc:
            receipt = {}
            errors.append(f'{name} 回执无法读取：{exc}')
        video = local_file(root, str(folder / f'{name}.mp4'))
        original_video, delivery_speed = video, 1.
        selected = manifest.get('selected_deliveries', {}).get(name, {})
        pending = manifest.get('pending_delivery_review', {})
        if not selected and pending.get('shot') == name:
            selected = pending
        if selected.get('status') in {'passed', 'pending'}:
            delivery = local_file(root, selected.get('video', ''))
            if delivery and hashlib.sha256(delivery.read_bytes()).hexdigest() == selected.get('video_sha256'):
                video, delivery_speed = delivery, selected.get('speed', 1.)
            else:
                errors.append(f'{name} 登记的视频版本缺失或发生变化')
        status = receipt.get('status', 'missing')
        completed = status in {'completed_on_web', 'succeeded', 'downloaded'}
        shots.append(dict(id=name, prompt=receipt.get('prompt', ''),
                          submitted=bool(receipt.get('url') or receipt.get('submit_id')), completed=completed,
                          downloaded=completed and video is not None,
                          video=video, original_video=original_video, delivery_speed=delivery_speed,
                          delivery_status=selected.get('status'),
                          status=status, created_at=receipt.get('created_at', ''),
                          cost=receipt.get('cost_credits', 0),
                          provider=receipt.get('provider',manifest.get('provider','dreamina_cli')),
                          completion_tokens=(receipt.get('usage') or {}).get('completion_tokens'),
                          references=receipt.get('references', []),
                          first_frame=local_file(root,receipt.get('first_frame','')),
                          reused=bool(receipt.get('reused_from')),
                          progress=receipt.get('latest_progress', [])))
    artifacts = {key: local_file(root, manifest.get(key, '')) for key in
                 ('script', 'merged_video', 'test_video', 'pacing_preview', 'direction_revision', 'stage_diagram',
                  'comparison', 'contact_sheet', 'review', 'probe', 'source_audit')}
    # Existing scripts already have provenance sidecars; future batches inherit them.
    if not artifacts['source_audit'] and artifacts['script']:
        artifacts['source_audit'] = local_file(root, str(artifacts['script'].with_suffix('.audit.json')))
    provenance = {}
    if artifacts['source_audit']:
        try:
            provenance = json.loads(artifacts['source_audit'].read_text(encoding='utf-8'))
            if not isinstance(provenance, dict) or not isinstance(provenance.get('source_videos', []), list):
                raise ValueError('来源审计格式错误')
        except (OSError, ValueError) as exc:
            provenance = {}
            errors.append(f'来源审计无法解析：{exc}')
    probe = {}
    if artifacts['probe']:
        try:
            probe = json.loads(artifacts['probe'].read_text(encoding='utf-8'))
        except (OSError, ValueError):
            errors.append('媒体检测报告无法解析')
    return dict(manifest=manifest, folder=folder, shots=shots, artifacts=artifacts,
                probe=probe, errors=errors, provenance=provenance)


def workflow_steps(run: dict) -> list[tuple[str, str]]:
    shots, artifacts = run['shots'], run['artifacts']
    total = len(run['manifest']['shots'])
    count = lambda key: sum(bool(s[key]) for s in shots)
    review = run['manifest'].get('review_result', 'pending')
    return [
        ('灵感来源', f'{len(run.get("provenance", {}).get("source_videos", []))} 条记录'
         if run.get('provenance', {}).get('source_videos') else '未记录'),
        ('剧本', '已保存' if artifacts['script'] else '文件缺失'),
        ('提交', f'{count("submitted")}/{total} 有回执'),
        ('生成', f'{count("completed")}/{total} 已完成'),
        ('采集', f'{count("downloaded")}/{total} 已下载'),
        ('合并', '已完成' if artifacts['merged_video'] else '待合并'),
        ('审核', {'failed': '未通过', 'passed': '通过', 'accepted_by_user':'用户认可', 'pending': '待审核'}.get(review, '待审核')
         if artifacts['review'] else '报告缺失'),
    ]


def download(path: Path | None, label: str, key: str) -> None:
    if path:
        st.download_button(label, path.read_bytes(), file_name=path.name, key=key)


def render_sources(run: dict) -> None:
    audit = run['provenance']
    sources = audit.get('source_videos', [])
    st.subheader('剧本灵感与生成依据')
    if not sources:
        st.info('未记录可追溯的灵感来源，不能仅凭剧本内容推定来源。')
        return
    st.caption('以下来自生成时保存的本地审计快照，不是本次实时抓取或重新核验。')
    opportunity = audit.get('opportunity', {})
    st.write('选题方向：' + str(opportunity.get('title', '未记录')))
    st.caption('选题记录时间：' + str(opportunity.get('created_at', '未记录')))
    st.write(f'筛选依据：近 {audit.get("window_days", "未记录")} 天，账号相关性门槛 {audit.get("min_relevance", "未记录")}，再筛选组内高展示指标样本。')
    st.warning('页面展示指标不等同于官方播放量。热门来源只用于创作灵感，不作为法律依据。')
    if all(s.get('media_access_mode') == 'metadata_only' for s in sources):
        st.warning(f'媒体级分析覆盖 0/{len(sources)}：仅有标题、作者等元数据，没有视频画面或转写分析。')
    primary = run['manifest'].get('primary_inspiration_item_id')
    for source in sources:
        with st.container(border=True):
            if source.get('item_id') == primary:
                st.write('主要主题线索（本次按题材匹配标注，原审计未记录单一主来源）')
            st.write(source.get('title', '未记录标题'))
            st.caption(f'作者：{source.get("author", "未记录")} · 发布时间（原记录）：{source.get("published_at", "未记录")}')
            st.caption(f'页面展示值：{source.get("visible_metric", "未记录")} · 指标类型：{source.get("metric_kind", "未记录")} · 采集模式：{source.get("media_access_mode", "未记录")}')
            video_id = str(source.get('video_id', ''))
            if video_id.isdigit():
                st.link_button('查看抖音原视频', 'https://www.douyin.com/video/' + video_id)
                st.caption('链接由已保存的视频 ID 构建，可用性未重新核验。')
    st.subheader('从来源到剧本')
    traits = audit.get('overlap_profile', {}).get('traits', [])
    if traits:
        st.dataframe([{'参考特征': t.get('value'), '支持样本数': t.get('support_video_count'),
                       '证据级别': t.get('evidence_level')} for t in traits], hide_index=True, width='stretch')
    expansion = audit.get('creative_expansion', {})
    dimensions = {'scene': '场景', 'character_appearance': '角色外形', 'blocking': '站位',
                  'action': '动作', 'emotion_and_performance': '表演', 'dialogue': '对白',
                  'camera': '机位', 'audio': '音频', 'continuity': '连续性'}
    original = expansion.get('original_dimensions', [])
    if original:
        st.info('原创扩写维度：' + '、'.join(dimensions.get(d, d) for d in original) + '；不是已观察到的原视频细节。')
    st.caption(run['manifest'].get('script_generation_note', '剧本生成方式或模型未记录。'))
    with st.expander('来源审计记录与下载'):
        st.code(str(run['artifacts']['source_audit']), language=None)
        download(run['artifacts']['source_audit'], '下载来源审计', 'production_source_audit')


def _render_assemblies(paths: list[Path]) -> None:
    from src.services.production_registry import read_record
    st.subheader('完整视频与成片审核')
    path = st.selectbox('成片版本', paths, format_func=lambda p: p.parent.name, key='production_assembly')
    record = read_record(path)
    video = local_file(ROOT, record.get('video', ''))
    review = local_file(ROOT, record.get('actual_review', ''))
    review_record = read_record(review) if review else {}
    decision = review_record.get('decision', 'pending')
    labels = {'passed': '审核记录：通过', 'passed_with_previously_accepted_limitations': '审核记录：通过，保留已接受的局限', 'failed': '审核记录：未通过'}
    cols = st.columns(3)
    cols[0].metric('成片时长', f"{record['duration_seconds']:.3f} 秒" if record.get('duration_seconds') is not None else '未记录')
    cols[1].metric('质量状态', labels.get(decision, '待核对审核记录'))
    cols[2].metric('发布状态', '未核实平台回执')
    st.caption('合成完成时间（UTC+8）：' + display_time(record.get('finished_at_bjt')))
    if video:
        st.video(str(video))
        st.caption(str(video))
        download(video, '下载完整视频', 'production_assembly_video')
    else:
        st.warning('合成记录中的视频文件缺失。')
    with st.expander('成片审核范围与原始记录'):
        st.caption('这里只展示已有审核结论，不代表本次重新听看审核。')
        if review_record:
            st.json(review_record)
        else:
            st.info('缺少独立成片审核记录，不能仅凭合成状态认定通过。')
        download(path, '下载合成记录', 'production_assembly_receipt')


def page_video_production() -> None:
    page_header('视频制作流程', '从灵感来源到成片审核，点击节点查看依据、内容与文件。只读展示，不触发付费生成。', icon='🎬', eyebrow='PRODUCTION / EVIDENCE')
    if st.button('刷新本地结果', key='production_refresh'):
        st.rerun()
    from src.services.production_registry import list_projects
    from src.operations_accounts import AccountProfileRepository
    from src.web.components.account_scope import select_account_scope
    scope = select_account_scope(AccountProfileRepository().list_active(status=None),
                                 key='production_account_scope', allow_unassigned=True)
    if scope and scope not in ('*', '?'):
        from src.web.production_learning_dashboard import render_experiments
        with st.expander('观看数据驱动的生产改进'):
            render_experiments(scope)
    projects = list_projects(ROOT, account_uuid=scope)
    if not projects:
        st.info('暂无制作记录。已有 production.json 和 assembly.json 会自动归档。')
        return
    preferred = st.session_state.pop('studio_selected_batch', None)
    keys = [p['key'] for p in projects]
    if preferred in keys:
        st.session_state['production_project'] = preferred
    if st.session_state.get('production_project') not in keys:
        st.session_state['production_project'] = keys[0]
    by_key = {p['key']: p for p in projects}
    project_id = st.selectbox('内容项目 / 剧本稿次', keys, key='production_project',
                              format_func=lambda key: by_key[key]['title'] + f" · {len(by_key[key]['attempts'])} 份制作记录 / {len(by_key[key]['assemblies'])} 份合成记录")
    project = by_key[project_id]
    if project['assemblies']:
        _render_assemblies(project['assemblies'])
    manifests = project['attempts']
    if not manifests:
        return
    if st.session_state.get('production_batch') not in manifests:
        st.session_state['production_batch'] = manifests[0]
    selected = st.selectbox('分段与历史生成记录', manifests, key='production_batch', format_func=lambda p: p.parent.name)
    try:
        run = load_run(selected)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f'制作记录无法读取：{exc}')
        return
    manifest, artifacts = run['manifest'], run['artifacts']
    st.subheader(manifest.get('title', selected.parent.name))
    st.caption(manifest.get('input_mode', ''))
    for error in run['errors']:
        st.warning(error)
    if manifest.get('generation_error'):
        st.error('生成接口拒绝了请求：'+str(manifest['generation_error']))
    status_map = dict(workflow_steps(run))
    nodes = [('灵感来源', status_map['灵感来源']), ('分析依据', '时间 · 占比 · 来源'),
             ('剧本内容', status_map['剧本']), ('分镜与采集', status_map['生成'] + ' / ' + status_map['采集']),
             ('合并成片', status_map['合并']), ('一致性审核', status_map['审核']),
             ('本地文件', '预览 · 下载 · 路径'), ('页面风格', '基线 · 对比')]
    if st.session_state.get('production_section') not in dict(nodes):
        st.session_state['production_section'] = '分析依据'
    from src.web.components.flow_graph import flow_graph
    from src.web.production_visuals import build_production_graph
    graph_nodes, graph_edges = build_production_graph(nodes)
    selection = flow_graph(graph_nodes, graph_edges, key='production_graph_' + selected.parent.name,
                           selected=st.session_state['production_section'],
                           title='制作路径与审核依据',
                           description='点击节点切换下方完整内容，点击连线了解阶段间传递什么。文件归档与页面风格是辅助入口。')
    if selection and selection['kind'] == 'node':
        st.session_state['production_section'] = selection['id']
    if manifest.get('review_result') == 'accepted_by_user':
        st.success('用户已认可当前测试片。技术观察保留在审核记录中，后续按用户认可的效果继续。')
    elif manifest.get('review_result') == 'failed':
        st.error('生成已完成，但一致性审核未通过。不能将“有成片”视为“可发布”。')
    elif manifest.get('review_result') == 'passed' and artifacts['review']:
        st.success('已有审核通过记录，请查看下方审核范围。')
    else:
        st.info('待审核：尚无完整的质量结论。')
    cols = st.columns(3)
    if manifest.get('provider')=='ark_api':
        tokens=[s['completion_tokens'] for s in run['shots'] if s['completion_tokens'] is not None]
        cols[0].metric('API 返回的生成用量', f'{sum(tokens):,} tokens' if tokens else '待接口返回')
        st.caption('火山方舟 API 按账户账单计费；这里不使用即梦网页积分或 BytePlus 美元估价。')
    else:
        cols[0].metric('本批记录消耗', f'{sum(s["cost"] for s in run["shots"])} 积分')
    cols[1].metric('生成参数', manifest.get('settings_label', '未记录'))
    duration = run['probe'].get('format', {}).get('duration')
    cols[2].metric('合并时长', f'{float(duration):.2f} 秒' if duration else '未检测')
    view = st.session_state['production_section']
    st.divider()
    if view == '分析依据':
        render_analysis(run, ROOT)
    if view == '页面风格':
        render_style(ROOT)
    if view == '灵感来源':
        render_sources(run)
    if view == '剧本内容':
        if artifacts['script']:
            st.code(str(artifacts['script']), language=None)
            download(artifacts['script'], '下载完整剧本', 'production_script')
            st.markdown(artifacts['script'].read_text(encoding='utf-8'))
        else:
            st.warning('剧本文件缺失')
    if view == '分镜与采集':
        if artifacts['direction_revision']:
            with st.expander('下一版的空间与动作修订', expanded=True):
                st.markdown(artifacts['direction_revision'].read_text(encoding='utf-8'))
                if artifacts['stage_diagram']:
                    st.image(str(artifacts['stage_diagram']))
        for shot in run['shots']:
            with st.container(border=True):
                st.subheader(shot['id'])
                billing=(f"API 用量：{shot['completion_tokens'] if shot['completion_tokens'] is not None else '待返回'} tokens"
                         if shot['provider']=='ark_api' else f"{shot['cost']} 积分")
                st.caption(f'状态：{shot["status"]} · 提交时间（北京时间）：{display_time(shot["created_at"])} · {billing}')
                if shot['progress']:
                    st.write('最近采集状态：' + ' / '.join(shot['progress']))
                left, right = st.columns([1, 2])
                with left:
                    if shot['downloaded']:
                        if shot['delivery_speed'] != 1.:
                            label = '已认可的成片版本' if shot['delivery_status']=='passed' else '待审核预览'
                            st.caption(f"{label} · 声画同步 {shot['delivery_speed']:g} 倍速")
                        st.video(str(shot['video']))
                        download(shot['video'], '下载此镜头', 'production_' + shot['id'])
                        if shot['original_video'] and shot['original_video'] != shot['video']:
                            with st.expander('查看生成原片'):
                                st.video(str(shot['original_video']))
                        tail=local_file(ROOT,str(run['folder']/(shot['id']+'.last_frame.png')))
                        if tail:
                            with st.expander('接口返回的尾帧，可用于后续首帧'):
                                st.image(str(tail))
                                download(tail,'下载原始尾帧','tail_'+shot['id'])
                                st.caption('连续机位可衔接；切换特写时需准备匹配新机位的首帧。')
                    else:
                        st.info('尚无已验证的本地成片')
                with right:
                    st.write('实际提交提示词')
                    st.text(shot['prompt'] or '无提示词记录')
                    if shot['first_frame']:
                        st.caption('实际输入：已审核首帧图片，使用接口 first_frame 功能。')
                    else:
                        st.caption(f'参考视频数：{len(shot["references"])}；0 表示仅文字输入。')
                    if shot['reused']:
                        st.caption('复用既有生成结果，本批没有重复提交此镜头。')
                    frame = local_file(ROOT, str(run['folder'] / (shot['id'] + '_frames.jpg')))
                    if frame:
                        with st.expander('动作抽帧证据'):
                            st.image(str(frame))
    if view == '合并成片':
        if artifacts['test_video']:
            st.subheader('首镜测试片')
            st.video(str(artifacts['test_video']))
            download(artifacts['test_video'],'下载首镜测试','production_test_video')
        if artifacts['merged_video']:
            preview, info = st.columns([1, 2])
            with preview:
                st.video(str(artifacts['merged_video']))
            with info:
                st.write('镜头顺序：' + ' → '.join(manifest['shots']))
                st.info(manifest.get('audio_note', '音频状态未记录'))
                if manifest.get('subtitle_note'):
                    st.caption(manifest['subtitle_note'])
                download(artifacts['merged_video'], '下载合并视频', 'production_merged')
                original=local_file(ROOT,manifest.get('merged_video_original',''))
                if original:
                    download(original,'下载原始合并版','production_merged_original')
                st.code(str(artifacts['merged_video']), language=None)
        elif not artifacts['test_video'] and not artifacts['pacing_preview']:
            st.info('合并文件尚未生成或已被移走')
        if artifacts['pacing_preview']:
            st.subheader('整片节奏预览' if manifest.get('latest_assembly_preview') else '动作节奏对比预览')
            st.caption(manifest.get('pacing_preview_note', '只用于比较节奏，原始画面问题仍需修正。'))
            st.video(str(artifacts['pacing_preview']))
            download(artifacts['pacing_preview'], '下载节奏预览', 'production_pacing_preview')
    if view == '一致性审核':
        st.caption('审核来自本地人工视觉检查报告，不是自动人脸识别评分。')
        if artifacts['comparison']:
            st.image(str(artifacts['comparison']), caption='从左到右 S01、S02、S03，各镜头第 2 秒')
        if artifacts['review']:
            st.markdown(artifacts['review'].read_text(encoding='utf-8'))
            download(artifacts['review'], '下载审核报告', 'production_review')
        else:
            st.info('尚无审核报告')
    if view == '本地文件':
        st.write('本批输出目录')
        st.code(str(run['folder']), language=None)
        labels = {'script': '完整剧本', 'merged_video': '合并成片', 'test_video':'首镜测试片', 'pacing_preview': '节奏预览',
                  'direction_revision':'空间与动作修订', 'stage_diagram':'固定座位与机位图', 'comparison': '角色对比图',
                  'contact_sheet': '动作抽帧总览', 'review': '审核报告', 'probe': '媒体参数', 'source_audit': '来源审计'}
        rows = [{'文件用途': labels[key], '本地位置': str(path) if path else '缺失'} for key, path in artifacts.items()]
        rows += [{'文件用途': s['id'], '本地位置': str(s['video']) if s['video'] else '缺失'} for s in run['shots']]
        st.dataframe(rows, hide_index=True, width='stretch')
        for key, path in artifacts.items():
            download(path, '下载' + labels[key], 'archive_' + key)
        st.caption('登录资料不在此处展示；页面不会读取或导出 Chrome Cookies、密码或浏览器指纹。')
