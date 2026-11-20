
"""Deliver saved technical artifacts, actual prompts and audit; no content review."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory.creative_segment_execution import read,sha,media_reservation_root
from src.content_factory.creative_stage_contracts import persist,digest
from src.content_factory.media_review_policy import validate_source_bindings
from scripts.run_legal_seedance_batch_v1 import OUT,BUNDLE,LOGICAL_TASK
assembly=read(OUT/"ASSEMBLY_RECEIPT.json")
if sha(assembly["video_path"])!=assembly["video_sha256"] or assembly["content_status"]!="awaiting_human_review":
 raise ValueError("full review file changed or wrongly approved")
records=[]
lines=["# 本片实际提交提示词与参数","",
       "按实际请求回执列出，含原四段及本次21新增段。参考图片字节用实际输入SHA256与MIME表示。LG01保留已提交的v1整镜说明；后续段使用收紧后的v2。",""]
for c in assembly["candidates"]:
 if sha(c["receipt"])!=c["receipt_sha256"]:raise ValueError("assembled candidate receipt changed")
 r=read(c["receipt"]);validate_source_bindings(r)
 provider_final=r.get("final") or r.get("latest_response") or {}
 if provider_final.get("id")!=r["task_id"] or provider_final.get("status")!="succeeded":
  raise ValueError("returned service task ID/status differs")
 if r["segment_id"].startswith("LG") and r["content_status"]!="awaiting_human_review":
  raise ValueError("batch output approval fabricated")
 request=r["request"];p=r["plan_snapshot"]
 records.append({"segment_id":r["segment_id"],"shot_id":r.get("shot_id"),
  "source_refs":p["source_refs"],"task_id":r["task_id"],"request":request,"request_sha256":r["request_sha256"],
  "receipt":c["receipt"],"receipt_sha256":c["receipt_sha256"]})
 text="\n".join(x["text"] for x in request["content"] if x["type"]=="text")
 lines.extend([f'## {r["segment_id"]} / {r.get("shot_id")} / {request["duration"]}秒',"",
  f'模型：{request["model"]}；分辨率：{request["resolution"]}；任务ID：{r["task_id"]}',"",
  f'来源：{", ".join(p["source_refs"])}',"",text,""])
if len({r["task_id"] for r in records})!=25 or len(records)!=25:
 raise ValueError("unexpected task count or duplicate generation")
persist(OUT/"ACTUAL_REQUESTS.json",{"schema":"legal_video_actual_request_audit/v1","requests":records,
 "original_payload_images_redacted_to_hash_and_mime":True,"automatic_retry":False})
(OUT/"ACTUAL_PROMPTS.md").write_text("\n".join(lines),encoding="utf-8")
ledger_path=media_reservation_root({"logical_task_id":LOGICAL_TASK})/"budget.json"
budget=read(ledger_path)
if budget["failure_limit"]!=10 or budget["budget_reset_supported"] is not False:
 raise ValueError("same-script budget changed")
persist(OUT/"MEDIA_BUDGET_SNAPSHOT.json",{"source":str(ledger_path),"source_sha256":sha(ledger_path),"value":budget})
all_receipts=[read(c["receipt"]) for c in assembly["candidates"]]
usage=sum((r.get("final") or r.get("latest_response") or {}).get("usage",{}).get("total_tokens",0) for r in all_receipts)
new_usage=sum((r.get("final") or r.get("latest_response") or {}).get("usage",{}).get("total_tokens",0) for r in all_receipts[4:])
source_manifest=read(BUNDLE/"MANIFEST.json")
for name,h in source_manifest["files"].items():
 if sha(BUNDLE/name)!=h:raise ValueError("frozen full handoff changed")
historical=all_receipts[0]["plan_snapshot"]["historical_campaign"]
if sha(historical["path"])!=historical["sha256_before"]:
 raise ValueError("historical campaign changed")
evidence={"schema":"legal_full_review_delivery/v1","logical_task_id":LOGICAL_TASK,
 "video_path":assembly["video_path"],"video_sha256":assembly["video_sha256"],
 "video_bytes":assembly["video_bytes"],"seconds":float(assembly["metadata"]["format"]["duration"]),
 "total_saved_segments":25,"new_submissions_this_batch":21,"new_text_model_calls":0,
 "video_service_reported_tokens_all_film":usage,"video_service_reported_tokens_new_batch":new_usage,
 "text_ledger_separate_and_unchanged":True,"frozen_handoff_unchanged":True,"historical_campaign_unchanged":True,
 "budget_reset":False,"automatic_retry":False,"technical_status":"succeeded","content_status":"awaiting_human_review",
 "content_approval_created":False,"visual_audio_content_checked":False,
 "source_request_coverage":"all 23 source steps/16 original speeches; long speeches split at original punctuation",
 "unresolved":["actual delivery/acting/language/lip sync/prop continuity require user review",
  "LG01 original whole-shot context contained next dialogue; preserved candidate, no regeneration",
  "speech chunk timings projected by exact-character proportions; natural cross-request delivery unverified"],
 "actual_prompts":str(OUT/"ACTUAL_PROMPTS.md"),"actual_requests":str(OUT/"ACTUAL_REQUESTS.json"),
 "code_sha256":{str(p):sha(p) for p in [ROOT/"scripts/run_legal_seedance_batch_v1.py",
  ROOT/"src/content_factory/creative_legal_video_batch_v1.py",ROOT/"src/content_factory/creative_segment_execution.py"]}}
persist(OUT/"DELIVERY_EVIDENCE.json",evidence)
duration=evidence["seconds"]
notes=[
 "# 《那张纸今天先留在这儿》完整审片交付","",
 f'实际完整审片文件：{duration:.3f}秒，25个服务片段；本次新增21次Seedance视频请求，文本模型新增0次。',
 "沿用Seedance Mini、480p、9:16及生成服务同期声音。复用原四段，剩余19源步骤、197秒源窗口全部纳入21新增请求。","",
 "接口均返回成功，视频及服务原始尾帧完整保存并核对SHA256。合成按故事顺序直接拼接原始视频与音轨，未裁掉对白或动作；技术检查仅读取容器/流元数据，不抽帧、不听看、不ASR、不使用音画审核模型。",
 "所有本次新段、原SH03B和完整审片文件均为 awaiting_human_review。前三段保留用户此前逐段批准记录；本次批授权允许提前承接服务原始尾帧，不等于其内容通过。","",
 "实际观看文件：[LEGAL_FULL_REVIEW_v1.mp4](LEGAL_FULL_REVIEW_v1.mp4)；实际输入全文：[ACTUAL_PROMPTS.md](ACTUAL_PROMPTS.md)；实际请求与图片输入哈希：[ACTUAL_REQUESTS.json](ACTUAL_REQUESTS.json)。","",
 "剧情不改：公司要求离开，纸面却是个人原因；小林核对矛盾、受催签压力后坚持暂不签；周姐带走纸笔并承诺回复，回复尚未发生，小林不追出去。","",
 "尚待人工审核：语言、声音口型、实际表演窗口、跨段连续性、情绪效果与纸面字样。四句长对白在源标点拆分，发话时长按字符比例投影，未删对白或反应窗口，但自然接话未验证。LG01原请求整镜说明混入下一步催签对白，未重派、未修改原请求；后续v2已收紧，LG01实际是否受影响请审片确认。","",
 f'视频服务reported tokens：本次{new_usage}，本片累计{usage}，与MiniMax/DeepSeek文本账本分开。原同稿失败上限10未变，预算未重置；当前账本确认失败{budget["confirmed_failed_current_script"]}。这些数值不代表内容质量。',
 "首轮34项相关离线检查通过，提示词范围修正后14项通过；实际合成已完成格式、源回执、顺序、哈希及总时长核对。冻结交接、原四段记录和旧任务账本保留。发布未执行。",""]
(OUT/"DELIVERY_REPORT.md").write_text("\n".join(notes),encoding="utf-8")
entry = "\n\n### 2026-10-08 法律片完整审片文件（本次整批审核例外）\n\n"
entry += f"用户明确授权服务原始尾帧连续生成、全部完成后统一人工审核。原四段复用，新增21次Seedance Mini 480p视频请求，25段已完整保存并合成{duration:.3f}秒的[完整审片文件](../data/video_generation/legal_trend_20261008/remaining_batch_v1/LEGAL_FULL_REVIEW_v1.mp4)。"
entry += "全部新段和整片为awaiting_human_review，未抽帧、听看、ASR或模型音画审核，未发布、未自动重生成。"
entry += "原稿、导演交接、旧账本和默认逐段批准规则保留；本次例外不授予其他片批量续段。"
entry += "源对白/窗口完整进入实际请求，但真实表演与长句接话未验证；LG01原整镜说明夹带下一步对白的候选保留供用户审核，后续提示词范围已修正。"
entry += "实际内容与剩余问题见[交付记录](../data/video_generation/legal_trend_20261008/remaining_batch_v1/DELIVERY_REPORT.md)及[实际提示词](../data/video_generation/legal_trend_20261008/remaining_batch_v1/ACTUAL_PROMPTS.md)。\n"
for name in ("CREATIVE_WORKFLOW_IMPLEMENTATION.md","CREATIVE_STAGE_DEBUGGING.md"):
 path=ROOT/"docs"/name
 old=path.read_text(encoding="utf-8")
 if "法律片完整审片文件（本次整批审核例外）" not in old:
  path.write_text(old+entry,encoding="utf-8")
print(json.dumps(evidence,ensure_ascii=False))

