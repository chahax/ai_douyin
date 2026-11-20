"""One source-backed cooking design proposal; never auto-accept or alter prose."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.cooking_assets import validate_proposal


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--prior',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    a=p.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('prepared','running'):raise ValueError('prior_not_terminal')
    if old['calls_started']>=plan['max_calls']:raise ValueError('engineering_window_exhausted')
    source=read(a.prior/'SOURCE.json');design=read(a.prior/'DESIGN_COMPILED.json')
    a.run.mkdir(parents=True,exist_ok=False)
    for name,obj in [('SOURCE',source),('BEFORE_DESIGN',design),('PLAN',plan)]:freeze(a.run/(name+'.json'),obj)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'state_sha256':digest(old),'calls_carried':old['calls_started'],'tokens_carried':old['reported_tokens'],'ceiling':plan['max_calls']})
    snap=a.run/'implementation';snap.mkdir()
    for f in [Path(__file__),Path('src/content_factory/serial_story_transport_v6.py')]+list(Path('src/content_factory/novel_adaptation').glob('*.py')):(snap/f.name).write_bytes(f.read_bytes())
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    schema=c.obj(verdict=c.choices(['supported','uncertain']),
        new_props=c.array(c.obj(id=c.TEXT,kind=c.TEXT,display_name=c.TEXT,description=c.TEXT,owner=c.choices([x['id'] for x in design['places']]),
            evidence_type=c.choices(['source_explicit','visual_design']),source_ids=c.refs(c.catalog(source)))),
        bindings=c.array(c.obj(recipe=c.choices([r['id'] for r in design['recipes']]),input_prop=c.choices([r['id'] for r in design['props']]),vessel=c.TEXT,reason=c.TEXT,source_ids=c.refs(c.catalog(source)))),
        existing_display_names=c.array(c.obj(id=c.choices([r['id'] for r in design['props']]),display_name=c.TEXT)),
        action_requirements=c.array(c.obj(action=c.TEXT,target=c.TEXT,instrument=c.TEXT,source_ids=c.refs(c.catalog(source)),evidence_type=c.choices(['source_explicit','visual_design']))))
    try:
        value=ledger.call('COOKING_ASSET_PROPOSAL','writer','''只设计第二章烹饪所需的最小资产补充与加工容器绑定，不生成或修改剧本。
完整前三章作上下文，第二章是当前目标。已有old-aluminum-pot描述用于煮米饭，不能偷偷改为另一口炒菜锅；stew-pot是装好成品的大碗，不是生肉下锅的锅具。必要时新增独立炒锅和实际使用的工具，保持贫困家庭环境。
区分原文明确物件和影视设计补足。新资产只写物理外观，不预写完成状态，不新增人物、经历或对话。
bindings为recipe.input_containers：只有原料明确要先进入对应锅具，才指定。未指定则程序要求transform前原料在容器外。原料放入容器用pack，成菜后transform消耗原料并移除其容器关联，锅保留。不要将装成品的碗当生原料加工容器。
为点火、切肉、肉片下锅、搅拌所需实际动作列action_requirements；instrument无工具时填空字符串。工具必须可辨识，使用时由人持有。existing_display_names仅为当前generic厨具/食材补简短准确名称，不改资产身份或描述。
只返回必要补充；无法确定的关系verdict=uncertain。完整原文事实优先于旧配方描述。''',
            {'complete_chapters':c.indexed_chapters(source),'existing_props':design['props'],'places':design['places'],'recipes':design['recipes']},schema)
        issues=c.schema_issues(value,schema,'cooking_assets')
        if issues:raise c.ContractError(issues)
        freeze(a.run/'PROPOSAL.json',value)
        validate_proposal(value,design)
        state['status']='proposal_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()


if __name__=='__main__':main()
