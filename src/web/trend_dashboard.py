"""Streamlit page for native trend discovery and operation feedback."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import streamlit as st

from src.operations_accounts import (
    AccountProfile,
    AccountProfileRepository,
    stable_account_uuid,
)
from src.trend_intelligence.domain import get_default_domain_registry
from src.trend_intelligence.content_analysis import (
    ContentAnalysisBatchService,
    ContentAnalysisRequest,
)
from src.trend_intelligence.feedback import OperationsFeedbackService
from src.trend_intelligence.providers import (
    DOUYIN_SORTS,
    DouyinWebTrendProvider,
    TrendCollectionRequest,
    build_douyin_trend_session,
    estimate_douyin_planned_pages,
)
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.opportunity import ContentOpportunityService
from src.trend_intelligence.service import TrendOperationsService
from src.trend_intelligence.temporal import TemporalTrendService
from src.trend_intelligence.source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourceProvider,
)
from src.web.components.ui import page_header, section_header


COLLECTED_FIELDS = frozenset(
    {
        "video_id",
        "url",
        "title",
        "author",
        "keyword",
        "sort",
        "rank",
        "displayed_metrics",
        "published_at",
        "hashtags",
        "tag_relationships",
        "tag_traffic_snapshots",
    }
)
MAX_PAGES_PER_RUN = 30


def page_trend_operations() -> None:
    page_header(
        "热门选题",
        "原生采集授权页面可见样本，生成可解释选题卡，并用发布表现调整下一期策略。",
        icon="⌁",
        eyebrow="TREND OPERATIONS",
    )
    repository = TrendRepository()
    account_repository = AccountProfileRepository()
    service = TrendOperationsService(repository=repository)
    summary = repository.summary()

    metric_columns = st.columns(5)
    for column, label, value in zip(
        metric_columns,
        ("采集批次", "样本实体", "选题卡", "已批准", "效果快照"),
        (
            summary["runs"],
            summary["items"],
            summary["briefs"],
            summary["approved"],
            summary["snapshots"],
        ),
    ):
        column.metric(label, value)

    account_tab, collect_tab, briefs_tab, feedback_tab = st.tabs(
        ["账号策略", "采集与分析", "选题卡", "运营复盘"]
    )
    with account_tab:
        _render_account_profiles(account_repository)
    with collect_tab:
        _render_collection(repository, service, account_repository)
    with briefs_tab:
        _render_briefs(repository, service, account_repository)
    with feedback_tab:
        _render_feedback(repository)


def _render_collection(
    repository: TrendRepository,
    service: TrendOperationsService,
    account_repository: AccountProfileRepository,
) -> None:
    section_header("原生热门样本采集", "采集与发布使用两个隔离的浏览器目录。")
    st.info(
        "一次采集只计算热门样本分；同一视频至少跨两个采集批次后，才计算增长趋势。"
    )
    account_profiles = account_repository.list_active()
    account_profile: AccountProfile | None = None
    if account_profiles:
        selected_account_key = st.selectbox(
            "分析账号",
            [item.account_key for item in account_profiles],
            format_func=lambda value: _account_profile_label(account_profiles, value),
            key="trend_analysis_account",
        )
        account_profile = next(
            item for item in account_profiles if item.account_key == selected_account_key
        )
        st.caption(
            f"领域策略：{account_profile.domain_strategy_id}/{account_profile.strategy_version} · "
            f"账号策略版本：v{account_profile.profile_version}"
        )
        default_keywords = ",".join(account_profile.seed_keywords)
    else:
        st.warning("尚未配置运营账号。请先在“账号策略”页创建账号策略版本。")
        default_keywords = "法律,小说"

    if account_profile is not None:
        with st.expander("账号领域分批采集计划", expanded=False):
            wave_label = st.selectbox(
                "采集波次",
                ["baseline", "discovery", "momentum"],
                format_func=lambda value: {
                    "baseline": "基线：根关键词 + 标签族（每天）",
                    "discovery": "发现：领域扩展词（每天）",
                    "momentum": "追踪：高潜词复采（每 6 小时）",
                }[value],
                key="trend_plan_wave",
            )
            hot_text = st.text_input(
                "高潜追踪词",
                value=",".join(account_profile.seed_keywords),
                disabled=wave_label != "momentum",
                key="trend_plan_hot_keywords",
            )
            if st.button("生成并保存分批计划", key="trend_create_collection_plan"):
                try:
                    plan = service.create_collection_plan(
                        account_profile,
                        wave_kind=wave_label,
                        hot_keywords=(
                            _split_keywords(hot_text)
                            if wave_label == "momentum"
                            else None
                        ),
                    )
                except ValueError as exc:
                    st.error(f"计划生成失败：{exc}")
                else:
                    st.session_state["trend_collection_plan"] = plan
                    st.success(
                        f"已生成 {len(plan.batches)} 批、预计 {plan.estimated_pages} 页；"
                        f"建议每 {plan.repeat_interval_hours} 小时执行一轮。"
                    )
            plan = st.session_state.get("trend_collection_plan")
            if plan is not None and plan.account_uuid == account_profile.account_uuid:
                st.dataframe(
                    [
                        {
                            "批次": item.sequence,
                            "波次": item.wave_kind,
                            "关键词": "、".join(item.keywords),
                            "排序": "、".join(item.sorts),
                            "标签族扩展": "是" if item.expand_related_tags else "否",
                            "预计页面": item.estimated_pages,
                        }
                        for item in plan.batches
                    ],
                    width="stretch",
                    hide_index=True,
                )

    keywords_text = st.text_input(
        "关键词",
        value=default_keywords,
        help="逗号分隔，最多 10 个。",
        key=f"trend_keywords_{account_profile.account_key if account_profile else 'unset'}",
    )
    selected_labels = st.multiselect(
        "排序",
        [sort.label for sort in DOUYIN_SORTS],
        default=[sort.label for sort in DOUYIN_SORTS],
    )
    label_to_key = {sort.label: sort.key for sort in DOUYIN_SORTS}
    col_limit, col_mode = st.columns(2)
    with col_limit:
        limit_per_sort = st.slider("每种排序样本数", 1, 20, 20)
    with col_mode:
        headless = st.checkbox(
            "后台运行浏览器",
            value=False,
            help="首次登录或页面变化时不要开启。",
        )
    tag_col, tag_limit_col = st.columns(2)
    with tag_col:
        expand_related_tags = st.checkbox(
            "扩展一层相关标签族",
            value=True,
            help="从关键词结果提取标签，再搜索这些标签；只扩展一层，不递归。",
        )
    with tag_limit_col:
        max_related_tags = st.slider(
            "每个关键词最多扩展标签",
            1,
            3,
            2,
            disabled=not expand_related_tags,
        )
    preview_request = TrendCollectionRequest(
        keywords=_split_keywords(keywords_text),
        limit_per_sort=limit_per_sort,
        sorts=tuple(label_to_key[label] for label in selected_labels),
        headless=headless,
        web_crawler_enabled=True,
        expand_related_tags=expand_related_tags,
        max_related_tags_per_keyword=max_related_tags,
    )
    planned_pages = estimate_douyin_planned_pages(preview_request)
    st.caption(
        f"本次预计最多访问 {planned_pages} 个搜索结果页；"
        "关键词和标签族都会应用所选排序，标签族最多全局 6 个。"
    )
    over_page_budget = planned_pages > MAX_PAGES_PER_RUN
    if over_page_budget:
        st.warning(
            f"预计页数超过单批 {MAX_PAGES_PER_RUN} 页上限，请减少关键词、"
            "排序或每个关键词的标签数后再采集。"
        )
    authorization_reference = st.text_input(
        "授权说明/工单编号",
        placeholder="例如：账号持有人确认，仅采集当前账号可见公开样本",
    )
    confirmed = st.checkbox(
        "我确认有权访问这些页面，并仅将页面可见样本用于内部趋势分析",
        value=False,
    )

    login_col, collect_col = st.columns(2)
    with login_col:
        if st.button("打开独立趋势浏览器登录", width="stretch"):
            session = build_douyin_trend_session(headless=False)
            with st.spinner("请在浏览器中完成登录，完成后关闭浏览器窗口..."):
                session.open_for_manual_login_until_closed(
                    url="https://www.douyin.com/",
                    timeout_seconds=1800,
                )
            st.success("趋势采集登录窗口已关闭，登录态已保存在独立目录。")
    with collect_col:
        collect_clicked = st.button(
            "开始采集并分析",
            type="primary",
            width="stretch",
            disabled=(
                not confirmed
                or not authorization_reference.strip()
                or over_page_budget
                or account_profile is None
            ),
        )

    if collect_clicked:
        if account_profile is None:
            st.error("请先选择一个有效运营账号。")
            return
        keywords = _split_keywords(keywords_text)
        if not keywords:
            st.error("请至少填写一个关键词。")
            return
        if not selected_labels:
            st.error("请至少选择一种排序。")
            return
        request = TrendCollectionRequest(
            keywords=keywords,
            limit_per_sort=limit_per_sort,
            sorts=tuple(label_to_key[label] for label in selected_labels),
            headless=headless,
            web_crawler_enabled=True,
            expand_related_tags=expand_related_tags,
            max_related_tags_per_keyword=max_related_tags,
        )
        policy = _build_run_policy(
            authorization_reference,
            planned_pages=estimate_douyin_planned_pages(request),
        )
        with st.spinner("正在采集页面可见样本并生成选题卡..."):
            run_id, result = service.collect(
                DouyinWebTrendProvider(),
                request,
                policy=policy,
                account_profile=account_profile,
            )
            if run_id:
                clusters, briefs = service.analyze(
                    preferred_topics=keywords,
                    account_profile=account_profile,
                )
            else:
                clusters, briefs = [], []
        if result.policy_code != "allowed":
            st.error(f"采集被策略阻断：{result.policy_code}")
        elif run_id:
            st.session_state["trend_last_run_id"] = run_id
            st.success(
                f"采集完成：{len(result.observations)} 条观察，"
                f"保留 {len(result.tag_relations)} 条标签关系和 "
                f"{len(result.tag_traffic_snapshots)} 条排序流量快照；"
                f"生成 {len(clusters)} 个话题簇和 {len(briefs)} 张选题卡。"
            )
        else:
            st.warning("没有采集到可分析样本。")
        for warning in result.warnings:
            st.warning(warning)

    st.markdown("---")
    section_header("离线重新分析", "调整账号定位，不需要重新访问抖音页面。")
    preferred_text = st.text_input(
        "账号定位关键词",
        value="法律,普法,小说",
        key="trend_preferred_topics",
    )
    if st.button("重新聚类并生成选题卡"):
        if account_profile is None:
            st.error("请先在账号策略页创建并选择一个运营账号。")
            return
        clusters, briefs = service.analyze(
            preferred_topics=_split_keywords(preferred_text),
            account_profile=account_profile,
        )
        if briefs:
            st.success(f"分析完成：{len(clusters)} 个话题簇，{len(briefs)} 张选题卡。")
        else:
            st.info("当前没有可分析样本，请先完成采集。")

    _render_tag_relationships(repository)
    _render_temporal_signals(repository)
    _render_content_analysis(repository, account_profile)


def _render_account_profiles(repository: AccountProfileRepository) -> None:
    section_header(
        "运营账号与领域策略",
        "法律和小说是首批领域插件；每次修改都会创建不可变账号策略版本。",
    )
    registry = get_default_domain_registry()
    profiles = repository.list_active(status=None)
    if profiles:
        st.dataframe(
            [
                {
                    "账号": item.account_key,
                    "名称": item.display_name,
                    "状态": item.status,
                    "领域策略": f"{item.domain_strategy_id}/{item.strategy_version}",
                    "账号策略版本": item.profile_version,
                    "关键词": "、".join(item.seed_keywords),
                    "工作流": item.workflow_profile,
                }
                for item in profiles
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("暂无账号策略。可以先创建法律律所号或小说推广号。")

    existing_options = ["新建账号", *[item.account_key for item in profiles]]
    selected_existing = st.selectbox(
        "编辑对象",
        existing_options,
        key="trend_profile_edit_target",
    )
    current = next(
        (item for item in profiles if item.account_key == selected_existing),
        None,
    )
    specs = registry.list_available()
    strategy_keys = [f"{item.strategy_id}/{item.version}" for item in specs]
    current_strategy_key = (
        f"{current.domain_strategy_id}/{current.strategy_version}"
        if current
        else strategy_keys[0]
    )

    with st.form("trend_account_profile_form"):
        account_key = st.text_input(
            "账号标识",
            value=current.account_key if current else "",
            placeholder="例如 douyin_legal_01",
            disabled=current is not None,
        )
        display_name = st.text_input(
            "账号名称",
            value=current.display_name if current else "",
            placeholder="例如 XX 律师事务所普法号",
        )
        strategy_key = st.selectbox(
            "领域策略",
            strategy_keys,
            index=strategy_keys.index(current_strategy_key),
            format_func=lambda value: _strategy_label(specs, value),
        )
        seed_keywords = st.text_input(
            "种子关键词",
            value=",".join(current.seed_keywords) if current else "",
        )
        negative_keywords = st.text_input(
            "排除关键词",
            value=",".join(current.negative_keywords) if current else "",
        )
        target_audiences = st.text_input(
            "目标人群",
            value=",".join(current.target_audiences) if current else "",
        )
        service_scope = st.text_input(
            "业务/推广范围",
            value=",".join(current.service_scope) if current else "",
        )
        allowed_formats = st.text_input(
            "允许的视频形式",
            value=",".join(current.allowed_formats) if current else "",
        )
        cta_policy = st.text_input(
            "行动引导规则",
            value=",".join(current.cta_policy) if current else "",
        )
        workflow_profile = st.text_input(
            "默认工作流方案",
            value=current.workflow_profile if current else "",
        )
        domain_config_text = st.text_area(
            "领域扩展配置 JSON",
            value=json.dumps(
                current.domain_config if current else {},
                ensure_ascii=False,
                indent=2,
            ),
            help="字段由所选领域策略的配置 Schema 校验。",
        )
        submitted = st.form_submit_button(
            "保存为新策略版本",
            type="primary",
            width="stretch",
        )

    selected_spec = next(
        item
        for item in specs
        if f"{item.strategy_id}/{item.version}" == strategy_key
    )
    with st.expander("查看当前领域配置 Schema"):
        st.json(selected_spec.config_schema)

    if submitted:
        normalized_account_key = account_key.strip()
        if not normalized_account_key:
            st.error("账号标识不能为空。")
            return
        try:
            domain_config = json.loads(domain_config_text or "{}")
            if not isinstance(domain_config, dict):
                raise ValueError("领域扩展配置必须是 JSON 对象")
            strategy_id, strategy_version = strategy_key.split("/", 1)
            profile = AccountProfile(
                account_uuid=(
                    current.account_uuid
                    if current
                    else stable_account_uuid(normalized_account_key)
                ),
                account_key=normalized_account_key,
                display_name=display_name.strip(),
                business_mode=strategy_id,
                domain_strategy_id=strategy_id,
                strategy_version=strategy_version,
                profile_version=(
                    repository.next_profile_version(normalized_account_key)
                    if current
                    else 1
                ),
                seed_keywords=_split_keywords(seed_keywords),
                negative_keywords=_split_keywords(negative_keywords),
                target_audiences=_split_keywords(target_audiences),
                service_scope=_split_keywords(service_scope),
                allowed_formats=_split_keywords(allowed_formats),
                cta_policy=_split_keywords(cta_policy),
                workflow_profile=workflow_profile.strip(),
                domain_config=domain_config,
            )
            registry.resolve(profile)
            repository.save(profile)
        except (ValueError, KeyError) as exc:
            st.error(f"账号策略保存失败：{exc}")
        else:
            st.success(
                f"已保存 {profile.account_key} 的账号策略版本 v{profile.profile_version}。"
            )
            st.rerun()


def _strategy_label(specs, value: str) -> str:
    item = next(
        spec for spec in specs if f"{spec.strategy_id}/{spec.version}" == value
    )
    return f"{item.label} · {value}"


def _account_profile_label(profiles: list[AccountProfile], account_key: str) -> str:
    profile = next(item for item in profiles if item.account_key == account_key)
    return (
        f"{profile.display_name or profile.account_key} · "
        f"{profile.domain_strategy_id}/{profile.strategy_version}"
    )


def _render_tag_relationships(repository: TrendRepository) -> None:
    st.markdown("---")
    section_header(
        "标签族与页面样本流量",
        "按采集批次追加保存；样本指数不是抖音官方总流量。",
    )
    run_id = st.session_state.get("trend_last_run_id") or (
        repository.latest_collection_run_id()
    )
    if not run_id:
        st.info("暂无标签关系。完成一次采集后会显示关键词、标签和视频的关系。")
        return
    traffic = repository.list_tag_traffic_snapshots(run_id=run_id)
    relations = repository.list_tag_relations(run_id=run_id)
    if traffic:
        st.caption(f"批次：{run_id}")
        st.dataframe(
            [
                {
                    "根关键词": item.root_keyword,
                    "标签": f"#{item.tag}",
                    "排序": item.sort_label,
                    "唯一视频数": item.unique_video_count,
                    "最佳名次": item.best_rank,
                    "倒数排名和": item.reciprocal_rank_score,
                    "页面展示指标峰值": item.visible_metric_max,
                    "页面展示指标中位数": item.visible_metric_median,
                    "页面样本流量分": item.sample_score,
                }
                for item in traffic
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("本批次保留了关键词标签关系，但没有执行相关标签的排行采集。")
    if relations:
        with st.expander("查看标签关系证据", expanded=not traffic):
            st.dataframe(
                [
                    {
                        "根关键词": item.root_keyword,
                        "来源": (
                            item.source_value
                            if item.source_kind == "keyword"
                            else f"#{item.source_value}"
                        ),
                        "目标标签": f"#{item.target_tag}",
                        "关系": item.relation_kind,
                        "支持视频数": item.support_video_count,
                        "来源视频数": item.source_video_count,
                        "排序覆盖": item.sort_coverage,
                        "关系权重": item.weight,
                        "关系分": item.relationship_score,
                        "已扩展采集": "是" if item.expanded else "否",
                    }
                    for item in relations
                ],
                width="stretch",
                hide_index=True,
            )


def _render_temporal_signals(repository: TrendRepository) -> None:
    st.markdown("---")
    section_header(
        "多时间点趋势",
        "默认观察最近 14 天；至少两个批次才判断上涨或回落。",
    )
    temporal = TemporalTrendService(repository)
    videos = temporal.video_signals(window_days=14)[:50]
    tags = temporal.tag_family_signals(window_days=14)[:50]
    if videos:
        st.write("视频动量")
        st.dataframe(
            [
                {
                    "视频": item.title,
                    "方向": item.direction,
                    "动量分": item.momentum_score,
                    "置信度": item.confidence,
                    "时间点": item.point_count,
                    "观察小时": item.observation_hours,
                    "展示指标/小时": item.metric_velocity_per_hour,
                    "排名改善/小时": item.rank_improvement_per_hour,
                    "发布距今小时": item.age_hours,
                }
                for item in videos
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("暂无视频时间趋势；重复执行同一批关键词后会形成动量信号。")
    if tags:
        st.write("标签族动量")
        st.dataframe(
            [
                {
                    "根关键词": item.root_keyword,
                    "标签": f"#{item.tag}",
                    "排序": item.sort_key,
                    "方向": item.direction,
                    "动量分": item.momentum_score,
                    "置信度": item.confidence,
                    "时间点": item.point_count,
                    "样本分变化/小时": item.sample_score_velocity_per_hour,
                    "排名": f"{item.best_rank_start} → {item.best_rank_end}",
                }
                for item in tags
            ],
            width="stretch",
            hide_index=True,
        )


def _render_content_analysis(
    repository: TrendRepository,
    account_profile: AccountProfile | None,
) -> None:
    st.markdown("---")
    section_header(
        "候选视频内容分析",
        "可人工切换元数据降级分析或本地 Qwen + Paraformer；结果按账号策略版本缓存。",
    )
    if account_profile is None:
        st.info("选择账号后才能计算候选内容与账号定位的相关度。")
        return
    observations = repository.list_observations(limit=5000)
    latest_by_item = {}
    for item in observations:
        latest_by_item.setdefault(item.item_id, item)
    candidates = list(latest_by_item.values())
    if not candidates:
        st.info("暂无候选视频。完成采集后可批量分析。")
        return
    col_impl, col_count = st.columns(2)
    with col_impl:
        implementation_id = st.selectbox(
            "内容分析实现",
            ["metadata_heuristic", "local_qwen_paraformer"],
            format_func=lambda value: {
                "metadata_heuristic": "元数据分析（无需视频文件）",
                "local_qwen_paraformer": "本地 Qwen + Paraformer（需授权媒体）",
            }[value],
            key="trend_content_analysis_impl",
        )
    with col_count:
        candidate_count = st.slider(
            "本批候选数",
            1,
            min(100, len(candidates)),
            min(20, len(candidates)),
            key="trend_content_analysis_count",
        )
    artifact_mapping: dict[str, object] = {}
    run_toolchain = False
    media_confirmed = False
    if implementation_id == "local_qwen_paraformer":
        mapping_text = st.text_area(
            "本地媒体/分析产物映射 JSON",
            value="{}",
            help=(
                '键为 item_id；值可以是视频路径，或 {"video": "...", '
                '"qwen": "...", "transcript": "...", "scenes": "..."}。'
            ),
            key="trend_content_artifact_mapping",
        )
        try:
            parsed_mapping = json.loads(mapping_text or "{}")
            if isinstance(parsed_mapping, dict):
                artifact_mapping = parsed_mapping
            else:
                st.error("产物映射必须是 JSON 对象。")
        except json.JSONDecodeError as exc:
            st.error(f"产物映射 JSON 无效：{exc}")
        run_toolchain = st.checkbox(
            "缺少产物时自动执行本地抽帧、Qwen 和 Paraformer 脚本",
            value=False,
            key="trend_run_local_content_toolchain",
        )
        media_confirmed = st.checkbox(
            "我确认这些本地媒体有分析权限，仅用于内部选题研究",
            value=False,
            key="trend_local_media_authorized",
        )
    analyze_clicked = st.button(
        "批量分析候选内容",
        type="primary",
        disabled=(implementation_id == "local_qwen_paraformer" and not media_confirmed),
        key="trend_run_content_analysis",
    )
    if analyze_clicked:
        requests = []
        for item in candidates[:candidate_count]:
            artifacts = artifact_mapping.get(item.item_id, {})
            if isinstance(artifacts, str):
                artifacts = {"video": artifacts}
            if not isinstance(artifacts, dict):
                artifacts = {}
            requests.append(
                ContentAnalysisRequest(
                    item_id=item.item_id,
                    video_id=item.video_id,
                    title=item.title,
                    author=item.author,
                    hashtags=item.hashtags,
                    raw_text=item.raw_text,
                    account_profile=account_profile,
                    media_access_mode=(
                        "local_media_authorized"
                        if implementation_id == "local_qwen_paraformer"
                        else "metadata_only"
                    ),
                    local_video_path=str(artifacts.get("video") or ""),
                    qwen_analysis_path=str(artifacts.get("qwen") or ""),
                    transcript_path=str(artifacts.get("transcript") or ""),
                    scene_alignment_path=str(artifacts.get("scenes") or ""),
                )
            )
        with st.spinner("正在分析内容结构、展示方式与账号相关度..."):
            result = ContentAnalysisBatchService(repository).analyze(
                requests,
                implementation_id=implementation_id,
                allow_metadata_fallback=True,
                run_local_toolchain=run_toolchain,
            )
        st.success(
            f"分析完成：完整 {result.completed_count}，降级 {result.degraded_count}，"
            f"失败 {result.failed_count}，缓存命中 {result.cached_count}。"
        )
        for error in result.errors:
            st.warning(error)
    analyses = repository.list_content_analyses(
        account_uuid=account_profile.account_uuid,
        limit=200,
    )
    if analyses:
        st.dataframe(
            [
                {
                    "视频": item.title,
                    "状态": item.status,
                    "实现": item.provider_id,
                    "展示方式": item.presentation_type,
                    "钩子": item.hook_type,
                    "节奏": item.pacing,
                    "账号相关度": item.relevance.score if item.relevance else None,
                    "相关度置信度": (
                        item.relevance.confidence if item.relevance else None
                    ),
                    "主题": "、".join(item.topic_labels),
                }
                for item in analyses
            ],
            width="stretch",
            hide_index=True,
        )


def _render_briefs(
    repository: TrendRepository,
    service: TrendOperationsService,
    account_repository: AccountProfileRepository,
) -> None:
    section_header(
        "账号机会排行",
        "综合流量、时间动量、内容证据、账号相关度、饱和度和制作可行性。",
    )
    profiles = account_repository.list_active()
    if profiles:
        opportunity_account_key = st.selectbox(
            "机会账号",
            [item.account_key for item in profiles],
            format_func=lambda value: _account_profile_label(profiles, value),
            key="trend_opportunity_account",
        )
        opportunity_profile = next(
            item for item in profiles if item.account_key == opportunity_account_key
        )
        opportunity_service = ContentOpportunityService(repository)
        if st.button(
            "刷新账号机会排行",
            type="primary",
            key="trend_build_opportunities",
        ):
            service.analyze(account_profile=opportunity_profile, limit=100_000)
            opportunities = opportunity_service.build_opportunities(
                opportunity_profile
            )
            st.success(f"已生成 {len(opportunities)} 个账号机会。")
        opportunities = repository.list_opportunities(
            account_uuid=opportunity_profile.account_uuid,
            limit=200,
        )
        if opportunities:
            st.dataframe(
                [
                    {
                        "机会": item.title,
                        "状态": item.status,
                        "机会分": item.opportunity_score,
                        "时间动量": item.score_breakdown.get("temporal_momentum"),
                        "账号相关度": item.score_breakdown.get("account_relevance"),
                        "内容证据": item.score_breakdown.get("content_confidence"),
                        "展示方式": item.recommended_presentation,
                        "钩子": item.recommended_hook_type,
                        "有效至": item.valid_until,
                    }
                    for item in opportunities
                ],
                width="stretch",
                hide_index=True,
            )
            opportunity_id = st.selectbox(
                "选择机会",
                [item.opportunity_id for item in opportunities],
                format_func=lambda value: next(
                    f"{item.title} · {item.opportunity_score:.1f}"
                    for item in opportunities
                    if item.opportunity_id == value
                ),
                key="trend_selected_opportunity",
            )
            opportunity = next(
                item for item in opportunities if item.opportunity_id == opportunity_id
            )
            st.info("｜".join(opportunity.evidence[:3]))
            approve_col, reject_col, script_col = st.columns(3)
            with approve_col:
                if st.button("批准机会", key="trend_approve_opportunity"):
                    opportunity_service.approve_opportunity(opportunity_id)
                    st.rerun()
            with reject_col:
                if st.button("拒绝机会", key="trend_reject_opportunity"):
                    opportunity_service.reject_opportunity(opportunity_id)
                    st.rerun()
            with script_col:
                if st.button("生成 A/B 15秒脚本", key="trend_generate_ab_scripts"):
                    scripts = opportunity_service.generate_scripts(
                        opportunity_profile,
                        opportunity_id,
                    )
                    st.success(f"已生成 {len(scripts)} 个脚本版本。")
            scripts = repository.list_opportunity_scripts(
                opportunity_id=opportunity_id
            )
            for script in scripts:
                with st.expander(
                    f"脚本 {script.variant_id} · {script.title} · {script.status}",
                    expanded=script.status == "draft",
                ):
                    st.dataframe(
                        [
                            {
                                "时间": f"{beat.start_seconds:g}—{beat.end_seconds:g}秒",
                                "段落作用": beat.role,
                                "画面": beat.visual,
                                "口播/对白": beat.voiceover,
                                "字幕": beat.on_screen_text,
                            }
                            for beat in script.beats
                        ],
                        width="stretch",
                        hide_index=True,
                    )
                    st.caption(f"CTA：{script.cta}")
                    if st.button(
                        f"批准脚本 {script.variant_id}",
                        key=f"trend_approve_script_{script.script_id}",
                    ):
                        opportunity_service.approve_script(script.script_id)
                        st.rerun()
        else:
            st.info("暂无机会卡。先完成采集和内容分析，再刷新账号机会排行。")
    else:
        st.warning("请先配置运营账号。")

    st.markdown("---")
    section_header("选题审批", "只有批准后的选题卡可以带入视频制作。")
    status_filter = st.selectbox(
        "状态",
        ["全部", "draft", "approved", "rejected", "used"],
        format_func=lambda value: {
            "全部": "全部",
            "draft": "待审批",
            "approved": "已批准",
            "rejected": "已拒绝",
            "used": "已使用",
        }[value],
    )
    briefs = repository.list_briefs(
        status=None if status_filter == "全部" else status_filter
    )
    if not briefs:
        st.info("暂无选题卡。")
        return

    labels = {
        brief.brief_id: f"{brief.title} · {brief.score:.1f} · {brief.status}"
        for brief in briefs
    }
    selected_id = st.selectbox(
        "选择选题",
        [brief.brief_id for brief in briefs],
        format_func=lambda value: labels[value],
    )
    brief = next(item for item in briefs if item.brief_id == selected_id)
    col_score, col_kind, col_samples = st.columns(3)
    col_score.metric("选题分", f"{brief.score:.1f}")
    col_kind.metric("依据", "增长趋势" if brief.score_kind == "trend" else "单次样本")
    col_samples.metric("样本量", brief.source_scope.get("sample_count", 0))
    st.subheader(brief.title)
    st.write(brief.recommended_hook)
    with st.expander("证据和代表样本", expanded=True):
        for item in brief.evidence:
            st.write(f"- {item}")
    with st.expander("原创角度与脚本结构"):
        st.write("原创角度")
        for item in brief.angles:
            st.write(f"- {item}")
        st.write("脚本结构")
        for item in brief.script_structure:
            st.write(f"- {item}")
    with st.expander("风险与核验要求"):
        for item in brief.risks:
            st.write(f"- {item}")

    approve_col, reject_col, production_col = st.columns(3)
    with approve_col:
        if st.button("批准选题", type="primary", width="stretch"):
            service.approve_brief(brief.brief_id)
            st.success("选题已批准。")
            st.rerun()
    with reject_col:
        if st.button("拒绝选题", width="stretch"):
            service.reject_brief(brief.brief_id)
            st.warning("选题已拒绝。")
            st.rerun()
    with production_col:
        if st.button(
            "带入视频制作",
            width="stretch",
            disabled=brief.status != "approved",
        ):
            st.session_state["trend_publish_prefill"] = {
                "keywords": ",".join(brief.keywords) or brief.title,
                "title": brief.title,
                "description": brief.recommended_hook,
                "tags": ",".join(brief.keywords),
                "brief_id": brief.brief_id,
                "cluster_id": brief.cluster_id,
                "hook_type": "question_contrast",
            }
            st.success("已带入制作参数，请打开左侧“视频”页面继续。")


def _render_feedback(repository: TrendRepository) -> None:
    section_header("发布效果复盘", "至少两个指标快照才能计算增长速度。")
    feedback = OperationsFeedbackService(repository)
    results = feedback.performance_results()
    recommendation = feedback.recommend_next_cycle()
    st.info(recommendation.summary)
    metrics = st.columns(4)
    metrics[0].metric("有效样本", recommendation.sample_size)
    metrics[1].metric("策略状态", recommendation.status)
    metrics[2].metric("验证题材", len(recommendation.proven_topics))
    metrics[3].metric("实验比例", f"{recommendation.experiment_share:.0%}")
    if results:
        st.dataframe(
            [
                {
                    "视频": result.video_id or result.identity,
                    "话题簇": result.cluster_id,
                    "观察小时": result.observation_hours,
                    "播放增量": result.views_gained,
                    "每小时播放增长": result.view_velocity,
                    "每千播放互动": result.engagement_per_1k,
                    "相对表现": result.relative_performance,
                }
                for result in results
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("尚无包含两个快照的已关联视频。每次同步创作者作品都会自动保存快照。")


def _build_run_policy(reference: str, *, planned_pages: int) -> SourcePolicy:
    reference_hash = "sha256:" + hashlib.sha256(
        reference.strip().encode("utf-8")
    ).hexdigest()
    safe_cap = max(1, min(MAX_PAGES_PER_RUN, planned_pages))
    return SourcePolicy(
        policy_id=f"douyin-visible-samples-{datetime.now(timezone.utc).date().isoformat()}",
        provider=SourceProvider.AUTHORIZED_WEB,
        status=PolicyStatus.APPROVED,
        allowed_hosts=("www.douyin.com",),
        allowed_path_prefixes=("/search",),
        allowed_fields=COLLECTED_FIELDS,
        allowed_purposes=frozenset({"trend_analysis"}),
        min_interval_seconds=1,
        max_pages_per_run=safe_cap,
        daily_page_cap=90,
        raw_retention_days=0,
        authorization_reference_hash=reference_hash,
    )


def _split_keywords(value: str) -> list[str]:
    normalized = value.replace("，", ",")
    output: list[str] = []
    for item in normalized.split(","):
        item = item.strip()
        if item and item not in output:
            output.append(item)
    return output[:10]


if __name__ == "__main__":
    from src.web.components.ui import inject_app_theme

    st.set_page_config(page_title="热门选题", page_icon="⌁", layout="wide")
    inject_app_theme()
    st.navigation(
        [st.Page(page_trend_operations, title="热门选题", icon="📈")],
        position="sidebar",
    ).run()
