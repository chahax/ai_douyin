"""Explicit local preparation and text-only launch for a novel opportunity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import streamlit as st

from scripts.run_account_novel_creation_v1 import (
    prepare_from_repositories, validate_current_context,
)
from src.content_factory.account_novel_selection_v1 import discover_books, select_target_novel
from src.content_factory.account_novel_creation_v1 import (
    inspect_account_novel_run, preview_account_novel_run,
)
from src.web.components.auth import get_current_role, has_permission

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data/account_novel_creation/v1"
BOOKS = ROOT / "data/fanqie_promotion/books"

STATUS_LABELS = {
    "selected": "已选定目标小说", "needs_materials": "等待补齐小说材料",
    "no_matching_book": "暂无匹配小说", "unprepared": "尚未准备",
    "prepared": "准备完成，可启动创作", "machine_text_complete": "完整文本与机器复审已完成",
    "awaiting_text_review": "完整文本已保存", "needs_text_attention": "原文取材范围需要处理",
    "needs_attention": "任务已停止，需要处理记录中的问题",
    "needs_revision": "剧本仍有待修问题", "incomplete_artifacts": "产物缺失或文件校验未通过",
}


def opportunity_run_dir(profile, opportunity, *, root=None) -> Path:
    identity = f"{profile.account_uuid}\n{opportunity.opportunity_id}"
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return Path(root or RUNS).resolve() / key


def launch_account_novel_creation(run_dir: Path) -> dict:
    """Validate live account records before spawning the original bound task."""
    if not has_permission(get_current_role(), "editor"):
        raise PermissionError("当前角色只有查看权限，不能启动模型创作")
    run_dir = Path(run_dir).resolve()
    if (run_dir / ".account_novel_execution.lock").exists():
        raise RuntimeError("原任务正在执行或遗留在途锁，请刷新原结果，不重复启动")
    if inspect_account_novel_run(run_dir).get("status") in {"machine_text_complete", "awaiting_text_review"}:
        raise RuntimeError("完整文本已经生成，请查看原产物")
    validate_current_context(run_dir)
    preview_account_novel_run(run_dir)
    log_path = run_dir / "execution.log"
    argv = [sys.executable, str(ROOT / "scripts/run_account_novel_creation_v1.py"),
            "execute", "--run-dir", str(run_dir)]
    with log_path.open("ab") as handle:
        process = subprocess.Popen(
            argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=handle, stderr=handle,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    receipt = {"pid": process.pid, "run_dir": str(run_dir), "log_path": str(log_path),
               "command": argv, "automatic_media_submit": False}
    (run_dir / "LAST_LAUNCH.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def _show_outputs(run_dir: Path, report: dict) -> None:
    status = report.get("status", "未知")
    st.write("任务状态：", STATUS_LABELS.get(status, status))
    issue = report.get("error") or report.get("artifact_error") or (report.get("creative_state") or {}).get("last_error")
    if issue:
        st.warning(str(issue))
    with st.expander("实际运行记录与产物路径"):
        st.json(report)
    creative = run_dir / "creative"
    for filename, title in (("SCREENPLAY.md", "完整剧本"), ("STORYBOARD.json", "导演分镜")):
        path = creative / filename
        if path.is_file():
            with st.expander(title, expanded=filename.endswith(".md")):
                st.code(str(path.resolve()), language=None)
                content = path.read_text(encoding="utf-8")
                if filename.endswith(".md"):
                    st.markdown(content)
                else:
                    st.json(json.loads(content))
    log = run_dir / "execution.log"
    if log.is_file():
        with st.expander("后台执行日志（末尾）"):
            st.code(log.read_text(encoding="utf-8", errors="replace")[-16000:])


def render_account_novel_creation(profile, opportunity, repository, account_repository):
    """Called after selecting an existing opportunity in the account dashboard."""
    if profile.domain_strategy_id != "novel_promotion":
        return
    run_dir = opportunity_run_dir(profile, opportunity)
    prefix = "account_novel_" + run_dir.name
    editor = has_permission(get_current_role(), "editor")
    with st.expander("目标小说完整创作", expanded=True):
        st.caption("选题用于选书与表达方向，人物和剧情以绑定小说原文为准。准备、选书和预览不调用模型；启动仅推进文本创作。")
        st.code(str(run_dir), language=None)
        books_root = Path(st.text_input("本地小说素材目录", value=str(BOOKS), key=prefix + "books"))
        try:
            candidates = discover_books(books_root)
            choices = [None] + list(dict.fromkeys(str(row.get("book_id", "")) for row in candidates if row.get("book_id")))
            selected = st.selectbox(
                "目标书籍", choices,
                format_func=lambda value: "按账号与机会自动匹配" if value is None else next(
                    f"{row.get('book_name', value)} · {value}" for row in candidates if str(row.get("book_id")) == value),
                key=prefix + "book",
            )
            selection = select_target_novel(profile, opportunity, candidates, target_book_id=selected)
            st.write("选书状态：", STATUS_LABELS.get(selection["status"], selection["status"]))
            with st.expander("候选匹配与材料缺口"):
                st.json(selection.get("rankings", []))
            if selection["status"] != "selected":
                st.info("请补齐匹配的小说正文和既有文本使用依据，可在“候选匹配与材料缺口”查看具体原因。")
            if st.button("准备完整创作（不调用模型）", key=prefix + "prepare", disabled=not editor):
                result = prepare_from_repositories(
                    account_key=profile.account_key, opportunity_id=opportunity.opportunity_id,
                    run_dir=run_dir, account_db=account_repository.db_path,
                    trend_db=repository.db_path, books_root=books_root,
                    target_book_id=selected,
                )
                if result.get("status") == "prepared":
                    st.success("准备完成，可启动完整创作。")
                else:
                    status = result.get("status", "未知")
                    st.info("准备结果已保存：" + STATUS_LABELS.get(status, status))
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            st.error(str(exc))
        if (run_dir / "BINDING.json").is_file():
            try:
                preview = preview_account_novel_run(run_dir)
                with st.expander("冻结输入与完整创作请求预览"):
                    st.json(preview)
                terminal = preview.get("status") in {"machine_text_complete", "awaiting_text_review"}
                inflight = (run_dir / ".account_novel_execution.lock").exists()
                if st.button("启动／继续原任务文本创作", key=prefix + "execute", disabled=not editor or terminal or inflight):
                    launch_account_novel_creation(run_dir)
                    st.success("后台创作已启动，可刷新查看进度和产物。")
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                st.error(str(exc))
        if run_dir.is_dir():
            st.button("刷新原任务状态与产物", key=prefix + "refresh")
            try:
                _show_outputs(run_dir, inspect_account_novel_run(run_dir))
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                st.error(str(exc))
        if not editor:
            st.caption("当前角色可查看选书与产物；准备和模型启动需要编辑权限。")
