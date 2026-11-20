"""Same capability after a known exact zero-click failure; private stores only."""
from pathlib import Path
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
from test_manual_republication_runtime_v8 import V7_FLOW,put
from src.operations_accounts import manual_republication_runtime_v9 as bridge

FAILED='''from src.operations_accounts import manual_republication_runtime_v8 as r
class DeclarationInspectionBlocked(ValueError):
 def __init__(self,code):self.code=code;super().__init__(code)
SAFE_REASONS=frozenset({'declaration_trigger_unconfirmed'})
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 r._once(outdir/'TRIGGER_BEFORE.json',{'schema':'manual_native_declaration_trigger/v8','location':{'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'},'section_count':1,'control_count':1,'value_count':1,'value':'请选择自主声明','cursor':'pointer','pointer_events':'auto','view_only_eligible':True,'center_hit':False,'armed':False})
 trace=outdir/'RPC_TRACE.jsonl';trace.write_text('{"event":"rpc_dispatched","action":"evaluate"}\\n',encoding='utf8')
 r._once(outdir/'INSPECTION_FAILURE.json',{'schema':'manual_declaration_inspection_failure/v8','reason_code':'declaration_trigger_unconfirmed','trigger_click_dispatched':False,'rpc_trace':r.reference(trace),'submitted':False,'declaration_selected':False,'confirmed':False,'fields_written':False,'file_selected':False,'navigation_performed':False})
 raise DeclarationInspectionBlocked('declaration_trigger_unconfirmed')
'''
FLOW='''from src.operations_accounts import manual_republication_runtime_v9 as r
class DeclarationInspectionBlocked(ValueError):pass
SAFE_REASONS=frozenset()
def run_action(actor,resource,config,request,outdir):
 outdir.mkdir(parents=True,exist_ok=True)
 with (outdir/'ONCE').open('x') as f:f.write('protocol only')
 action=r.reference(outdir.parent/'ACTION_CLAIM.json');plan=r._read(r._read(action)['plan'])
 options=r._once(outdir/'DECLARATION_OPTIONS.json',{'schema':'manual_native_declaration_options/v9','complete_visible_capture':True,'truncated':False})
 return {'schema':'manual_republication_declaration_inspection/v9','action':r.ACTION,'action_claim':action,'file_selection_claim':plan['prior']['file_selection_claim'],
 'metadata_readback_matched':True,'trigger_click_count':1,'scroll_performed':True,'options_observed':True,'same_tab':config['tab_id'],'options_inventory':options,
 'submitted':False,'declaration_selected':False,'confirmed':False,'navigation_performed':False,'file_selected':False,'fields_written':False,'publication_ready':False}
'''


def test_zero_click_successor_preserves_records_and_same_read_capability(v7_case,monkeypatch):
    c=v7_case;v8=bridge.base;v7=v8.base
    paths=dict(v7.SOURCE_PATHS);paths['flow_v7'].write_text(V7_FLOW,encoding='utf8')
    cfg7=put(c.run/'V7_FINAL_CONFIG.json',dict(c.config,sources={k:v7.reference(p) for k,p in paths.items()}))
    req7=put(c.run/'V7_FINAL_REQUEST.json',dict(c.request,config=cfg7));p7=v7.prepare(cfg7,req7,c.run/'complete_v7')
    put(v7.ARM,{'schema':'manual_republication_runtime_arm/v7','plan':p7});assert v7.install_if_armed()['status'].startswith('callback_registered')
    c.namespace['_poll_manual_windows'](c.actor,c.resource);r7=v7._read(v7.status(p7)['result']);f7=Path(p7['path']).parent
    for module,version,body in [(v8,8,FAILED),(bridge,9,FLOW)]:
        monkeypatch.setattr(module,'ROOT',v7.ROOT);monkeypatch.setattr(module,'RUN',c.run);monkeypatch.setattr(module,'ARM',c.run/f'runtime_v{version}/ARM.json')
        for key in (f'runtime_v{version}',f'flow_v{version}'):
            path=v7.ROOT/'src/operations_accounts'/f'{key}.py';path.write_text(body if key.startswith('flow') else '# private protocol runtime',encoding='utf8');paths[key]=path
        monkeypatch.setattr(module,'SOURCE_PATHS',dict(paths))
    cfg8=put(c.run/'CONFIG_V8.json',dict(v7._read(cfg7),schema=v8.CONFIG_SCHEMA,sources={k:v8.reference(p) for k,p in v8.SOURCE_PATHS.items()}))
    req8=put(c.run/'REQUEST_V8.json',dict(schema=v8.REQUEST_SCHEMA,config=cfg8,action=v8.ACTION,prepared_result=v7.status(p7)['result'],prepared_receipt=v7.reference(f7/'RESULT_BINDING.json'),
        form_readback=r7['preparation']['form_readback'],file_selection_claim=r7['file_selection_claim'],trigger_projection=r7['preparation']['declaration_trigger_projection']))
    p8=v8.prepare(cfg8,req8,c.run/'failed_v8');put(v8.ARM,{'schema':'manual_republication_runtime_arm/v8','plan':p8});assert v8.install_if_armed()['status'].startswith('callback_registered')
    c.namespace['_poll_manual_windows'](c.actor,c.resource);assert v8.status(p8)['status']=='outcome_unknown'
    folder=Path(p8['path']).parent;cfg9=put(c.run/'CONFIG_V9.json',dict(v7._read(cfg7),schema=bridge.CONFIG_SCHEMA,sources={k:bridge.reference(p) for k,p in paths.items()}))
    req=dict(schema=bridge.REQUEST_SCHEMA,config=cfg9,action=bridge.ACTION,prior_inspection_plan=p8,prior_inspection_action=bridge.reference(folder/'ACTION_CLAIM.json'),
        prior_unknown=bridge.reference(folder/'UNKNOWN.json'),prior_failure=bridge.reference(folder/'inspection/INSPECTION_FAILURE.json'),trigger_before=bridge.reference(folder/'inspection/TRIGGER_BEFORE.json'))
    before={ref['path']:Path(ref['path']).read_bytes() for ref in [r7['file_selection_claim'],*[req[k] for k in bridge.PRIOR_FIELDS]]}
    # An already-clicked failure is not this narrow continuation capability.
    bad=put(c.run/'WRONG_PRIOR_FAILURE.json',dict(bridge._read(req['prior_failure']),trigger_click_dispatched=True))
    with pytest.raises(ValueError,match='known_zero_click'):bridge.prepare(cfg9,put(c.run/'BAD_REQUEST.json',dict(req,prior_failure=bad)),c.run/'bad')
    p9=bridge.prepare(cfg9,put(c.run/'REQUEST_V9.json',req),c.run/'inspect_v9');put(bridge.ARM,{'schema':'manual_republication_runtime_arm/v9','plan':p9})
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    assert bridge.status(p9)['status']=='declaration_options_observed' and bridge.install_if_armed()['status']=='declaration_options_observed'
    assert all(Path(path).read_bytes()==raw for path,raw in before.items())
