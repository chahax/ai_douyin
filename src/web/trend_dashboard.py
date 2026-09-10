"""Streamlit page for native trend discovery and operation feedback."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import streamlit as st

from src.operations_accounts import (
    AccountBindingConflict,
    AccountBindingRepository,
    AccountOAuthStateError,
    AccountProfile,
    AccountProfileRepository,
    AccountRuntimeError,
    AccountRuntimeService,
    DouyinIdentity,
    stable_account_uuid,
)
from src.operations_accounts.maintenance import AccountMaintenanceService
from src.platform_adapter.douyin_identity import (
    DOUYIN_SELF_URL,
    DouyinIdentityVerificationError,
    DouyinOAuthClient,
)
from src.platform_adapter.douyin_playback import PlaybackOptions
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
    build_account_douyin_trend_session,
    estimate_douyin_planned_pages,
)
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.opportunity import ContentOpportunityService
from src.trend_intelligence.research_workflow import (
    AccountVideoResearchWorkflow, cohort_media_readiness, load_local_media_manifest,
)
from src.trend_intelligence.media_evidence import media_readiness
from src.trend_intelligence.saved_script_review import current_saved_script_review
from src.trend_intelligence.service import TrendOperationsService
from src.trend_intelligence.sample_gate import (
    POLICY_TEXT, SampleGateError, batch_observations, evaluate_sample,
)
from src.trend_intelligence.temporal import TemporalTrendService
from src.trend_intelligence.source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourceProvider,
)
from src.web.components.ui import page_header, section_header
from src.web.components.auth import get_current_role, get_current_user, has_permission


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
        "duration_seconds",
        "tag_relationships",
        "tag_traffic_snapshots",
    }
)
MAX_PAGES_PER_RUN = 30


def _process_douyin_oauth_callback(
    account_repository: AccountProfileRepository,
) -> None:
    """Consume a durable one-time OAuth state before account widgets render."""
    code = str(st.query_params.get("code") or "").strip()
    returned_state = str(st.query_params.get("state") or "").strip()
    if not code and not returned_state:
        return
    try:
        if not has_permission(get_current_role(), "admin"):
            raise AccountOAuthStateError("只有管理员可以完成抖音账号授权绑定。")
        if not code or not returned_state:
            raise AccountOAuthStateError("OAuth 回调缺少 code 或 state。")
        binding_repository = AccountBindingRepository(account_repository.db_path)
        attempt = binding_repository.consume_oauth_attempt(returned_state)
        current_user = get_current_user() or ""
        if attempt["requested_by"] and attempt["requested_by"] != current_user:
            raise AccountOAuthStateError("当前管理员与发起授权的管理员不一致。")
        identity = DouyinOAuthClient().exchange_identity(code)
        account_key = attempt["account_key"]
        st.session_state[f"pending_douyin_identity_{account_key}"] = asdict(
            identity
        )
        st.session_state["trend_profile_edit_target"] = account_key
        st.success(
            "已读取官方授权身份；请继续打开扫码登录页，"
            "核对当前浏览器环境后再确认绑定。"
        )
    except (AccountOAuthStateError, DouyinIdentityVerificationError) as exc:
        st.error(f"抖音授权回调处理失败：{exc}")
    finally:
        st.query_params.pop("code", None)
        st.query_params.pop("state", None)


def page_trend_operations() -> None:
    page_header(
        "热门选题",
        "原生采集授权页面可见样本，生成可解释选题卡，并用发布表现调整下一期策略。",
        icon="⌁",
        eyebrow="TREND OPERATIONS",
    )
    repository = TrendRepository()
    account_repository = AccountProfileRepository()
    _process_douyin_oauth_callback(account_repository)
    service = TrendOperationsService(repository=repository)
    summary = repository.summary()

    from src.web.components.flow_graph import sequence_graph
    sequence_graph([
        ('账号方向', '先明确运营账号、内容定位与授权范围，让后续调研围绕正确的对象展开。', '操作指引'),
        ('采集与分析', '采集可访问的热门样本，分析内容结构与相关性。', f"{summary['runs']} 个采集批次"),
        ('选题提案', '将分析形成选题卡，人工审核后再进入内容制作。', f"{summary['briefs']} 张选题卡"),
        ('效果复盘', '结合已发布内容的表现，为下一轮选题补充依据。', f"{summary['snapshots']} 个快照"),
    ], key='research_intro_graph', title='从账号方向到下一次选题',
       description='先理解这四步，再使用下方对应功能。节点数量来自本地统计，连线表示操作顺序。')

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
        _render_feedback(repository, account_repository)


def _render_collection(
    repository: TrendRepository,
    service: TrendOperationsService,
    account_repository: AccountProfileRepository,
) -> None:
    section_header(
        "原生热门样本采集",
        "采集、分析、账号维护和发布统一使用当前账号的 AccountRuntimeContext。",
    )
    st.info(
        "一次采集只计算热门样本分；同一视频至少跨两个采集批次后，才计算增长趋势。"
    )
    account_profiles = account_repository.list_active()
    account_profile: AccountProfile | None = None
    account_binding_ready = False
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
        selected_binding = AccountBindingRepository(
            account_repository.db_path
        ).get_optional(selected_account_key)
        account_binding_ready = bool(
            selected_binding and selected_binding.status == "active"
        )
        st.caption(
            f"领域策略：{account_profile.domain_strategy_id}/{account_profile.strategy_version} · "
            f"账号策略版本：v{account_profile.profile_version}"
        )
        if not account_binding_ready:
            st.error("该运营账号尚未完成真实抖音身份绑定或登录不健康，请先到“账号策略”处理。")
        # 单批只预填两个根词，保证三种排序和一层标签扩展仍在 30 页预算内。
        # 全部账号关键词由上方分批计划分多轮执行。
        default_keywords = ",".join(account_profile.seed_keywords[:2])
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

    try:
        from src.workflow.runtime import active_selections

        active_nodes = active_selections()
    except Exception:
        active_nodes = {
            "trend_collection": "douyin_authorized_web",
            "media_acquisition": "metadata_only",
            "content_analysis": "metadata_heuristic",
            "opportunity_ranking": "explainable_rules",
        }
    research_nodes = {
        stage: active_nodes.get(stage, implementation)
        for stage, implementation in {
            "trend_collection": "douyin_authorized_web",
            "media_acquisition": "metadata_only",
            "content_analysis": "metadata_heuristic",
            "opportunity_ranking": "explainable_rules",
        }.items()
    }
    supported_research = (
        research_nodes["trend_collection"] == "douyin_authorized_web"
        and (research_nodes["media_acquisition"], research_nodes["content_analysis"])
        in {("metadata_only", "metadata_heuristic"), ("authorized_local_media", "local_qwen_paraformer")}
        and research_nodes["opportunity_ranking"] == "explainable_rules"
    )
    st.caption(
        "当前研究流程："
        f"{research_nodes['trend_collection']} → "
        f"{research_nodes['media_acquisition']} → "
        f"{research_nodes['content_analysis']} → "
        f"{research_nodes['opportunity_ranking']}"
    )
    if not supported_research:
        st.info(
            "当前研究入口支持页面元数据筛选，或授权本地视频 + Qwen/Paraformer 音画分析。"
        )
    research_media_manifest = ""
    if research_nodes["content_analysis"] == "local_qwen_paraformer":
        research_media_manifest = st.text_input(
            "继续已采集批次的本地媒体清单路径",
            help="research_local_media/v1 清单须绑定 collection_run_id、account_uuid 和每条 item_id/video_id。会复用指定批次，运行本地音画分析。",
            key="research_workflow_media_manifest",
        ).strip()
    else:
        st.caption("页面元数据仅用于采集筛选。原视频音画分析未齐全时，流程停在等待媒体阶段，不能生成剧本。")

    login_col, collect_col, workflow_col = st.columns(3)
    with login_col:
        login_label = (
            f"打开 {account_profile.display_name or account_profile.account_key} 登录/验证"
            if account_profile
            else "打开账号登录/验证"
        )
        if st.button(
            login_label,
            width="stretch",
            disabled=account_profile is None or not account_binding_ready,
        ):
            keywords_for_login = _split_keywords(keywords_text)
            login_url = (
                f"https://www.douyin.com/search/{quote(keywords_for_login[0])}?type=video"
                if keywords_for_login
                else "https://www.douyin.com/"
            )
            try:
                session = build_account_douyin_trend_session(
                    account_profile.account_key,
                    headless=False,
                )
                with st.spinner("请在浏览器中完成人工验证，完成后关闭浏览器窗口..."):
                    session.open_for_manual_login_until_closed(
                        url=login_url,
                        timeout_seconds=1800,
                    )
            except (AccountRuntimeError, RuntimeError) as exc:
                st.error(str(exc))
            else:
                st.success("账号浏览器已关闭，登录/验证状态已保存，可重新运行流程。")
    with collect_col:
        collect_clicked = st.button(
            "只采集并聚类",
            width="stretch",
            disabled=(
                not confirmed
                or not authorization_reference.strip()
                or over_page_budget
                or account_profile is None
                or not account_binding_ready
            ),
        )
    with workflow_col:
        local_research_mode = research_nodes["content_analysis"] == "local_qwen_paraformer"
        workflow_clicked = st.button(
            "运行完整研究流程",
            type="primary",
            width="stretch",
            disabled=(
                account_profile is None
                or not supported_research
                or (local_research_mode and not research_media_manifest)
                or (not local_research_mode and (not confirmed or not authorization_reference.strip()
                    or over_page_budget or not account_binding_ready))
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
                DouyinWebTrendProvider.for_account(account_profile.account_key),
                request,
                policy=policy,
                account_profile=account_profile,
            )
            if run_id:
                clusters, briefs = _analyze_with_sample_gate(service,
                    preferred_topics=keywords,
                    account_profile=account_profile,
                    collection_run_id=run_id,
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

    if workflow_clicked:
        if account_profile is None:
            st.error("请先选择一个有效运营账号。")
            return
        keywords = _split_keywords(keywords_text)
        if not local_research_mode and (not keywords or not selected_labels):
            st.error("请至少填写一个关键词并选择一种排序。")
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
        resume_collection_run_id = ""
        if research_media_manifest:
            try:
                manifest_header = json.loads(Path(research_media_manifest).read_text(encoding="utf-8-sig"))
                resume_collection_run_id = str(manifest_header.get("collection_run_id") or "")
                if not resume_collection_run_id:
                    raise ValueError("媒体清单缺少 collection_run_id")
            except (OSError, ValueError, TypeError) as exc:
                st.error(f"本地媒体清单无效：{exc}")
                return
        with st.spinner(
            "正在执行：采集 → 去重校验 → 话题聚类 → 内容分析 → 机会排行..."
        ):
            workflow_result = AccountVideoResearchWorkflow(repository).run(
                account_profile,
                DouyinWebTrendProvider.for_account(account_profile.account_key),
                request,
                policy=policy,
                content_analysis_implementation=research_nodes["content_analysis"],
                max_content_candidates=50,
                resume_collection_run_id=resume_collection_run_id,
                local_media_manifest=research_media_manifest or None,
                run_local_toolchain=bool(research_media_manifest),
            )
        if workflow_result.collection_run_id:
            st.session_state["trend_last_run_id"] = (
                workflow_result.collection_run_id
            )
        if workflow_result.status == "completed":
            st.success(
                f"完整流程完成：{workflow_result.unique_videos} 个不同视频，"
                f"{workflow_result.content_analyses} 条内容分析，"
                f"{workflow_result.opportunities} 个账号机会。"
            )
        elif workflow_result.status == "partial":
            st.warning("流程部分完成，请根据阶段日志处理降级项。")
        elif workflow_result.status == "awaiting_media_analysis":
            st.warning(
                f"采集筛选已保存；音画表达证据齐全 {workflow_result.media_readiness.get('ready_count', 0)}"
                f"/{workflow_result.media_readiness.get('required_count', workflow_result.unique_videos)} 条。"
                "请在下方绑定原视频并完成音画分析，再生成剧本。"
            )
        else:
            st.error(
                "流程已停止："
                f"{workflow_result.stopped_reason or workflow_result.status}"
            )
            if workflow_result.stopped_reason == "human_required":
                st.info(
                    "抖音要求人工安全验证。请点击左侧“打开账号登录/验证”，"
                    "完成验证并关闭浏览器后，再运行完整研究流程。"
                )
        st.dataframe(
            [
                {
                    "阶段": item.stage,
                    "实现": item.implementation_id,
                    "状态": item.status,
                    "数量": item.item_count,
                    "说明": item.message,
                }
                for item in workflow_result.stages
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(f"运行日志：{workflow_result.log_path}")
        if workflow_result.local_media_template_path:
            st.download_button("下载本批原视频清单模板",
                Path(workflow_result.local_media_template_path).read_text(encoding="utf-8"),
                file_name="research_local_media.json", mime="application/json")

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
        clusters, briefs = _analyze_with_sample_gate(service,
            preferred_topics=_split_keywords(preferred_text),
            account_profile=account_profile,
        )
        if briefs:
            st.success(f"分析完成：{len(clusters)} 个话题簇，{len(briefs)} 张选题卡。")
        else:
            st.info("当前没有可分析样本，请先完成采集。")

    _render_research_run_logs()
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
    binding_repository = AccountBindingRepository(repository.db_path)
    bindings = {
        item.account_key: item for item in binding_repository.list_all()
    }
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
                    "真实抖音账号": (
                        bindings[item.account_key].display_identity
                        if item.account_key in bindings
                        else "未绑定"
                    ),
                    "登录健康": (
                        bindings[item.account_key].status
                        if item.account_key in bindings
                        else "未检测"
                    ),
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
    if current is not None:
        _render_account_binding(current, repository)
        _render_account_maintenance(current, repository)
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


def _render_account_binding(
    profile: AccountProfile,
    profile_repository: AccountProfileRepository,
) -> None:
    """Render login, identity preview, confirmation and health controls."""
    st.markdown("### 登录并绑定抖音账号")
    st.caption(
        "一个运营账号只绑定一个浏览器环境和一个真实抖音身份。"
        "系统不读取、不保存抖音账号密码。"
    )
    runtime = AccountRuntimeService(profile_repository=profile_repository)
    is_admin = has_permission(get_current_role(), "admin")
    binding = runtime.bindings.get_optional(profile.account_key)
    if binding:
        left, middle, right = st.columns([1, 2, 2])
        with left:
            if binding.avatar_url:
                st.image(binding.avatar_url, width=72)
        with middle:
            st.markdown(f"**{binding.nickname}**")
            st.caption(
                f"公开 UID：{binding.public_uid or '页面未公开'}  · "
                f"来源：{'官方授权' if binding.verification_source == 'official_oauth' else '登录页验真'}"
            )
        with right:
            state_label = {
                "active": "登录健康",
                "expired": "登录已过期，请重新扫码",
                "mismatch": "账号不匹配，已停止任务",
                "blocked": "需要人工安全验证",
            }.get(binding.status, binding.status)
            if binding.status == "active":
                st.success(state_label)
            else:
                st.error(state_label)
            st.caption(f"浏览器环境：{binding.browser_environment_key}")
    else:
        st.warning("尚未绑定真实抖音账号；采集、维护、同步和发布均不会执行。")

    oauth = DouyinOAuthClient()
    if oauth.configured and is_admin:
        oauth_state_key = f"douyin_oauth_state_{profile.account_key}"
        if oauth_state_key not in st.session_state:
            st.session_state[oauth_state_key] = runtime.bindings.create_oauth_attempt(
                profile.account_key,
                requested_by=get_current_user() or "admin",
            )
        st.link_button(
            "使用抖音开放平台授权（优先）",
            oauth.authorization_url(st.session_state[oauth_state_key]),
            width="stretch",
        )
    elif not oauth.configured:
        st.info(
            "未配置开放平台 ClientKey/ClientSecret/回调地址，当前可使用下方扫码登录页验真。"
        )
    if not is_admin:
        st.info("登录、换绑和最终身份确认只允许管理员执行。")

    login_col, health_col = st.columns(2)
    pending_key = f"pending_douyin_identity_{profile.account_key}"
    with login_col:
        if st.button(
            "登录并绑定抖音账号",
            key=f"bind_douyin_{profile.account_key}",
            type="primary",
            width="stretch",
            disabled=not is_admin,
        ):
            try:
                prepared = runtime.prepare_browser_environment(profile.account_key)
                session = prepared.create_browser_session(headless=False)
                with st.spinner("请在弹出的浏览器中扫码登录，完成后关闭该浏览器窗口..."):
                    session.open_for_manual_login_until_closed(
                        DOUYIN_SELF_URL,
                        timeout_seconds=1800,
                    )
                    page_identity = runtime.probe_unbound_identity(
                        profile.account_key,
                        headless=False,
                    )
                existing_pending = st.session_state.get(pending_key) or {}
                if existing_pending.get("verification_source") == "official_oauth":
                    identity = DouyinIdentity(
                        nickname=page_identity.nickname,
                        avatar_url=(existing_pending.get("avatar_url") or page_identity.avatar_url),
                        public_uid=page_identity.public_uid,
                        sec_uid=page_identity.sec_uid,
                        open_id=str(existing_pending.get("open_id") or ""),
                        union_id=str(existing_pending.get("union_id") or ""),
                        verification_source="official_oauth",
                        verified_at=page_identity.verified_at,
                        auth_expires_at=str(existing_pending.get("auth_expires_at") or ""),
                    )
                else:
                    identity = page_identity
                st.session_state[pending_key] = asdict(identity)
            except (DouyinIdentityVerificationError, AccountRuntimeError, RuntimeError) as exc:
                st.error(f"登录身份读取失败：{exc}")
    with health_col:
        if st.button(
            "检测登录健康",
            key=f"verify_douyin_{profile.account_key}",
            width="stretch",
            disabled=binding is None,
        ):
            try:
                context = runtime.resolve(profile.account_key, require_healthy=False)
                with st.spinner("正在从真实抖音页面核验当前登录身份..."):
                    check = runtime.verify_identity(context)
            except (AccountRuntimeError, RuntimeError) as exc:
                st.error(str(exc))
            else:
                (st.success if check.healthy else st.error)(check.message)
                st.rerun()

    pending_payload = st.session_state.get(pending_key)
    if not pending_payload:
        return
    identity = DouyinIdentity(**pending_payload)
    browser_identity_confirmed = bool(identity.public_uid or identity.sec_uid)
    st.markdown("#### 请管理员确认本次读取的身份")
    preview_left, preview_right = st.columns([1, 5])
    with preview_left:
        if identity.avatar_url:
            st.image(identity.avatar_url, width=88)
    with preview_right:
        st.write(f"昵称：{identity.nickname}")
        st.write(f"公开 UID：{identity.public_uid or '页面未展示'}")
        if identity.open_id:
            st.caption(f"开放平台 OpenID：{identity.open_id}")
        if identity.sec_uid:
            st.caption(f"页面身份标识：{identity.sec_uid}")
    allow_rebind = False
    if binding and binding.platform_identity_key != identity.platform_identity_key:
        st.error(
            f"当前绑定为 {binding.display_identity}，本次读取身份不同。"
            "只有管理员明确确认后才允许换绑。"
        )
        allow_rebind = st.checkbox(
            "我确认要将该运营账号换绑到上述真实抖音账号",
            key=f"allow_rebind_{profile.account_key}",
        )
    if st.button(
        "确认身份并保存唯一绑定",
        key=f"confirm_binding_{profile.account_key}",
        disabled=(
            not is_admin
            or not browser_identity_confirmed
            or (
                binding is not None
                and binding.platform_identity_key != identity.platform_identity_key
                and not allow_rebind
            )
        ),
        width="stretch",
    ):
        try:
            saved = runtime.confirm_binding(
                profile.account_key,
                identity,
                confirmed_by=get_current_user() or "admin",
                allow_rebind=allow_rebind,
            )
        except (AccountBindingConflict, ValueError, RuntimeError) as exc:
            st.error(f"绑定失败：{exc}")
        else:
            st.session_state.pop(pending_key, None)
            st.success(f"绑定成功：{saved.display_identity}")
            st.rerun()


def _render_account_maintenance(
    profile: AccountProfile,
    profile_repository: AccountProfileRepository,
) -> None:
    st.markdown("### 账号健康与运营维护")
    st.caption(
        "检查登录、调研相关内容、播放高相关视频、同步自己的作品与评论；"
        "播放互动仅在管理员明确启用后执行。"
    )
    if not has_permission(get_current_role(), "admin"):
        st.info("只有管理员可以执行账号维护；当前页面仍可查看账号状态和历史日志。")
        can_run = False
    else:
        can_run = True
    binding = AccountBindingRepository(profile_repository.db_path).get_optional(
        profile.account_key
    )
    can_run = can_run and bool(binding and binding.status == "active")
    mode = st.selectbox(
        "维护模式",
        ["daily", "pre-publish", "playback", "post-publish"],
        format_func=lambda value: {
            "daily": "daily · 登录健康 + 有限相关内容调研",
            "pre-publish": "pre-publish · 近期同领域内容与用户反馈",
            "playback": "playback · 高相关内容播放维护",
            "post-publish": "post-publish · 同步自己的作品数据与评论",
        }[value],
        key=f"maintenance_mode_{profile.account_key}",
    )
    authorization_reference = st.text_input(
        "调研授权说明/工单编号",
        placeholder="daily / pre-publish / playback 必填",
        disabled=mode == "post-publish",
        key=f"maintenance_auth_{profile.account_key}",
    )
    confirmed = st.checkbox(
        "我确认使用当前绑定账号执行本次维护",
        value=False,
        disabled=mode == "post-publish",
        key=f"maintenance_confirm_{profile.account_key}",
    )
    missing_authorization = mode != "post-publish" and (
        not authorization_reference.strip() or not confirmed
    )
    playback_options = None
    visible_browser = False
    interaction_confirmed = True
    if mode == "playback":
        st.info(
            f"播放前会重新核验绑定身份：{binding.display_identity if binding else '未绑定'}。"
            "候选只来自本次分析结果，不访问随机推荐页。"
        )
        limit_col, per_video_col, total_col, relevance_col = st.columns(4)
        with limit_col:
            playback_max_videos = st.number_input(
                "视频数",
                min_value=1,
                max_value=20,
                value=20,
                step=1,
                key=f"playback_max_videos_{profile.account_key}",
            )
        with per_video_col:
            playback_seconds = st.number_input(
                "单条上限（秒）",
                min_value=5,
                max_value=300,
                value=90,
                step=5,
                key=f"playback_seconds_{profile.account_key}",
            )
        with total_col:
            playback_minutes = st.number_input(
                "总时长（分钟）",
                min_value=1,
                max_value=60,
                value=20,
                step=1,
                key=f"playback_minutes_{profile.account_key}",
            )
        with relevance_col:
            min_relevance_score = st.number_input(
                "最低相关度",
                min_value=0.0,
                max_value=100.0,
                value=60.0,
                step=5.0,
                key=f"playback_relevance_{profile.account_key}",
            )
        visible_browser = st.checkbox(
            "使用可见浏览器",
            value=True,
            help="推荐开启，可减少无头浏览器与正常页面返回结果不一致的问题。",
            key=f"playback_visible_{profile.account_key}",
        )
        interaction_col, comment_col = st.columns(2)
        with interaction_col:
            auto_like = st.checkbox(
                "自动点赞",
                value=False,
                help="仅在真实播放进度通过校验后，按动态比例和单条点赞表现决定。",
                key=f"playback_auto_like_{profile.account_key}",
            )
            base_like_percent = st.slider(
                "基础点赞比例（%）",
                min_value=0,
                max_value=80,
                value=25,
                step=5,
                disabled=not auto_like,
                help="这是计算起点；系统会按候选相关度和点赞表现动态上调或下调。",
                key=f"playback_like_ratio_{profile.account_key}",
            )
        with comment_col:
            auto_comment = st.checkbox(
                "安全自动评论",
                value=False,
                help="学习评论区表达族后使用批准模板改写，过滤广告和重复内容。",
                key=f"playback_auto_comment_{profile.account_key}",
            )
            base_comment_percent = st.slider(
                "基础评论比例（%）",
                min_value=0,
                max_value=20,
                value=5,
                step=1,
                disabled=not auto_comment,
                help="按当天已验证播放量形成动态预算，仍受评论冷却和同作者限制。",
                key=f"playback_comment_ratio_{profile.account_key}",
            )
        if auto_like or auto_comment:
            interaction_confirmed = st.checkbox(
                "我确认本次允许系统按动态比例执行点赞/评论",
                value=False,
                key=f"playback_interaction_confirm_{profile.account_key}",
            )
            st.caption(
                "每日互动不再使用固定次数：预算根据当天已验证播放量和本批候选质量动态计算；"
                "高点赞表现且高相关的视频会获得更高点赞概率。"
                "评论会拦截联系方式、链接、私信引流、免费咨询等广告表达；"
                "同一作者每天最多评论一次，评论间隔至少 30 分钟。"
            )
        playback_options = PlaybackOptions(
            max_videos=int(playback_max_videos),
            per_video_seconds=int(playback_seconds),
            total_minutes=int(playback_minutes),
            min_relevance_score=float(min_relevance_score),
            auto_like=bool(auto_like),
            auto_comment=bool(auto_comment),
            base_like_ratio=float(base_like_percent) / 100 if auto_like else 0,
            base_comment_ratio=(
                float(base_comment_percent) / 100 if auto_comment else 0
            ),
        )
        missing_authorization = missing_authorization or not interaction_confirmed
    if st.button(
        "运行账号健康与运营维护",
        type="primary",
        width="stretch",
        disabled=not can_run or missing_authorization,
        key=f"run_maintenance_{profile.account_key}",
    ):
        with st.spinner("正在执行账号维护；遇到安全验证会停止并记录原因..."):
            result = AccountMaintenanceService().run(
                profile.account_key,
                mode,
                authorization_reference=authorization_reference,
                headless=not visible_browser if mode == "playback" else True,
                playback_options=playback_options,
            )
        if result.status == "completed":
            st.success(result.message)
        else:
            st.error(result.message)
        policy = result.interaction_policy
        if policy.get("budget_mode") == "dynamic_daily_ratio":
            ratio_like_col, ratio_comment_col, target_col, action_col = st.columns(4)
            ratio_like_col.metric(
                "本次动态点赞比例",
                f"{float(policy.get('adaptive_like_ratio') or 0):.1%}",
            )
            ratio_comment_col.metric(
                "本次动态评论比例",
                f"{float(policy.get('adaptive_comment_ratio') or 0):.1%}",
            )
            target_col.metric(
                "当日动态目标",
                f"赞 {policy.get('realized_daily_like_target', 0)} / "
                f"评 {policy.get('realized_daily_comment_target', 0)}",
            )
            action_col.metric(
                "本次实际互动",
                f"赞 {result.likes_performed} / 评 {result.comments_sent}",
            )
        st.json(asdict(result))

    log_dir = Path("data/account_maintenance") / profile.account_key
    log_paths = (
        sorted(log_dir.glob("maintenance_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:5]
        if log_dir.exists()
        else []
    )
    if log_paths:
        with st.expander("最近账号维护日志", expanded=False):
            for path in log_paths:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                st.caption(
                    f"{payload.get('finished_at', '')} · {payload.get('mode', '')} · "
                    f"{payload.get('status', '')} · 相关去重视频 "
                    f"{payload.get('unique_relevant_videos', 0)} · 验证播放 "
                    f"{payload.get('playback_verified_videos', 0)} · 互动 "
                    f"{payload.get('interaction_actions', 0)} · 动态点赞比例 "
                    f"{float((payload.get('interaction_policy') or {}).get('adaptive_like_ratio') or 0):.1%}"
                )


def _render_research_run_logs() -> None:
    st.markdown("---")
    section_header(
        "视频研究运行日志",
        "按账号记录采集、去重、内容分析和机会排行的阶段结果。",
    )
    log_dir = Path("data/trend_research_runs")
    if not log_dir.exists():
        st.info("暂无完整研究流程日志。")
        return
    payloads = []
    for path in log_dir.glob("research_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["_path"] = str(path)
        payloads.append(payload)
    def recorded_time(payload):
        try:
            value = datetime.fromisoformat(payload.get("finished_at", ""))
            return value.timestamp() if value.tzinfo else 0
        except (TypeError, ValueError):
            return 0
    payloads = sorted(payloads, key=recorded_time, reverse=True)[:20]
    if not payloads:
        st.info("暂无可读取的完整研究流程日志。")
        return
    st.dataframe(
        [
            {
                "本次研究运行结束（北京时间）": (
                    datetime.fromtimestamp(recorded_time(item), timezone(timedelta(hours=8))).isoformat(timespec="seconds")
                    if recorded_time(item) else "未记录"
                ),
                "账号": item.get("account_key", ""),
                "状态": item.get("status", ""),
                "采集观察": item.get("collected_observations", 0),
                "不同视频": item.get("unique_videos", 0),
                "内容分析": item.get("content_analyses", 0),
                "音画表达证据齐全": item.get("media_readiness", {}).get("ready_count", "历史未记录"),
                "机会": item.get("opportunities", 0),
                "停止原因": item.get("stopped_reason", ""),
            }
            for item in payloads
        ],
        width="stretch",
        hide_index=True,
    )
    latest = payloads[0]
    with st.expander("最近一次阶段明细"):
        st.dataframe(latest.get("stages", []), width="stretch", hide_index=True)
        st.caption(f"日志文件：{latest['_path']}")


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
        "逐条分析核心表达、音频表达、画面动作和道具证据；页面元数据只用于筛选，不能代替原视频。",
    )
    if account_profile is None:
        st.info("选择账号后才能计算候选内容与账号定位的相关度。")
        return
    st.caption(POLICY_TEXT)
    observations = batch_observations(repository, account_uuid=account_profile.account_uuid)
    latest_by_item = {}
    for item in observations:
        latest_by_item.setdefault(item.video_id, item)
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
                "metadata_heuristic": "元数据筛选（不能用于编剧）",
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
    manifest_valid = True
    run_toolchain = False
    media_confirmed = False
    if implementation_id == "local_qwen_paraformer":
        mapping_text = st.text_area(
            "本批原视频与分析产物清单 JSON",
            value=json.dumps({"schema": "research_local_media/v1",
                "collection_run_id": candidates[0].run_id,
                "account_uuid": account_profile.account_uuid, "items": []}, ensure_ascii=False, indent=2),
            help=(
                'items 每项须含 item_id、video_id、video（原视频本地路径），可附 '
                'qwen、transcript、scenes 路径。清单必须绑定本次账号及采集批次。'
            ),
            key="trend_content_artifact_mapping",
        )
        try:
            artifact_mapping = load_local_media_manifest(
                json.loads(mapping_text or "{}"), collection_run_id=candidates[0].run_id,
                account_uuid=account_profile.account_uuid, candidates=candidates,
            )
            manifest_valid = bool(artifact_mapping)
        except (ValueError, OSError) as exc:
            manifest_valid = False
            st.error(f"媒体清单无效：{exc}")
        with st.expander("本批来源身份（用于绑定原视频）"):
            st.dataframe([{"item_id": item.item_id, "video_id": item.video_id,
                "标题": item.title, "来源": item.url} for item in candidates], hide_index=True)
        run_toolchain = st.checkbox(
            "缺少产物时自动执行本地抽帧、Qwen 和 Paraformer 脚本",
            value=True,
            key="trend_run_local_content_toolchain",
        )
        media_confirmed = st.checkbox(
            "我确认这些本地媒体有分析权限，仅用于内部选题研究",
            value=False,
            key="trend_local_media_authorized",
        )
    selected_ids = {item.video_id for item in candidates[:candidate_count]}
    gate = evaluate_sample([item for item in observations if item.video_id in selected_ids])
    (st.success if gate.passed else st.warning)(gate.message)
    analyze_clicked = st.button(
        "批量分析候选内容",
        type="primary",
        disabled=(not gate.passed or (implementation_id == "local_qwen_paraformer" and (not media_confirmed or not manifest_valid))),
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
                    duration_seconds=item.duration_seconds,
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
        try:
            with st.spinner("正在分析内容结构、展示方式与账号相关度..."):
                result = ContentAnalysisBatchService(repository).analyze(
                    requests,
                    implementation_id=implementation_id,
                    allow_metadata_fallback=False,
                    run_local_toolchain=run_toolchain,
                    collection_run_id=gate.run_id,
                )
        except (SampleGateError, ValueError) as exc:
            st.error(str(exc))
            return
        readiness = cohort_media_readiness(result.analyses, candidates[:candidate_count])
        (st.success if readiness["ready"] else st.warning)(
            f"音画表达证据齐全 {readiness['ready_count']}/{readiness['required_count']}；"
            f"失败 {result.failed_count}，缓存命中 {result.cached_count}。"
            + ("可进入剧本生成。" if readiness["ready"] else "证据不足，剧本生成保持阻断。")
        )
        for error in result.errors:
            st.warning(error)
    analyses = repository.list_content_analyses(
        account_uuid=account_profile.account_uuid,
        limit=200,
    )
    current_items = {item.item_id for item in candidates}
    latest_analyses = {}
    for analysis in analyses:
        if analysis.item_id in current_items and analysis.profile_version == account_profile.profile_version:
            latest_analyses.setdefault(analysis.item_id, analysis)
    analyses = list(latest_analyses.values())
    if analyses:
        st.dataframe(
            [
                {
                    "视频": item.title,
                    "状态": item.status,
                    "实现": item.provider_id,
                    "音画证据": "齐全" if media_readiness(item, verify_artifacts=False)["ready"] else "不足，不能用于编剧",
                    "核心表达": (getattr(item, "expression_analysis", {}).get("core_message") or {}).get("text", ""),
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
        expression_analyses = [item for item in analyses if getattr(item, "expression_analysis", {})]
        if expression_analyses:
            selected_analysis_id = st.selectbox("查看逐条核心表达与音画证据",
                [item.analysis_id for item in expression_analyses],
                format_func=lambda value: next(item.title for item in expression_analyses if item.analysis_id == value),
                key="trend_expression_analysis_detail")
            selected = next(item for item in expression_analyses if item.analysis_id == selected_analysis_id)
            expression = selected.expression_analysis
            st.write((expression.get("core_message") or {}).get("text", "核心表达待分析"))
            modes = {"prop_demonstration": "实物演示", "conflict_drama": "人物冲突",
                "direct_explanation": "直接讲解", "question_answer": "知识问答",
                "case_reenactment": "情景还原", "screen_demonstration": "屏幕演示",
                "text_cards": "文字卡片", "interview": "访谈", "mixed": "混合表达"}
            st.caption("表达方式：" + "、".join(modes.get(row.get("mode"), row.get("mode", ""))
                for row in expression.get("expression_modes", [])))
            for label, key in (("画面如何表达", "visual_expression"), ("语句如何表达", "audio_expression")):
                st.write(label)
                st.dataframe([{"表达方式": row.get("text", ""), "证据": "、".join(row.get("evidence_ids", []))}
                    for row in expression.get(key, [])], hide_index=True)
            st.caption("音频转写支持台词及句式分析；声线、语气和口型是否匹配仍需听看原片确认。")
            st.dataframe([{"证据": row.get("id"), "来源": "画面" if row.get("channel") == "visual" else "音频转写",
                "原片时间（秒）": f"{row.get('start_seconds')}—{row.get('end_seconds')}", "观察": row.get("text")}
                for row in expression.get("evidence", [])], hide_index=True)


def _script_source_selection_key(account_uuid, selected_media):
    run_id = str((selected_media.get("sample_gate") or {}).get("run_id") or "")
    ids = list(selected_media.get("selected_item_ids") or [])
    return hashlib.sha256(json.dumps([account_uuid, run_id, ids], ensure_ascii=False).encode()).hexdigest()[:24]


def _acquire_selected_script_media(script_service, script_request, profile, repository, state,
                                   *, expected_readiness=None, service_factory=None):
    """Acquire exactly the script selection, retaining its account browser on rerun.

    This helper does not call the content-analysis, script or video models.
    """
    if script_request.account_key != profile.account_key:
        raise ValueError("原片获取账号与脚本账号不一致")
    selected = script_service.source_media_readiness(script_request, verify_artifacts=False)
    ids = list(selected.get("selected_item_ids") or [])
    run_id = str((selected.get("sample_gate") or {}).get("run_id") or "")
    if not run_id or not ids or len(ids) != len(set(ids)):
        raise ValueError("脚本筛选结果缺少明确的同批来源")
    if script_request.collection_run_id and script_request.collection_run_id != run_id:
        raise ValueError("原片获取批次与脚本请求不一致")
    selection_key = _script_source_selection_key(profile.account_uuid, selected)
    if expected_readiness is not None and selection_key != _script_source_selection_key(profile.account_uuid, expected_readiness):
        raise ValueError("来源筛选已变化，请核对当前列表后再次获取")
    rows = batch_observations(repository, account_uuid=profile.account_uuid, run_id=run_id)
    chosen = {}
    for row in rows:
        if row.item_id in ids:
            if row.item_id in chosen and chosen[row.item_id].video_id != row.video_id:
                raise ValueError("来源标识对应多个视频，不能确定原片")
            chosen.setdefault(row.item_id, row)
    if set(chosen) != set(ids):
        raise ValueError("所选来源不完整或不属于当前账号批次")
    candidates = [chosen[item_id] for item_id in ids]
    if any(row.run_id != run_id for row in candidates) or len({row.video_id for row in candidates}) != len(candidates):
        raise ValueError("所选原片必须来自同一批次且视频 ID 不重复")

    from scripts.acquire_source_media import build_acquisition_policy
    if service_factory is None:
        from src.trend_intelligence.source_media_acquisition import SourceMediaAcquisitionService
        service_factory = SourceMediaAcquisitionService
    slots = state.setdefault("pre_video_source_acquisition_sessions", {})
    slot = slots.get(profile.account_uuid)
    if slot is None:
        acquisition = service_factory(session_factory=lambda: build_account_douyin_trend_session(profile.account_key, headless=False))
        slot = {"account_key": profile.account_key, "service": acquisition, "session": None}
        slots[profile.account_uuid] = slot
    elif slot["account_key"] != profile.account_key:
        raise ValueError("已保留的认证会话账号不匹配")
    acquisition = slot["service"]
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    if slot.get("usage_date") != today:
        slot.update(usage_date=today, pages_used_today=0)
    reference = (f"用户点击获取所选原片；账号{profile.account_uuid}，采集批次{run_id}，"
                 f"脚本已选{len(candidates)}条，选择摘要{selection_key}；仅获取原视频供后续音画表达研究，不发布或生成。")
    try:
        result = acquisition.acquire(candidates, account_uuid=profile.account_uuid, collection_run_id=run_id,
            policy=build_acquisition_policy(reference, max_items=len(candidates)), session=slot.get("session"),
            max_items=len(candidates), pages_used_today=slot.get("pages_used_today", 0))
    finally:
        # Includes human_required and failures: preserve the live page rather
        # than creating/closing another browser when the user clicks again.
        slot["session"] = getattr(acquisition, "session", slot.get("session"))
    payload = result.to_dict()
    slot["pages_used_today"] += int(payload.get("attempted_count") or 0)
    payload.update(account_uuid=profile.account_uuid, collection_run_id=run_id, selected_item_ids=ids,
                   analysis_submitted=False, script_generation_submitted=False, video_generation_submitted=False)
    state.setdefault("pre_video_source_acquisition_results", {})[selection_key] = payload
    return payload


def _render_selected_source_acquisition(script_service, script_request, profile, repository, selected_media):
    count = len(selected_media.get("selected_item_ids") or [])
    if not count:
        return
    st.caption(f"可获取当前脚本筛选的 {count} 条原片。遇到登录或验证会保留当前页面，完成后再次点击同一按钮继续。")
    if st.button("获取所选原片", key="pre_video_acquire_selected_sources"):
        try:
            with st.spinner(f"正在获取当前所选 {count} 条原片，复用已有文件和登录会话..."):
                _acquire_selected_script_media(script_service, script_request, profile, repository,
                    st.session_state, expected_readiness=selected_media)
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            st.error(f"原片获取未完成：{exc}")
    key = _script_source_selection_key(profile.account_uuid, selected_media)
    result = st.session_state.get("pre_video_source_acquisition_results", {}).get(key)
    if not result:
        return
    acquired, cached = int(result.get("acquired_count") or 0), int(result.get("cached_count") or 0)
    message = f"原片文件就绪 {acquired + cached}/{result['selected_count']} 条：本次获取 {acquired} 条，复用缓存 {cached} 条。"
    (st.success if result.get("status") == "completed" else st.info)(message)
    if result.get("stopped_reason"):
        st.warning(result["stopped_reason"])
    if result.get("manifest_path"):
        st.caption("本地媒体清单（后续音画分析使用）")
        st.code(result["manifest_path"], language=None)
    st.caption("原片获取不代表音画分析通过；本按钮不会自动调用分析模型、编剧或视频生成。")


def _render_briefs(
    repository: TrendRepository,
    service: TrendOperationsService,
    account_repository: AccountProfileRepository,
) -> None:
    from src.trend_intelligence.pre_video_script import (
        PreVideoScriptRequest,
        PreVideoScriptService,
        render_script_markdown,
    )

    section_header(
        "生成视频前的脚本分析",
        "每次生成短视频、长视频两版完整分镜：无旁白，以人物动作和对白推进，逐镜交代构图、光线与摄影。",
    )
    profiles = account_repository.list_active()
    if not profiles:
        st.warning("请先配置运营账号。")
        return

    account_key = st.selectbox(
        "脚本账号",
        [item.account_key for item in profiles],
        format_func=lambda value: _account_profile_label(profiles, value),
        key="pre_video_script_account",
    )
    script_service = PreVideoScriptService(
        repository=repository,
        profile_repository=account_repository,
    )
    saved_pair = _load_saved_script_pair(account_repository.get(account_key).account_uuid)
    st.caption(POLICY_TEXT)
    st.caption("筛选后仍须保留至少 20 条同批来源，并逐条完成原视频音频、抽帧和核心表达分析；缺失时停止生成剧本。")
    st.caption("采样得分与加权特征支持度用于筛选，不能当作剧本参考贡献率。实际借鉴应列明来源和音画时间段。")
    source_profile = account_repository.get(account_key)
    source_candidates = batch_observations(repository, account_uuid=source_profile.account_uuid)
    source_analyses = repository.list_content_analyses(account_uuid=source_profile.account_uuid, limit=100_000)
    source_readiness = cohort_media_readiness(source_analyses, source_candidates, verify_artifacts=False)
    if not source_readiness["ready"]:
        st.warning(f"本批音画表达证据齐全 {source_readiness['ready_count']}/{source_readiness['required_count']} 条。生成门槛按下方实际筛选的来源核对。")
        with st.expander("待补齐的原视频分析"):
            st.dataframe([{ "item_id": row["item_id"], "video_id": row["video_id"],
                "缺失": "；".join(row["reasons"])} for row in source_readiness["missing"]], hide_index=True)
    col_window, col_relevance, col_traffic = st.columns(3)
    window_days = col_window.number_input(
        "发布时间窗口（天，0 表示不限）",
        min_value=0,
        max_value=30,
        value=0,
        step=1,
        key="pre_video_script_window_days",
    )
    min_relevance = col_relevance.number_input(
        "最低账号相关度",
        min_value=0.0,
        max_value=100.0,
        value=50.0,
        step=5.0,
        key="pre_video_script_min_relevance",
    )
    high_traffic_share = col_traffic.slider(
        "高流量样本范围",
        min_value=10,
        max_value=50,
        value=30,
        step=5,
        format="前 %d%%",
        help="在时间、账号相关度和视频类型筛选之后，取页面展示指标靠前的样本计算跨视频重合特征。",
        key="pre_video_script_high_traffic_share",
    )
    try:
        type_counts = script_service.recent_video_type_counts(
            account_key,
            window_days=int(window_days) or None,
            min_relevance=float(min_relevance),
        )
    except (KeyError, ValueError, OSError) as exc:
        st.error(f"读取近期视频类型失败：{exc}")
        return
    if not type_counts:
        st.info("当前批次及筛选条件下没有可用视频类型，请先采集并分析样本。")
        if saved_pair:
            _render_script_pair_result(saved_pair)
        return

    type_labels = {
        "unknown": "表现形式未识别（仅元数据）",
        "mixed": "案例/口播/素材混合",
        "talking_head": "真人口播",
        "interview": "采访/连线",
        "screen_recording": "录屏讲解",
        "slideshow": "图文卡片",
    }
    video_types = st.multiselect(
        "本批视频类型",
        list(type_counts),
        default=list(type_counts),
        format_func=lambda value: (
            f"{type_labels.get(value, value)} · {type_counts[value]} 条本批样本"
        ),
        key="pre_video_script_types",
    )
    short_col, long_col = st.columns(2)
    short_seconds = short_col.number_input("短视频时长（秒）", min_value=30, max_value=120, value=45, step=15, key="script_pair_short_seconds")
    long_seconds = long_col.number_input("长视频时长（秒）", min_value=120, max_value=600, value=180, step=30, key="script_pair_long_seconds")
    st.caption("短版约 45 秒：一个可见的核心冲突，以人物动作、对白和实物推进，出现转折并有明确结局。长版扩展冲突过程和证据；法律内容同时交代适用边界。")
    script_request = None
    selected_media_ready = False
    if video_types and long_seconds > short_seconds:
        try:
            script_request = PreVideoScriptRequest(
                account_key=account_key, recent_video_types=tuple(video_types),
                window_days=int(window_days) or None, min_relevance=float(min_relevance),
                high_traffic_percentile=1 - float(high_traffic_share) / 100,
                short_seconds=int(short_seconds), long_seconds=int(long_seconds),
            )
            selected_media = script_service.source_media_readiness(script_request, verify_artifacts=False)
            selected_media_ready = selected_media["ready"]
            (st.success if selected_media_ready else st.warning)(selected_media["message"])
            if not selected_media_ready:
                _render_selected_source_acquisition(script_service, script_request, source_profile,
                    repository, selected_media)
        except (KeyError, ValueError, OSError) as exc:
            st.warning(str(exc))
    if st.button(
        "生成短版 + 长版剧本",
        type="primary",
        disabled=not selected_media_ready,
        key="pre_video_script_generate",
    ):
        try:
            with st.spinner("正在编写、审稿并按问题修改短版与长版..."):
                artifact = script_service.generate(script_request)
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            st.error(f"剧本生成失败：{exc}")
        else:
            st.session_state["pre_video_script_pair_result"] = {
                "account_key": account_key,
                "scripts": [{"kind": item.script.format_kind,
                             "duration": item.script.target_duration_seconds,
                             "markdown": render_script_markdown(item.script),
                             "json": Path(item.script_json_path).read_text(encoding="utf-8"),
                             "manifest_path": str(Path(artifact.manifest_path).resolve()),
                             "script_path": str(Path(item.script_path).resolve()),
                             "script_json_path": str(Path(item.script_json_path).resolve())}
                            for item in (artifact.short, artifact.long)],
            }
            st.success("已保存短版与长版；下方将核对当前审核记录，已停在生成视频前。")

    pair_result = st.session_state.get("pre_video_script_pair_result", {})
    if pair_result.get("account_key") == account_key:
        _render_script_pair_result(pair_result.get("scripts", []))
    elif saved_pair:
        st.caption('最近一次工作流生成结果 · 待人工审核 · 已停在生成视频前')
        _render_script_pair_result(saved_pair)


def _load_saved_script_pair(account_uuid, output_dir=None):
    """Load the latest saved pair by its recorded timestamp, never file mtime."""
    root = Path(output_dir) if output_dir else Path(__file__).resolve().parents[2] / 'data/pre_video_scripts'
    root = root.resolve()
    candidates = []
    for path in root.glob('*.pair.json'):
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if manifest.get('account_uuid') != account_uuid or manifest.get('video_generation_submitted') is not False:
                continue
            created_at = datetime.fromisoformat(manifest['created_at'])
            if created_at.tzinfo is None:
                continue
            scripts = []
            for kind in ('short', 'long'):
                paths = [(root / manifest[kind][key]).resolve() for key in ('script_path', 'script_json_path')]
                if any(root not in p.parents for p in paths):
                    raise ValueError('Script path outside output directory')
                # Keep the remaining historical text visible if its companion
                # artifact is damaged; the fresh review check will fail closed.
                try:
                    markdown = paths[0].read_text(encoding='utf-8')
                except OSError:
                    markdown = '历史 Markdown 文件不可读取；当前稿需复核。'
                try:
                    raw = paths[1].read_text(encoding='utf-8')
                except OSError:
                    raw = ''
                try:
                    script = json.loads(raw)
                    script = script if isinstance(script, dict) else {}
                except (TypeError, ValueError):
                    script = {}
                if (('account_uuid' in script and script['account_uuid'] != account_uuid)
                        or ('format_kind' in script and script['format_kind'] != kind)):
                    raise ValueError('Script account or format mismatch')
                scripts.append(dict(kind=kind, duration=script.get('target_duration_seconds'), markdown=markdown, json=raw,
                                    manifest_path=str(path.resolve()), script_path=str(paths[0]),
                                    script_json_path=str(paths[1])))
            candidates.append((created_at, scripts))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not candidates:
        return []
    scripts = max(candidates, key=lambda row: row[0])[1]
    # This is informational only; rendering repeats the check for live caches.
    review = current_saved_script_review(scripts, allowed_root=root)
    for item in scripts:
        item['current_review'] = review
    return scripts


def _render_legacy_briefs(
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
            try:
                service.analyze(account_profile=opportunity_profile, limit=100_000)
            except SampleGateError as exc:
                st.error(str(exc))
                return
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
                    st.button(
                        f"脚本 {script.variant_id} 暂不可带入视频制作",
                        disabled=True,
                        key=f"trend_use_script_{script.script_id}",
                        help="旧视频流程已归档；新流程通过质量验收后重新开放。",
                    )
        else:
            st.info("暂无机会卡。先完成采集和内容分析，再刷新账号机会排行。")
    else:
        st.warning("请先配置运营账号。")

    st.markdown("---")
    section_header(
        "选题审批",
        "选题分析与审批继续保留；旧视频制作入口已关闭。",
    )
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
            "视频制作入口已重置",
            width="stretch",
            disabled=True,
            help="等待新视频流程通过质量验收后重新开放。",
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


def _render_feedback(
    repository: TrendRepository,
    account_repository: AccountProfileRepository,
) -> None:
    section_header(
        "发布效果复盘",
        "按 1h/6h/24h/72h/7d 窗口，并按脚本、钩子、展示方式、工作流和发布时间归因。",
    )
    profiles = account_repository.list_active()
    selected_profile = None
    if profiles:
        feedback_account_key = st.selectbox(
            "复盘账号",
            [item.account_key for item in profiles],
            format_func=lambda value: _account_profile_label(profiles, value),
            key="trend_feedback_account",
        )
        selected_profile = next(
            item for item in profiles if item.account_key == feedback_account_key
        )
    feedback = OperationsFeedbackService(repository)
    account_uuid = selected_profile.account_uuid if selected_profile else ""
    results = feedback.performance_results(account_uuid=account_uuid)
    recommendation = feedback.recommend_next_cycle(account_uuid=account_uuid)
    st.info(recommendation.summary)
    metrics = st.columns(4)
    metrics[0].metric("有效样本", recommendation.sample_size)
    metrics[1].metric("策略状态", recommendation.status)
    metrics[2].metric("验证题材", len(recommendation.proven_topics))
    metrics[3].metric("实验比例", f"{recommendation.experiment_share:.0%}")
    due = feedback.due_snapshot_windows(account_uuid=account_uuid)
    if due:
        st.warning(f"有 {len(due)} 个指标时间窗待同步。")
        with st.expander("待同步时间窗"):
            st.dataframe(
                [
                    {
                        "视频": item.video_id or item.local_id,
                        "窗口": item.window,
                        "目标时间": item.target_at,
                        "逾期小时": item.overdue_hours,
                    }
                    for item in due
                ],
                width="stretch",
                hide_index=True,
            )
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
                    "指标窗口": result.latest_window,
                    "脚本版本": result.script_variant,
                    "钩子": result.hook_type,
                    "展示方式": result.presentation_type,
                    "工作流": result.workflow_profile,
                    "发布时间窗": result.publish_window,
                }
                for result in results
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("尚无包含两个快照的已关联视频。每次同步创作者作品都会自动保存快照。")
    dimensions = feedback.dimension_performance(account_uuid=account_uuid)
    if dimensions:
        with st.expander("多维归因", expanded=True):
            st.dataframe(
                [
                    {
                        "维度": item.dimension,
                        "取值": item.value,
                        "样本": item.sample_size,
                        "相对表现": item.average_relative_performance,
                        "播放增速": item.average_view_velocity,
                        "每千播放互动": item.average_engagement_per_1k,
                        "胜率": item.win_rate,
                        "置信度": item.confidence,
                    }
                    for item in dimensions
                ],
                width="stretch",
                hide_index=True,
            )
    if selected_profile and st.button(
        "生成并保存下一轮学习报告", key="trend_build_feedback_report"
    ):
        report = feedback.build_learning_report(
            account_uuid=selected_profile.account_uuid,
            profile_version=selected_profile.profile_version,
        )
        st.success(
            f"学习报告已保存：{report.sample_size} 个有效视频，"
            f"{len(report.score_adjustments)} 个维度调权。"
        )


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



def _analyze_with_sample_gate(service, **kwargs):
    """Keep collection results visible when the subsequent analysis is blocked."""
    try:
        return service.analyze(**kwargs)
    except SampleGateError as exc:
        st.warning(str(exc))
        return [], []



def _render_script_pair_result(scripts):
    if not scripts:
        return
    # Never inherit a badge from session_state, a manifest flag, or an older
    # rendering. This is a local read-only check and cannot trigger paid review.
    review = current_saved_script_review(scripts)
    if review['current_passed']:
        st.success('当前协议审核记录与本稿、来源证据一致；仍待用户审核。')
        st.caption('此状态仅核验文本剧本审核，不代表视频的声线、口型或画面已检查。')
    else:
        st.warning(f"需复核 · {review['reason']}。历史稿仍可阅读；不会自动发起付费重审。")
    def label(item):
        duration = item.get('duration')
        duration_label = f'{duration:g} 秒' if type(duration) in (int, float) and 0 < duration < float('inf') else '时长待核对'
        return f"{'短视频' if item['kind'] == 'short' else '长视频'} · {duration_label}"
    tabs = st.tabs([label(item) for item in scripts])
    for tab, item in zip(tabs, scripts):
        with tab:
            # Storyboards stay visible; model submission text is secondary to review.
            import re
            review_markdown = re.sub(r'<details>.*?</details>', '', item['markdown'], flags=re.DOTALL)
            st.markdown(review_markdown)
            try:
                script = json.loads(item['json'])
                script = script if isinstance(script, dict) else {}
            except (TypeError, ValueError):
                script = {}
            if script.get('shots'):
                with st.expander('查看逐镜视频提示词（尚未生成视频）'):
                    for shot in script['shots']:
                        if isinstance(shot, dict):
                            st.markdown(f"**{shot.get('shot_id', '未标明镜号')}**")
                            st.text(shot.get('model_prompt_zh', '历史稿未保存本镜视频提示词'))
            st.download_button("下载剧本 Markdown", item['markdown'], file_name=f"script-{item['kind']}.md", key=f"script_pair_md_{item['kind']}")
            st.download_button("下载剧本 JSON", item['json'], file_name=f"script-{item['kind']}.json", mime="application/json", key=f"script_pair_json_{item['kind']}")


if __name__ == "__main__":
    from src.web.components.ui import inject_app_theme

    st.set_page_config(page_title="热门选题", page_icon="⌁", layout="wide")
    inject_app_theme()
    st.navigation(
        [st.Page(page_trend_operations, title="热门选题", icon="📈")],
        position="sidebar",
    ).run()
