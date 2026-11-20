"""Read an exported account-bound batch and prepare one legal core collection plan."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src.operations_accounts.models import AccountProfile
from src.trend_intelligence.collection.legal_core import build_legal_core_plan
from scripts.prepare_trend_creative_workflow import read, file_sha, write_bundle


def main(argv=None):
    parser=argparse.ArgumentParser(description="Prepare a single-core legal tag graph and bounded search request; offline only")
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--core-tag",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--now",default=None)
    parser.add_argument("--max-related-tags",type=int,default=4)
    parser.add_argument("--max-pages",type=int,default=30)
    args=parser.parse_args(argv)
    before=file_sha(args.source);source=read(args.source)
    profile=AccountProfile(**source["account_profile"])
    for key in ("account_uuid","profile_version","domain_strategy_id","strategy_version"):
        if source["collection_run"].get(key)!=getattr(profile,key):
            raise ValueError("source batch does not belong to the legal account strategy")
    if any(r.get("run_id")!=source["collection_run"]["run_id"] for r in source["observations"]):
        raise ValueError("source contains another batch")
    plan=build_legal_core_plan(profile,source["observations"],args.core_tag,
        now=args.now or datetime.now(timezone.utc).isoformat(),max_related_tags=args.max_related_tags,max_pages=args.max_pages)
    if file_sha(args.source)!=before:raise ValueError("source changed during preparation")
    lines=["# 法律单核心标签采集计划","",f"核心：{plan['core_tag']}",
        "关联："+"、".join(plan["related_tags"]),f"预计搜索页：{plan['estimated_pages']}，来源旧批次去重视频：{plan['source_unique_videos']}",
        "旧样本提供关联线索；本次计划尚未执行，不代表今天热点。","","## 选择依据",""]
    for tag in plan["related_tags"]:
        c=next(c for c in plan["candidates"] if c["tag"]==tag)
        lines.append(f"- {tag}：{c['support_unique_videos']}个去重视频、{len(c['author_display_names'])}个可见作者名，关系分{c['relation_score']}。")
    lines += ["","## 热度与后续条件", "", *["- "+s for s in plan["creative_handoff_blockers"]],
        "","关联是直接共现与法律检索词表的启发式结果，不证明语义正确或法律结论。",
        "关联搜索作为新批次采集；不把旧记录合并到新批次凑门槛。",""]
    write_bundle(args.output,{"LEGAL_CORE_PLAN.json":plan,"CORE_TAG_REVIEW.md":"\n".join(lines),
        "EVIDENCE.json":{"source_path":str(args.source.resolve()),"source_file_sha256":before,
            "model_calls":0,"collection_calls":0,"media_calls":0,"current_hot_topic_verified":False}})
    print(json.dumps({"output":str(args.output.resolve()),"core_tag":plan["core_tag"],
        "related_tags":plan["related_tags"],"estimated_pages":plan["estimated_pages"],"submitted":False},ensure_ascii=False))
    return 0


if __name__=="__main__":raise SystemExit(main())
