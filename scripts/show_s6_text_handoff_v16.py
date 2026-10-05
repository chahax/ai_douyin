"""Show/save the reviewed S6 text handoff; contains no provider dispatch."""
from pathlib import Path
import sys,types,json
project=Path(__file__).resolve().parents[1];sys.path.insert(0,str(project))
package=types.ModuleType('scripts');package.__path__=[str(project/'scripts')];sys.modules['scripts']=package
from scripts import run_creative_handoff_delivery_v16 as delivery
from scripts import render_creative_text_handoff_v1 as renderer
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    proof=delivery.control.read(delivery.ROOT/'ASSISTANT_SOURCE_EVIDENCE.json')
    handoff=delivery.finalize(proof)
    print(json.dumps({key:handoff[key] for key in ('status','adopted_review_ordinal','shots','compiled_duration_seconds','text_production_handoff_complete','creative_quality_passed','media_calls')},ensure_ascii=False,indent=2))
    print(json.dumps(renderer.render(delivery.ROOT/'DELIVERABLE_s6_d6'),ensure_ascii=False,indent=2))
