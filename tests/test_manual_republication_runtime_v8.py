"""One exact receiver chain, private stores, no platform/browser."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
from src.operations_accounts import manual_republication_runtime_v8 as bridge


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return bridge.reference(path)


V7_FLOW='''import json
from pathlib import Path
from src.operations_accounts import manual_republication_runtime_v7 as r
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 a=r.reference(outdir.parent/'ACTION_CLAIM.json');p=r._read(r._read(a)['plan']);m=r._read(config['metadata']);f=p['prior']['file_selection_claim']
 form=r._once(outdir/'FORM_READBACK.json',{'title':{'content':m['title']},'description_core':m['description'],'hashtag_tokens':m['hashtags'],'description_exact':True})
 trigger=r._once(outdir/'DECLARATION_TRIGGER_PROJECTION.json',{'schema':'manual_draft_declaration_trigger/v5','truncated':False})
 return {'schema':'manual_republication_existing_draft/v7','action':'complete_existing_form','action_claim':a,'metadata':config['metadata'],'file_selection_claim':f,
 'form_readback':form,'declaration_trigger_projection':trigger,'metadata_readback_matched':True,'hashtag_readback_verified':True,'declaration_entry_expanded':False,
 'submitted':False,'declaration_selected':False,'navigation_performed':False,'file_selected':False,'publication_ready':False,
 'title_readback':{'content':m['title']},'description_readback':{'content':m['description']}}
'''
V8_FLOW='''from src.operations_accounts import manual_republication_runtime_v8 as r
class DeclarationInspectionBlocked(ValueError):pass
SAFE_REASONS=frozenset()
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 with (outdir/'ONCE').open('x') as f:f.write('protocol only')
 options=r._once(outdir/'DECLARATION_OPTIONS.json',{'schema':'manual_native_declaration_options/v8','complete_visible_capture':True,'truncated':False})
 return {'schema':'manual_republication_declaration_inspection/v8','action':'inspect_declaration_options','action_claim':r.reference(outdir.parent/'ACTION_CLAIM.json'),
 'file_selection_claim':request['file_selection_claim'],'metadata_readback_matched':True,'trigger_click_count':1,'options_observed':True,'same_tab':config['tab_id'],
 'options_inventory':options,'submitted':False,'declaration_selected':False,'confirmed':False,'navigation_performed':False,'file_selected':False,'fields_written':False,'publication_ready':False}
'''


def test_exact_receiver_preserves_history_once_and_rejects_write_action(v7_case,monkeypatch):
    c=v7_case;base=bridge.base
    paths=dict(base.SOURCE_PATHS);paths['flow_v7'].write_text(V7_FLOW,encoding='utf8')
    oldcfg=dict(c.config,sources={k:bridge.reference(p) for k,p in paths.items()});cfg7=put(c.run/'CONFIG_V7_FINAL.json',oldcfg)
    req7=put(c.run/'REQUEST_V7_FINAL.json',dict(c.request,config=cfg7))
    oldplan=base.prepare(cfg7,req7,c.run/'complete_v7');put(base.ARM,{'schema':'manual_republication_runtime_arm/v7','plan':oldplan})
    assert base.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    resultref=base.status(oldplan)['result'];result=bridge._read(resultref);oldfolder=Path(oldplan['path']).parent
    monkeypatch.setattr(bridge,'ROOT',base.ROOT);monkeypatch.setattr(bridge,'RUN',c.run);monkeypatch.setattr(bridge,'ARM',c.run/'runtime_v8/ARM.json')
    for key in ('runtime_v8','flow_v8'):
        path=base.ROOT/'src/operations_accounts'/f'{key}.py';path.write_text(V8_FLOW if key=='flow_v8' else '# reviewed protocol runtime',encoding='utf8');paths[key]=path
    monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
    cfg=dict(oldcfg,schema=bridge.CONFIG_SCHEMA,sources={k:bridge.reference(p) for k,p in paths.items()});cfgref=put(c.run/'CONFIG_V8.json',cfg)
    req=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action=bridge.ACTION,prepared_result=resultref,prepared_receipt=bridge.reference(oldfolder/'RESULT_BINDING.json'),
        form_readback=result['preparation']['form_readback'],file_selection_claim=result['file_selection_claim'],trigger_projection=result['preparation']['declaration_trigger_projection'])
    reqref=put(c.run/'REQUEST_V8.json',req)
    before={p:Path(p).read_bytes() for p in [c.prior_claim['path'],resultref['path'],req['file_selection_claim']['path']]}
    with pytest.raises(ValueError,match='inspection_only'):bridge.prepare(cfgref,put(c.run/'BAD_WRITE.json',dict(req,action='set_declarations')),c.run/'bad')
    planref=bridge.prepare(cfgref,reqref,c.run/'inspect_v8');put(bridge.ARM,{'schema':'manual_republication_runtime_arm/v8','plan':planref})
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    assert bridge.status(planref)['status']=='declaration_options_observed'
    assert bridge.install_if_armed()['status']=='declaration_options_observed'
    assert all(Path(p).read_bytes()==raw for p,raw in before.items())
