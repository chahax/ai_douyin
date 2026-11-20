
"""Publish actual same-film receipts into the mutable progress view; preserve a checkpoint."""
import json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory.creative_segment_execution import read,sha
from src.content_factory.creative_stage_contracts import persist
film=ROOT/"data/video_generation/legal_trend_20261008"
batch=film/"remaining_batch_v1"
path=ROOT/"data/task_progress_monitor/creative_progress_state.json"
backup=batch/"PROGRESS_VIEW_BEFORE_BATCH.json"
if not backup.exists():backup.write_bytes(path.read_bytes())
v=read(path)
candidates=[]
for p in sorted(film.glob("**/receipt.json")):
 r=read(p)
 if r.get("logical_task_id")=="legal_trend_text_trial_20261008_adopted_r8":
  candidates.append({"receipt":str(p),**{k:r.get(k) for k in ("segment_id","task_id","technical_status","content_status","video_path")}})
calls=sum(bool(r["task_id"]) for r in candidates)
assembly=batch/"ASSEMBLY_RECEIPT.json"
full_review=read(assembly) if assembly.exists() else {}
full_status=full_review.get("content_status")
human_rejected=full_status=="rejected"
current_stage=("legal_full_film_user_feedback_requires_revision" if human_rejected else
               "legal_full_video_awaiting_human_review" if assembly.exists() else
               "legal_video_remaining_batch_generating")
v.update(updated_at_utc=datetime.now(timezone.utc).isoformat(),
 current_stage=current_stage,
 stage=current_stage,
 current_goal="按用户反馈修复法律片对白重复、工牌/场景连续性与字幕请求" if human_rejected else "已采用法律片完整生成：服务原始尾帧连续生成剩余段→完整审片文件→用户统一人工审核",
 latest_user_alignment=v.get("latest_user_alignment") if human_rejected else "本次改为原始尾帧连续生成，全部完成后统一人工审核",
 latest_user_direction_confirmation="本次改为原始尾帧连续生成，全部完成后统一人工审核",
 next_step="按已登记人工反馈准备完整返修；旧批授权不自动重领媒体调用" if human_rejected else "用户统一审核完整审片文件" if assembly.exists() else "原ID续查；保存视频及服务原始尾帧后生成下一段；21新增段完成后技术合成",
 current_iteration_media_calls=calls,media_calls=calls,media_calls_scope="current adopted legal film only; historical other films retained",
 effective_calls_started=311,effective_reported_tokens=5335773,actual_latest_call=311,
 aggregate_text_token_limit=None,quota_monitor_cancelled=True,
 current_content="公司要求离开→催签个人原因→小林核对口头与纸面并暂不签→周姐带走纸笔承诺下班前答复；未兑现留白",
 current_batch_authorization=str(batch/"BATCH_USER_AUTHORIZATION.json"),
 current_batch_progress=str(batch/"PROGRESS.json"),current_batch_prompts=str(batch/"ALL_PROMPTS_v2.md"),
 current_film_candidates=candidates,creative_quality_passed=False,
 current_deliverable=str(batch/"LEGAL_FULL_REVIEW_v1.mp4") if assembly.exists() else v.get("current_deliverable"))
v["latest_script"]["status"]="human_adopted_complete_script"
v["unresolved"]=[
 "用户已反馈重复对白、重复戴工牌和场景不一致；整片rejected，等待完整返修" if human_rejected else "视频表演、普通话声音口型、道具连续性与情绪效果待用户统一人工审核",
 "LG01整镜说明含下一步对白，原请求保留；后续提示词已收紧，LG01是否受影响待用户审片",
 "旧70结果未知、70/160用量未知与93117预留保留",
 "原研究SQLite锁及旧研究音画门禁问题保留，未据此宣称研究分析完成"]
v["content_alignment_pending"]={"working_direction":"confirmed_legal_departure_case",
 "script_adopted":True,"full_film_quality_approval":None,"pending_question":None}
v["latest_legal_video_batch"]={"authorization":str(batch/"BATCH_USER_AUTHORIZATION.json"),
 "progress":str(batch/"PROGRESS.json"),"planned_new_submissions":21,"actual_film_submissions":calls,
 "saved_film_candidates":sum(r["technical_status"]=="succeeded" for r in candidates),
 "content_status":full_status or "awaiting_human_review","automatic_retry":False,
 "human_approval_created":full_status=="approved","full_review_video":str(batch/"LEGAL_FULL_REVIEW_v1.mp4") if assembly.exists() else None}
persist(path,v)
print(json.dumps(v["latest_legal_video_batch"],ensure_ascii=False))

