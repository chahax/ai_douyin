
"""Generate v3 offline proposals against unchanged legal sources; no model calls."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory.creative_segment_execution import read,sha
from src.content_factory.creative_stage_contracts import persist
from src.content_factory.creative_video_current_step_contract_v3 import build_contract,render_offline_prompt,require_production_ready
from scripts.run_legal_opening_seedance_v1 import make_plan
root=ROOT/"data/video_generation/legal_trend_20261008/remaining_batch_v1"
out=root/"human_feedback_20261009";out.mkdir(exist_ok=True)
make_plan() # Recompute complete frozen handoff without changing it.
manifest=read(root/"BATCH_MANIFEST.json")
contracts=[];lines=["# 当前段请求隔离v3（离线候选，尚不能生产调用）","",
 "冻结正文、导演、表演和25段原请求均不修改。整镜构图/未来动作和完整重音说明只保存在来源字段中，不进入当前段提示词。",
 "对白由唯一对白字段输出；无对白动作段明确禁止发声念字；只有当前动作进入可执行指令。保留全部源窗口和原句片段。",
 "原完整表演里的活动期间重音/非言语指导尚未由生成模型重写为隔离字段，暂缓应用并列为生产阻断条件；不能把本候选视为完整导演或可制作返修交接。",""]
for d in manifest["segments"]:
 c=build_contract(d);prompt=render_offline_prompt(c)
 contracts.append(c)
 lines.extend([f'## {d["segment_id"]} / {d["duration_seconds"]}秒',"",prompt,""])
 try:require_production_ready(c)
 except ValueError:pass
 else:raise ValueError("prototype became production-ready without full revision")
persist(out/"V3_OFFLINE_CONTRACTS.json",{"schema":"legal_v3_offline_contract_candidates/v1",
 "source_manifest_sha256":sha(root/"BATCH_MANIFEST.json"),"contracts":contracts,
 "new_model_calls":0,"production_ready":False})
(out/"V3_OFFLINE_PROMPTS.md").write_text("\n".join(lines),encoding="utf-8")
print(json.dumps({"contracts":len(contracts),"production_ready":False,"new_paid_calls":0,
 "file":str(out/"V3_OFFLINE_PROMPTS.md")},ensure_ascii=False))

