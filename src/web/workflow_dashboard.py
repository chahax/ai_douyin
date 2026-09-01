"""Streamlit control plane for workflow implementation profiles."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.web.components.ui import (
    node_card_header,
    page_header,
    section_header,
    workflow_overview,
)
from src.workflow.contracts import ActivationMode, NodeImplementationSpec
from src.workflow.runtime import get_node_registry, get_selection_store
from src.workflow.selection_store import (
    WorkflowProfile,
    WorkflowSelectionError,
    WorkflowSelectionSnapshot,
)


STAGE_LABELS = {
    "llm": "大模型",
    "tts": "配音",
    "background": "背景生成",
    "video_pipeline": "成片主流程",
    "portrait_animation": "头像/口型驱动",
    "video_generation": "视频生成",
    "frame_interpolation": "视频插帧",
    "composition": "音视频合成",
    "publishing": "平台发布",
}

WORKFLOW_PHASES = (
    ("内容准备", ("llm", "tts", "background")),
    ("视觉生成", ("video_pipeline", "portrait_animation", "video_generation")),
    ("交付发布", ("frame_interpolation", "composition", "publishing")),
)

ACTIVATION_LABELS = {
    ActivationMode.HOT_SWITCH: "热切换（当前入口已接线）",
    ActivationMode.PROFILE_ONLY: "配置切换（独立入口待统一适配）",
    ActivationMode.EXTERNAL_CONFIG: "仅登记（当前仍由 .env 管理）",
    ActivationMode.RESTART_REQUIRED: "配置记录（现有实例仍需重启）",
}

ACTIVATION_SHORT = {
    ActivationMode.HOT_SWITCH: ("热切换", "hot"),
    ActivationMode.PROFILE_ONLY: ("待适配", "profile"),
    ActivationMode.EXTERNAL_CONFIG: (".env 管理", "external"),
    ActivationMode.RESTART_REQUIRED: ("需重启", "external"),
}


def page_workflow_nodes() -> None:
    page_header(
        "工作流节点",
        "像选择创作模型一样管理每个功能节点的实现，并通过配置方案控制新任务。",
        icon="⌘",
        eyebrow="WORKFLOW STUDIO",
    )

    registry = get_node_registry()
    store = get_selection_store()
    try:
        snapshot = store.load()
    except WorkflowSelectionError as exc:
        st.error(f"工作流配置不可用：{exc}")
        st.stop()

    active_col, revision_col, hot_col, pending_col = st.columns(4)
    active_col.metric("当前方案", snapshot.active_profile)
    revision_col.metric("配置版本", f"r{snapshot.revision}")
    hot_col.metric(
        "已接线节点",
        sum(
            registry.get(stage, implementation_id).activation_mode
            == ActivationMode.HOT_SWITCH
            for stage, implementation_id in snapshot.active.selections.items()
        ),
    )
    pending_col.metric(
        "待适配节点",
        sum(
            registry.get(stage, implementation_id).activation_mode
            == ActivationMode.PROFILE_ONLY
            for stage, implementation_id in snapshot.active.selections.items()
        ),
    )

    profile_names = list(snapshot.profiles)
    profile_col, note_col = st.columns([1, 2])
    with profile_col:
        selected_profile_name = st.selectbox(
            "配置方案",
            profile_names,
            index=profile_names.index(snapshot.active_profile),
            help="选择要预览或编辑的方案，不会立即改变生产配置。",
        )
    profile = snapshot.profiles[selected_profile_name]
    with note_col:
        st.text_input(
            "方案摘要",
            value=profile.description or "暂无说明",
            disabled=True,
            key=f"workflow_profile_summary_{selected_profile_name}",
        )

    implementation_labels = {
        (item.stage, item.implementation_id): item.label for item in registry.all()
    }
    workflow_overview(
        WORKFLOW_PHASES,
        profile.selections,
        STAGE_LABELS,
        implementation_labels,
    )

    editor_tab, catalog_tab, profiles_tab = st.tabs(
        ["工作流编排", "实现目录", "配置管理"]
    )
    with editor_tab:
        _render_editor(
            registry=registry,
            store=store,
            snapshot=snapshot,
            profile=profile,
        )
    with catalog_tab:
        _render_catalog(registry, snapshot)
    with profiles_tab:
        _render_profile_management(store, snapshot)


def _render_editor(*, registry, store, snapshot, profile: WorkflowProfile) -> None:
    section_header(
        "节点实现",
        "修改只作用于当前方案；点击“保存并设为当前”后，热切换节点的新任务立即生效。",
    )
    if profile.name != snapshot.active_profile:
        st.info(
            f"正在编辑非生产方案“{profile.name}”。当前运行方案仍是“{snapshot.active_profile}”。"
        )

    chosen: dict[str, str] = {}
    with st.form("workflow_node_profile_form"):
        description = st.text_input("方案说明", value=profile.description)
        for phase_name, stages in WORKFLOW_PHASES:
            st.markdown(f"##### {phase_name}")
            columns = st.columns(len(stages))
            for column, stage in zip(columns, stages):
                with column:
                    with st.container(border=True):
                        implementations = registry.implementations(stage)
                        implementation_ids = [
                            item.implementation_id for item in implementations
                        ]
                        current_id = profile.selections[stage]
                        widget_key = f"workflow_node_{profile.name}_{stage}"
                        displayed_id = st.session_state.get(widget_key, current_id)
                        displayed_spec = registry.get(stage, displayed_id)
                        badge, tone = ACTIVATION_SHORT[displayed_spec.activation_mode]
                        node_card_header(
                            STAGE_LABELS.get(stage, stage),
                            badge,
                            tone,
                        )
                        selected_id = st.selectbox(
                            f"{STAGE_LABELS.get(stage, stage)}实现",
                            implementation_ids,
                            index=implementation_ids.index(current_id),
                            format_func=lambda value, stage_name=stage: _implementation_label(
                                registry.get(stage_name, value)
                            ),
                            key=widget_key,
                            label_visibility="collapsed",
                        )
                        chosen[stage] = selected_id
                        selected = registry.get(stage, selected_id)
                        st.caption(selected.description)
                        st.caption(
                            f"接口：`{selected.inputs[0].artifact_type}` → "
                            f"`{selected.outputs[0].artifact_type}`"
                        )

        save_col, activate_col, hint_col = st.columns([1, 1, 1.35])
        save_only = save_col.form_submit_button("保存方案", width="stretch")
        save_and_activate = activate_col.form_submit_button(
            "保存并设为当前",
            type="primary",
            width="stretch",
        )
        hint_col.caption("网页保存采用 revision 校验与原子替换，不修改 .env。")

    if save_only or save_and_activate:
        try:
            updated = store.save_profile(
                profile.name,
                chosen,
                description=description,
                activate=save_and_activate,
                expected_revision=snapshot.revision,
            )
        except WorkflowSelectionError as exc:
            st.error(f"保存失败：{exc}。请刷新页面后重试。")
        else:
            message = f"方案已保存（revision {updated.revision}）"
            if save_and_activate:
                message += "，热切换节点的新任务将立即使用该选择"
            st.success(message)
            st.rerun()


def _render_catalog(registry, snapshot: WorkflowSelectionSnapshot) -> None:
    section_header(
        "实现目录",
        "查看每个功能节点的候选实现、接线状态和统一输入输出契约。",
    )
    all_implementations = registry.all()
    total_col, hot_col, profile_col, external_col = st.columns(4)
    total_col.metric("实现总数", len(all_implementations))
    hot_col.metric(
        "热切换",
        sum(item.activation_mode == ActivationMode.HOT_SWITCH for item in all_implementations),
    )
    profile_col.metric(
        "待适配",
        sum(item.activation_mode == ActivationMode.PROFILE_ONLY for item in all_implementations),
    )
    external_col.metric(
        "环境管理",
        sum(item.activation_mode == ActivationMode.EXTERNAL_CONFIG for item in all_implementations),
    )

    filter_col, mode_col = st.columns(2)
    stage_filter = filter_col.selectbox(
        "功能节点",
        ["全部", *registry.stages()],
        format_func=lambda value: STAGE_LABELS.get(value, value),
        key="workflow_catalog_stage",
    )
    mode_filter = mode_col.selectbox(
        "接线状态",
        ["全部", *[mode.value for mode in ActivationMode]],
        format_func=_activation_filter_label,
        key="workflow_catalog_mode",
    )

    rows: list[dict[str, Any]] = []
    active = snapshot.active.selections
    for implementation in all_implementations:
        if stage_filter != "全部" and implementation.stage != stage_filter:
            continue
        if mode_filter != "全部" and implementation.activation_mode.value != mode_filter:
            continue
        rows.append(
            {
                "功能节点": STAGE_LABELS.get(implementation.stage, implementation.stage),
                "实现": implementation.label,
                "当前": (
                    "当前使用"
                    if active[implementation.stage] == implementation.implementation_id
                    else ""
                ),
                "接线状态": ACTIVATION_LABELS[implementation.activation_mode],
                "输入 → 输出": (
                    f"{implementation.inputs[0].artifact_type} → "
                    f"{implementation.outputs[0].artifact_type}"
                ),
                "实现入口": implementation.entrypoint,
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_profile_management(store, snapshot: WorkflowSelectionSnapshot) -> None:
    section_header(
        "配置管理",
        "快速切换现有方案，或从稳定方案复制一份用于预览和实验。",
    )
    profile_rows = [
        {
            "方案": profile.name,
            "状态": "当前使用" if profile.name == snapshot.active_profile else "可切换",
            "说明": profile.description,
            "节点数": len(profile.selections),
        }
        for profile in snapshot.profiles.values()
    ]
    st.dataframe(profile_rows, width="stretch", hide_index=True)

    activate_col, action_col = st.columns([2, 1])
    activate_target = activate_col.selectbox(
        "切换当前方案",
        list(snapshot.profiles),
        index=list(snapshot.profiles).index(snapshot.active_profile),
        key="workflow_activate_target",
    )
    if action_col.button(
        "设为当前方案",
        type="primary",
        width="stretch",
        disabled=activate_target == snapshot.active_profile,
    ):
        try:
            store.activate(activate_target, expected_revision=snapshot.revision)
        except WorkflowSelectionError as exc:
            st.error(f"切换失败：{exc}")
        else:
            st.success(f"当前方案已切换为：{activate_target}")
            st.rerun()

    with st.expander("复制为新方案"):
        with st.form("clone_workflow_profile_form"):
            clone_source = st.selectbox("复制来源", list(snapshot.profiles))
            clone_name = st.text_input("新方案名称", placeholder="preview 或 新方案")
            clone_description = st.text_input("新方案说明")
            clone_submitted = st.form_submit_button(
                "创建方案", type="primary", width="stretch"
            )
        if clone_submitted:
            try:
                store.clone_profile(
                    clone_source,
                    clone_name.strip(),
                    description=clone_description,
                    expected_revision=snapshot.revision,
                )
            except WorkflowSelectionError as exc:
                st.error(f"创建失败：{exc}")
            else:
                st.success(f"已创建方案：{clone_name.strip()}")
                st.rerun()


def _implementation_label(implementation: NodeImplementationSpec) -> str:
    status, _tone = ACTIVATION_SHORT[implementation.activation_mode]
    return f"{implementation.label} · {status}"


def _activation_filter_label(value: str) -> str:
    if value == "全部":
        return value
    mode = ActivationMode(value)
    return ACTIVATION_LABELS[mode]


if __name__ == "__main__":
    from src.web.components.ui import inject_app_theme

    st.set_page_config(page_title="工作流节点 · UI Preview", layout="wide")
    inject_app_theme()
    st.navigation(
        [st.Page(page_workflow_nodes, title="工作流节点", icon="🔀")],
        position="sidebar",
    ).run()
