"""Versioned candidate prompt modules; production default is unchanged."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "config/prompts/creative_writer_modules_v1.json"

def build_writer_prompt(module_names=(), *, pack_path=PACK):
    pack=json.loads(Path(pack_path).read_text(encoding="utf-8-sig"))
    if pack.get("schema")!="creative_writer_modules/v1":
        raise ValueError("提示词模块版本无效")
    names=list(dict.fromkeys([*pack["common"],*module_names]))
    unknown=set(names)-set(pack["modules"])
    if unknown:raise ValueError("未知提示词模块: "+str(sorted(unknown)))
    return "\n\n".join("【"+name+"】\n"+pack["modules"][name] for name in names)
