"""Current-modal receiver, real prior protocol and immutable producer bytes."""
from pathlib import Path
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
from test_manual_republication_runtime_v8 import put
from test_manual_republication_runtime_v9 import test_zero_click_successor_preserves_records_and_same_read_capability as build_v9
from src.operations_accounts import manual_republication_runtime_v10 as bridge

FLOW='''from src.operations_accounts import manual_republication_runtime_v10 as r
class DeclarationControlsBlocked(ValueError):pass
SAFE_REASONS=frozenset()
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 outdir.mkdir(parents=True,exist_ok=True)
 with (outdir/'ONCE').open('x') as f:f.write('protocol only')
 controls=r._once(outdir/'MODAL_CONTROLS.json',{'render_complete':True})
 return {'schema':'manual_republication_declaration_controls/v10','action':r.ACTION,'action_claim':r.reference(outdir.parent/'ACTION_CLAIM.json'),
 'render_complete':True,'modal_controls':controls,'input_performed':False,'selection_performed':False,'declaration_confirmed':False,
 'publish_clicked':False,'navigation_performed':False,'file_selected':False,'submitted':False}
'''


def test_current_modal_receiver_prior_options_status_and_snapshot_survive_code_delta(v7_case,monkeypatch):
    c=v7_case;build_v9(c,monkeypatch);v9=bridge.base
    p9=v9.reference(c.run/'inspect_v9/PLAN.json');r9=v9.status(p9)['result'];result=v9._read(r9)
    assert result['status']=='declaration_options_observed'
    # The shared prior protocol intentionally does not have real modal help.
    # Add that observation to its producer fixture, without changing the runtime
    # or original state/status semantics being exercised.
    old_options=result['inspection']['options_inventory'];options=v9._read(old_options)
    options.update(location={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'},visible_text='请选择声明类型（单选）')
    updated=put(Path(old_options['path']),dict(options,schema='manual_native_declaration_options/v9'))
    events=put(c.run/'inspect_v9/inspection/DISCLOSURE_EVENTS.json',dict(allowed_clicks=1,blocked_events=0))
    result['inspection'].update(options_inventory=updated,disclosure_events=events,action=v9.ACTION,schema='manual_republication_declaration_inspection/v9',
        same_tab=c.config['tab_id'],scroll_performed=True,trigger_click_count=1,metadata_readback_matched=True,options_observed=True)
    result['inspection'].update({k:False for k in ('submitted','declaration_selected','confirmed','navigation_performed','file_selected','fields_written','publication_ready')})
    r9=put(Path(r9['path']),result);old_receipt=c.run/'inspect_v9/RESULT_BINDING.json';receipt=v9._read(v9.reference(old_receipt));receipt['result']=r9;put(old_receipt,receipt)
    monkeypatch.setattr(bridge,'ROOT',v9.ROOT);monkeypatch.setattr(bridge,'RUN',c.run);monkeypatch.setattr(bridge,'ARM',c.run/'runtime_v10/ARM.json')
    paths=dict(v9.SOURCE_PATHS)
    for key in ('runtime_v10','flow_v10'):
        path=v9.ROOT/'src/operations_accounts'/f'{key}.py';path.write_text(FLOW if key=='flow_v10' else '# private protocol runtime',encoding='utf8');paths[key]=path
    monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
    cfg=dict(v9._read(v9._read(p9)['config']),schema=bridge.CONFIG_SCHEMA,sources={k:bridge.reference(p) for k,p in paths.items()})
    cfgref=put(c.run/'CONFIG_V10.json',cfg)
    req=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action=bridge.ACTION,prior_result=r9,prior_receipt=bridge.reference(old_receipt),options_inventory=updated)
    before={ref['path']:Path(ref['path']).read_bytes() for ref in (r9,req['prior_receipt'],result['file_selection_claim'])}
    with pytest.raises(ValueError,match='inspection_only'):bridge.prepare(cfgref,put(c.run/'BAD_ACTION_V10.json',dict(req,action='set_declaration_and_publish_once')),c.run/'bad_v10')
    p10=bridge.prepare(cfgref,put(c.run/'REQUEST_V10.json',req),c.run/'controls_v10');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=p10))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    assert bridge.status(p10)['status']=='declaration_controls_observed' and bridge.install_if_armed()['status']=='declaration_controls_observed'
    assert all(Path(p).read_bytes()==raw for p,raw in before.items())
    plan=bridge._read(p10);paths['flow_v10'].write_text('# separately reviewed future writer',encoding='utf8')
    assert bridge.validate_producer_snapshot(plan,cfg,p10)==plan['producer_source_snapshot']
    assert bridge.status(p10)['status']=='declaration_controls_observed'
    # The original imported loader callable must execute a newly pinned stage
    # even while that old callable and runtime module remain cached.
    loader=bridge.install_fresh_if_armed
    paths['runtime_v10'].write_text("def install_if_armed():return {'status':'fresh_stage_two_loaded'}\n",encoding='utf8')
    assert loader()['status']=='refused'  # Original ARM still pins the old bytes.
    next_config=dict(cfg,sources=dict(cfg['sources'],runtime_v10=bridge.reference(paths['runtime_v10'])))
    next_cfg=put(c.run/'STAGE_TWO_CONFIG.json',next_config)
    next_plan=put(c.run/'STAGE_TWO_PLAN.json',dict(schema=bridge.PLAN_SCHEMA,config=next_cfg))
    put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=next_plan))
    assert loader()=={'status':'fresh_stage_two_loaded'}
    snapshot=Path(plan['producer_source_snapshot']['flow_v10']['path']);snapshot.write_bytes(snapshot.read_bytes()+b' changed')
    with pytest.raises(ValueError):bridge.validate_producer_snapshot(plan,cfg,p10)
    with pytest.raises(ValueError):bridge.status(p10)
