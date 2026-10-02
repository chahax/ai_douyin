"""Streamlit dashboard for Dreamina CLI and BytePlus Seedance channels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.content_factory.dreamina_cli import (
    DreaminaCLIClient,
    DreaminaCLIConfig,
    DreaminaCLIError,
)
from src.services.seedance_usage_service import summarize_seedance_usage
from src.content_factory.seedance_models import load_catalog
from src.shared.config import settings
from src.web.components.ui import page_header, section_header


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_LABELS = {
    "ark_api": "火山方舟 API（Seedance 系列）",
    "dreamina_cli": "即梦 CLI（网页套餐）",
    "byteplus_api": "BytePlus API",
}


def page_seedance_usage() -> None:
    page_header(
        "视频用量与余额",
        "先看账户余额与生成用量，再按渠道核对每次生成记录。所有时间统一为北京时间。",
        icon="▶",
        eyebrow="VIDEO GENERATION",
    )

    provider_ids = list(PROVIDER_LABELS)
    configured_provider = _setting("SEEDANCE_PROVIDER", "dreamina_cli")
    default_provider = (
        configured_provider if configured_provider in provider_ids else "dreamina_cli"
    )
    provider = st.selectbox(
        "生成渠道",
        provider_ids,
        index=provider_ids.index(default_provider),
        format_func=PROVIDER_LABELS.get,
        key="seedance_provider",
        help="这里切换看板台账；命令行可用 --provider 指定实际提交渠道。",
    )

    report_dir = _resolve_report_dir(
        _setting("SEEDANCE_USAGE_REPORT_DIR", "data/video_generation/seedance")
    )
    usage = summarize_seedance_usage(
        report_dir,
        provider=provider,
        monthly_budget_usd=float(_setting("SEEDANCE_MONTHLY_BUDGET_USD", 0.0)),
        monthly_quota_seconds=float(_setting("SEEDANCE_MONTHLY_QUOTA_SECONDS", 0.0)),
        usd_per_second_480p=float(
            _setting("SEEDANCE_ESTIMATED_USD_PER_SECOND_480P", 0.2056)
        ),
        usd_per_second_720p=float(
            _setting("SEEDANCE_ESTIMATED_USD_PER_SECOND_720P", 0.4621)
        ),
    )

    from src.operations_accounts import AccountProfileRepository
    from src.web.components.account_scope import select_account_scope
    profiles = AccountProfileRepository().list_active(status=None)
    owner = select_account_scope(profiles, key="usage_account_scope", allow_unassigned=True)
    all_usage = usage
    if owner is not None:
        usage = summarize_seedance_usage(report_dir, provider=provider, account_uuid=owner,
            usd_per_second_480p=float(_setting("SEEDANCE_ESTIMATED_USD_PER_SECOND_480P", 0.2056)),
            usd_per_second_720p=float(_setting("SEEDANCE_ESTIMATED_USD_PER_SECOND_720P", 0.4621)))
    st.caption("当前统计：" + ("全部账号（含历史未归属）" if owner is None else "历史未归属 / 待核对" if owner == "" else next((p.display_name for p in profiles if p.account_uuid == owner), owner)))
    st.info("供应商余额由多个抖音账号共用，下方只展示一份公共余额；账号筛选仅改变生成用量，不拆分或累加公共余额。")
    if provider != "ark_api":
        totals = st.columns(2)
        totals[0].metric("本月接口生成成功", usage["summary"]["period_succeeded_count"])
        totals[1].metric("本月生成时长（含重试）", f"{usage['summary']['generated_seconds']:.1f} 秒")
    if provider == "dreamina_cli":
        _render_dreamina_channel()
    elif provider=='ark_api':
        _render_ark_channel(usage['summary'])
    else:
        _render_byteplus_channel(usage["summary"])

    if owner is None:
        st.subheader('本月多账号用量对比')
        labels = {p.account_uuid: p.display_name or p.account_key for p in profiles}
        rows = [{'账号': labels.get(row['account_uuid'], row['account_key'] or row['account_uuid'] or '历史未归属 / 待核对'),
                 '生成请求': row['task_count'], '接口成功': row['succeeded_count'],
                 '生成秒数（含重试）': round(row['generated_seconds'], 3),
                 '生成 tokens': row['completion_tokens'],
                 '实际费用': '未接入账单',
                 **({'估算费用 USD': row['estimated_cost_usd']} if provider == 'byteplus_api' else {})}
                for row in all_usage['account_totals']]
        if rows:
            st.dataframe(rows, hide_index=True, width='stretch')
        else:
            st.info('本月暂无该渠道用量。')
        st.caption('有可靠来源的历史记录自动关联；无法证明账号归属的保留为未归属，不默认分给当前账号。')
    st.markdown("---")
    _render_status_and_tasks(usage, report_dir)

    if usage["parse_errors"]:
        with st.expander(f"无法解析的报告（{len(usage['parse_errors'])}）"):
            st.json(usage["parse_errors"])

    if st.button("🔄 刷新本地台账"):
        st.rerun()


def _render_dreamina_channel() -> None:
    st.caption(
        "即梦 CLI 使用当前 Windows 用户的 OAuth 登录状态；查询余额和任务不会产生生成费用。"
    )
    client = DreaminaCLIClient(DreaminaCLIConfig.from_settings())
    with st.expander("渠道默认配置", expanded=False):
        _render_dreamina_defaults(client)

    query_col, link_col = st.columns([1, 2])
    with query_col:
        if st.button("查询即梦余额", disabled=not client.installed):
            try:
                st.session_state["dreamina_credit"] = client.user_credit()
                st.session_state.pop("dreamina_credit_error", None)
            except DreaminaCLIError as exc:
                st.session_state["dreamina_credit_error"] = str(exc)
    with link_col:
        st.link_button("打开即梦网页版", "https://jimeng.jianying.com/ai-tool/home")

    credit = st.session_state.get("dreamina_credit")
    error = st.session_state.get("dreamina_credit_error")
    st.metric("即梦账户可用积分", _credit_display(credit) if isinstance(credit, dict) else "未查询")
    if error:
        st.warning("本次查询失败，已保留上次成功结果。" + _friendly_dreamina_error(str(error)))
    if isinstance(credit, dict):
        st.success(f"即梦账户可用积分：{_credit_display(credit)}")
        with st.expander("余额接口原始结果"):
            st.json(credit)
    else:
        st.info("点击“查询即梦余额”读取套餐剩余积分。第一次使用需先完成 CLI 登录。")

    with st.expander("CLI 登录与能力"):
        st.write(
            "登录后会复用本机 OAuth 状态。支持文生视频、图生视频、首尾帧、"
            "多帧故事和图片/视频/音频全能参考。"
        )
        st.code(f'& "{client.config.executable}" login', language="powershell")
        st.caption("以上登录命令不会生成视频；实际生成任务才会消耗积分。")


def _render_dreamina_defaults(client) -> None:
    state_col, ratio_col, resolution_col, model_col = st.columns(4)
    with state_col:
        st.metric("CLI", "已安装" if client.installed else "未安装")
    with ratio_col:
        st.metric("默认画幅", _setting("SEEDANCE_DEFAULT_RATIO", "9:16"))
    with resolution_col:
        st.metric(
            "默认清晰度",
            str(_setting("SEEDANCE_DEFAULT_RESOLUTION", "480p")).upper(),
        )
    with model_col:
        st.metric("模型", _setting("DREAMINA_MODEL_VERSION", "seedance2.5"))



@st.cache_data(ttl=300, show_spinner=False)
def _cached_ark_balance(scope: str) -> dict:
    from src.services.volcengine_balance import query_account_balance
    return query_account_balance()


def _render_ark_channel(summary: dict[str, Any]) -> None:
    from src.services.volcengine_balance import credential_status, credential_scope
    from src.web.components.auth import get_current_role, has_permission
    from src.web.production_insights import display_time

    allowed = has_permission(get_current_role(), "admin")
    config = credential_status()
    scope = credential_scope() if allowed else "restricted"
    balance_key = "ark_balance_" + scope
    error_key = "ark_balance_error_" + scope
    ready = allowed and all(config.values())
    refresh = st.button("刷新账户余额", disabled=not ready, key="ark_balance_refresh")
    if ready:
        try:
            if refresh:
                _cached_ark_balance.clear(scope)
            st.session_state[balance_key] = _cached_ark_balance(scope)
            st.session_state.pop(error_key, None)
        except ValueError as exc:
            # Preserve the last successful result and label its age on failure.
            st.session_state[error_key] = str(exc)
    balance = st.session_state.get(balance_key) if allowed else None
    placeholder = "未获取" if allowed else "需管理员权限"
    cols = st.columns(4)
    cols[0].metric("账户可用余额", balance.get("available_balance") if balance and balance.get("available_balance") is not None else placeholder)
    cols[1].metric("账户现金余额", balance.get("cash_balance") if balance and balance.get("cash_balance") is not None else placeholder)
    cols[2].metric("本月接口生成成功", summary['period_succeeded_count'])
    cols[3].metric("本月生成时长（含重试）", f"{summary['generated_seconds']:.1f} 秒")
    if balance:
        st.caption("火山引擎账户资金，不是单个模型/API Key 额度。接口未返回独立币种字段，以费用中心账户币种为准。查询时间（UTC+8）：" + display_time(balance['queried_at']))
    if st.session_state.get(error_key):
        st.warning("本次刷新失败；如有余额，保留的是上次成功快照。" + st.session_state[error_key])
    elif not allowed:
        st.info("生成台账可查看；账户资金仅向管理员展示。")
    elif not config['configured']:
        st.info("尚未配置费用中心管理凭证，请由管理员在系统环境配置 VOLCENGINE_ACCESS_KEY 和 VOLCENGINE_SECRET_KEY。推理 API Key 不能查询账户余额。")
    elif not config['sdk_installed']:
        st.warning("余额查询 SDK 未安装：请安装 requirements-volcengine.txt 后刷新。")
    else:
        st.caption("只读余额查询自动复用 5 分钟快照；刷新按钮可立即重新查询，不会生成视频。")
    usage = st.columns(2)
    usage[0].metric('API 返回的生成用量', f"{summary['completion_tokens']:,} tokens" if summary['completion_tokens'] is not None else '未返回')
    usage[1].metric('本月实际费用', '未接入账单明细')
    st.caption(f"统计月份：{summary['billing_period']}（UTC+8）。接口成功不代表质量通过；生成秒数包含重试，不等于可发布成片时长。")
    with st.expander('渠道配置与模型目录', expanded=False):
        st.write('API 配置：' + ('已配置' if _setting('ARK_API_KEY', '') else '未配置'))
        st.write('默认模型：' + str(_setting('ARK_SEEDANCE_MODEL', '未配置')))
        st.caption('默认清晰度：' + str(_setting('SEEDANCE_DEFAULT_RESOLUTION', '480p')) + ' · 默认画幅：' + str(_setting('SEEDANCE_DEFAULT_RATIO', '9:16')))
        catalog = load_catalog()
        st.dataframe([{'型号': m['name'], 'Model ID': m['id'], '时长': f"4–{m['duration_max']} 秒或自动", '清晰度': ' / '.join(m['resolutions']), '输出格式': ' / '.join(m['output_formats'])} for m in catalog['ark_models']], hide_index=True, width='stretch')
        st.caption('已登记型号不代表账户已开通。文字模型免费 tokens 与视频资源包分开计算。')
        st.link_button('打开火山引擎控制台', 'https://console.volcengine.com/ark/region:cn-beijing/overview')
        guide = PROJECT_ROOT / 'docs/reference/seedance/README.md'
        if guide.exists():
            st.download_button('下载型号与调用指南', guide.read_bytes(), file_name='seedance_guide.md')


def _render_byteplus_channel(summary: dict[str, Any]) -> None:
    st.caption(
        "BytePlus 页面读取本地任务报告，不会自动调用付费接口；真实账单以控制台为准。"
    )
    with st.expander("渠道默认配置", expanded=False):
        state_col, ratio_col, resolution_col, model_col = st.columns(4)
        with state_col:
            st.metric(
                "API配置",
                "已配置" if _setting("SEEDANCE_API_KEY", "") else "未配置",
            )
        with ratio_col:
            st.metric("默认画幅", _setting("SEEDANCE_DEFAULT_RATIO", "9:16"))
        with resolution_col:
            st.metric(
                "默认清晰度",
                str(_setting("SEEDANCE_DEFAULT_RESOLUTION", "480p")).upper(),
            )
        with model_col:
            st.metric("模型", "Seedance 2.5")

    spend_col, balance_col, seconds_col, success_col = st.columns(4)
    with spend_col:
        st.metric("本地估算消费", f"${summary['estimated_spend_usd']:.4f}")
    with balance_col:
        remaining_budget = summary["remaining_budget_usd"]
        st.metric(
            "本地预算余额",
            f"${remaining_budget:.4f}" if remaining_budget is not None else "未配置",
        )
    with seconds_col:
        st.metric("成功生成时长", f"{summary['generated_seconds']:.1f} 秒")
    with success_col:
        st.metric("本月成功任务", summary["period_succeeded_count"])

    budget = summary["monthly_budget_usd"]
    if budget:
        spend_ratio = min(float(summary["estimated_spend_usd"]) / float(budget), 1.0)
        st.progress(
            spend_ratio,
            text=(
                f"{summary['billing_period']} 本地月预算使用 {spend_ratio * 100:.1f}% · "
                f"${summary['estimated_spend_usd']:.4f} / ${budget:.2f}"
            ),
        )
    else:
        st.info("在 `.env` 设置 `SEEDANCE_MONTHLY_BUDGET_USD` 后可显示预算余额。")

    quota_seconds = summary["monthly_quota_seconds"]
    if quota_seconds:
        remaining_seconds = float(summary["remaining_quota_seconds"])
        seconds_ratio = min(float(summary["generated_seconds"]) / float(quota_seconds), 1.0)
        st.progress(
            seconds_ratio,
            text=f"本地时长额度剩余 {remaining_seconds:.1f} 秒 / {quota_seconds:.1f} 秒",
        )

    st.warning(
        "BytePlus 生成 API 不返回账户余额；这里是本地推算值，"
        "免费额度、代金券和账单请在控制台核对。"
    )
    st.link_button(
        "打开 BytePlus ModelArk 控制台",
        "https://console.byteplus.com/ark/region:ark+ap-southeast-1/overview",
    )


def _render_status_and_tasks(usage: dict[str, Any], report_dir: Path) -> None:
    summary = usage["summary"]
    section_header(
        f"{PROVIDER_LABELS.get(usage['provider'], '')}任务状态",
        "以下为全历史接口状态；质量审核与发布状态独立记录，不由接口成功推断。",
    )
    status_cols = st.columns(5)
    labels = (
        ("预览", "dry_run_count"),
        ("本地已提交待核对", "submitted_count"),
        ("运行中", "running_count"),
        ("接口成功", "succeeded_count"),
        ("接口失败/拒绝/取消", "failed_count"),
    )
    for column, (label, key) in zip(status_cols, labels):
        with column:
            st.metric(label, summary[key])

    tasks = usage["tasks"]
    period_only = st.checkbox("仅看本月生成记录", value=True)
    if period_only:
        tasks = [item for item in tasks if str(item.get("updated_at", "")).startswith(summary["billing_period"])]
    from src.services.production_registry import task_review_context
    contexts = [task_review_context(item, PROJECT_ROOT) for item in tasks]
    review_cols = st.columns(3)
    review_cols[0].metric("所选范围 · 审核通过记录", sum(c["decision"] in {"passed", "passed_with_previously_accepted_limitations"} for c in contexts))
    review_cols[1].metric("所选范围 · 审核未通过记录", sum(c["decision"] == "failed" for c in contexts))
    review_cols[2].metric("所选范围 · 待核对审核", sum(c["decision"] not in {"passed", "passed_with_previously_accepted_limitations", "failed"} for c in contexts))
    st.caption("审核统计来自片段旁的独立审核记录；未在此重新验帧或听音，完整范围请进入视频制作查看。")
    if tasks:
        rows = [
            {
                "账号": item.get("account_key") or item.get("account_uuid") or "历史未归属 / 待核对",
                "渠道": PROVIDER_LABELS.get(item["provider"], item["provider"]),
                "分段": item["segment_id"],
                "接口状态": item["status"],
                "模型": item.get("model", "未记录"),
                "质量审核记录": context["quality"],
                "项目": context["project"],
                "稿次": context.get("series", ""),
                "生成尝试": context.get("attempt", ""),
                "任务ID": item["task_id"],
                "清晰度": item["resolution"],
                "画幅": item["ratio"],
                "时长(秒)": item["duration_seconds"],
                "原生音频": item["generate_audio"],
                "生成用量(tokens)": item['completion_tokens'],
                "估算费用(USD)": item["estimated_cost_usd"],
                "更新时间(北京时间)": item["updated_at"],
            }
            for item, context in zip(tasks, contexts)
        ]
        if usage['provider']=='ark_api':
            for row in rows:row.pop('估算费用(USD)',None)
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info(f"当前渠道暂无 Seedance 任务报告：{report_dir}")


def _credit_display(payload: dict[str, Any]) -> str:
    preferred = {
        "remaining_credit",
        "remaining_credits",
        "credit",
        "credits",
        "balance",
        "remaining_balance",
    }

    def search(value: Any) -> Any:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in preferred and isinstance(item, (int, float, str)):
                    return item
            for item in value.values():
                found = search(item)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = search(item)
                if found is not None:
                    return found
        return None

    found = search(payload)
    return str(found) if found is not None else "已成功读取（展开查看详情）"


def _friendly_dreamina_error(value: str) -> str:
    lowered = value.lower()
    if "登录" in value or "login" in lowered:
        return "尚未登录即梦 CLI。请展开“CLI 登录与能力”，运行登录命令后再查询。"
    return value


def _resolve_report_dir(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _setting(name: str, default: Any) -> Any:
    """Read a setting while tolerating Streamlit's stale hot-reload singleton."""

    return getattr(settings, name, default)
