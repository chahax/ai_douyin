"""Actual local progress only; no provider, quota or media action."""
from datetime import datetime, timezone
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def main():
    path = PROJECT / "data/task_progress_monitor/creative_progress_state.json"
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    stamp = datetime.now(timezone.utc).isoformat()
    doc.update(updated_at_utc=stamp, last_progress_review_at=stamp,
        status="goal_setup_separation_development_after_known_terminal",
        current_stage="goal_setup_separation_offline_review",
        stage="goal_setup_separation_offline_review",
        actual_latest_call=540, latest_call=540, latest_model_call_ordinal=540,
        latest_effective_reported_tokens=10308368, effective_reported_tokens=10308368,
        effective_calls_started=540, effective_calls=540,
        current_new_model_calls=2, current_new_media_calls=0,
        generation_running=False, current_generation_running=False,
        current_generation_process_running=False, pending_user_question=False,
        current_task_completed=False, quota_monitor_cancelled=True,
        next_step="完成独立整片静态规划→原生开场状态→正文接线、谱系SHA去重与控制分支审查后，按已有文本授权生产新完整剧本和同源全文审查。",
        latest_story_direction="尚无新采用正文。旧候选是夜班女工追问撤排班与结算签字；具体新完整规划和结尾必须由模型原生新版本提交并审查，不把旧失败计划当正文。",
        latest_actual_report=str(PROJECT / "docs/CREATIVE_GOAL_CONTEXT_PRODUCTION_REPAIR_REVIEW_20261013.md"),
        latest_plan=str(PROJECT / "docs/CREATIVE_PLAN_SETUP_SEPARATION_PLAN_20261013.md"))
    doc["goal_context_production"].update(root=str(PROJECT / "data/production_trials/goal_context_text_production_20261013/round_05"),
        latest_known_ordinal=540, latest_known_status="contract_rejected",
        latest_known_reason="GOAL_SCHEMA_INVALID and absent prop already held",
        known_reported_tokens=10308368, known_calls_with_usage=538,
        actual_new_model_calls=2, actual_new_media_calls=0,
        terminal_status="halt_goal_content_capacity_exhausted", text_ready_for_director=False,
        cumulative_goal_candidates_used=8)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
