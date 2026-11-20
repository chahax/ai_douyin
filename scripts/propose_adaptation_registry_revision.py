"""One bounded model proposal for reviewed cross-episode visual refinement."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.handoff import description_span
def main():
    p=argparse.ArgumentParser()
    for key in ("run","prior","handoff","source","request"):p.add_argument("--"+key,type=Path,required=True)
    p.add_argument("--span-start",type=int);p.add_argument("--span-end",type=int)
    a=p.parse_args();old=read(a.prior/"STATE.json");plan=read(a.prior/"PLAN.json")
    if old["pending"] is not None or old["status"]=="running":raise ValueError("prior_not_terminal")
    source=read(a.source);handoff=read(a.handoff);request=read(a.request)
    kind,key=request["kind"],request["id"];record=handoff["registry"][kind][key]
    a.run.mkdir(parents=True,exist_ok=False)
    for name,value in (("PLAN",plan),("SOURCE",source),("HANDOFF",handoff),("REQUEST_SCOPE",request)):
        freeze(a.run/(name+".json"),value)
    snap=a.run/"implementation";snap.mkdir()
    for file in [Path(__file__),Path("src/content_factory/novel_adaptation/handoff.py")]:
        (snap/file.name).write_bytes(file.read_bytes())
    state={"status":"prepared","calls_started":old["calls_started"],"reported_tokens":old["reported_tokens"],
           "baseline_calls":old["calls_started"],"baseline_tokens":old["reported_tokens"],"pending":None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        span=a.span_start is not None or a.span_end is not None
        if span:
            description_span(record,digest(record),a.span_start,a.span_end,"validate")
        schema=c.obj(**({"replacement":{"type":"string","minLength":1,"maxLength":12}} if span else {"description":c.TEXT}),source_ids=c.refs(c.catalog(source)))
        result=ledger.call("REGISTRY_DESCRIPTION","writer",
            "依据给定原文细化指定道具的外观描述。只纠正指出的不一致，保留其余可见特征，不改变身份、持有人或剧情。description只写正向可见内容，不写审查或禁止指令。若有editable_span，只返回该跨度的replacement替换文字，外部字符由程序保持，不返回整段描述。",
            {"complete_chapters":c.indexed_chapters(source),"current_record":record,"request":request,
             "editable_span":{"start":a.span_start,"end":a.span_end,"text":record["description"][a.span_start:a.span_end]} if span else None},schema)
        errors=c.schema_issues(result,schema,"registry")
        if errors:raise c.ContractError(errors)
        if span:
            result={"description":description_span(record,digest(record),a.span_start,a.span_end,result["replacement"]),
                    "source_ids":result["source_ids"]}
        proposals=[{"kind":kind,"id":key,"before_sha256":digest(record),**result}]
        freeze(a.run/"PROPOSALS.json",proposals);state["status"]="awaiting_primary_review"
    except Exception as exc:
        state["status"]="outcome_unknown" if state["pending"] is not None else "needs_attention"
        freeze(a.run/"ERROR.json",{"type":type(exc).__name__,"message":str(exc)})
    finally:ledger.save()
if __name__=="__main__":main()
