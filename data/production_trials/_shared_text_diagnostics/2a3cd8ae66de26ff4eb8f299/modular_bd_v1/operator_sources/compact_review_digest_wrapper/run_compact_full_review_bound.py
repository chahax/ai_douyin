"""Reference immutable review provenance by digest; do not change service payload."""
from __future__ import annotations
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_modular_bd_probe as base
from scripts import review_linear_script_probe_v6 as review
from src.content_factory.creative_review_v6 import validate_review_v6
def wire():
    ctx,w=review.wire()
    path=Path(__file__).resolve();h=base.file_hash(path)
    parent=base.ROOT/"LINEAR_REVIEW_BINDING_v6.json"
    value={"version":"compact_review_digest_wrapper/v1","source_path":str(path),"source_sha256":h,
           "parent_manifest_path":str(parent),"parent_manifest_sha256":base.file_hash(parent)}
    bind=base.ROOT/"COMPACT_REVIEW_WRAPPER_BINDING.json"
    snap=base.ROOT/"operator_sources"/"compact_review_digest_wrapper"/path.name
    if bind.exists():
        if base.read(bind)!=value:raise RuntimeError("compact review wrapper changed")
    else:
        snap.parent.mkdir(parents=True,exist_ok=True)
        with snap.open("xb") as f:f.write(path.read_bytes())
        base.write(bind,value,True)
    if base.file_hash(snap)!=h:raise RuntimeError("wrapper snapshot changed")
    w["operator_binding"]={"manifest_sha256":base.file_hash(parent),"wrapper_binding_sha256":base.file_hash(bind)}
    return ctx,w
def run():
    ctx,w=wire()
    def validate(value):
        validate_review_v6(value,ctx)
        return {"full_script_evidence_valid":True,"story_preserved":value["story_preserved"],
                "requires_assistant_evidence_verification":True,"semantic_approval":False,
                "review_context_sha256":base.digest(ctx),"validation_contract":"unchanged evidence_review_v6"}
    return base.dispatch("linear_script_review_v6",w,validate)
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1]=="preflight":
        c,w=wire();n=len(json.dumps(w,ensure_ascii=False))+w["parameters"]["max_completion_tokens"]+1024
        print(json.dumps({"reservation":n,"remaining":base.summary()["remaining_tokens"],
            "fits_original_budget":n<=base.summary()["remaining_tokens"],"service_payload_identical":w["messages"]==review.wire()[1]["messages"]},ensure_ascii=False))
    elif sys.argv[1]=="review":
        r=run()
        print(json.dumps({k:r.get(k) for k in ("ordinal","label","status","response_metadata","validation","failure","validation_error")},ensure_ascii=False,indent=2))
        print(json.dumps(base.summary(),ensure_ascii=False))
    else:raise SystemExit("preflight | review")
