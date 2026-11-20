"""One observed-shape real DOM and one strict RPC boundary protocol case."""
import json
from types import SimpleNamespace as NS

import pytest
from test_fanqie_backfill_editor_inspection_v1 import context
from src.operations_accounts import manual_work_cleanup_delete_runtime_v1 as bridge
from src.platform_adapter import douyin_work_cleanup_delete_v1 as adapter
from src.platform_adapter import douyin_work_cleanup_v1 as inspector
from src.platform_adapter.browser_session import Page


TARGETS=['7709043480894524722','7708948487446056192'];PROTECTED=['7709219071845256488','7700201288079920427']


def test_native_batch_entry_once_projects_all_label_checkbox_associations_without_selection(context):
    page=context.new_page();page.goto('https://www.douyin.com/user/self?from_tab_name=main')
    page.set_content('''<div><span>抖音号：</span><span>75891235130</span></div><div class="FmoW3iJu">批量管理</div>
      <ul>'''+''.join('<li><a href="/video/'+p+'">'+('同标题两分钟完整版' if p in TARGETS[:1]+PROTECTED[:1] else '作品')+'</a>'+('<span>流量减少</span>' if p in TARGETS else '')+'</li>' for p in PROTECTED[:1]+TARGETS+PROTECTED[1:])+'''</ul>
      <div id="toolbar" hidden><label><input type="checkbox">全选</label><button id="delete" type="button">删除</button></div>
      <script>window.entries=0;window.changes=0;window.deletes=0;
      document.addEventListener('change',()=>window.changes++);document.querySelector('#delete').onclick=()=>window.deletes++;
      document.querySelector('.FmoW3iJu').onclick=()=>{window.entries++;toolbar.hidden=false;document.querySelectorAll('li').forEach(li=>{
        const label=document.createElement('label');label.innerHTML='<input type="checkbox" style="display:none">选择作品';li.append(label);
        Object.defineProperty(label.querySelector('input'),'value',{get(){throw Error('value read')}});});};</script>''')
    stages=[]
    class OriginalPage:
        _session=object();tab_id='same-tab'
        def evaluate(self,script):return page.evaluate(script)
        def locator(self,selector):return page.locator(selector)
        def wait_for_timeout(self,ms):pass
    value=adapter.open_batch_controls(OriginalPage(),guard=lambda:None,checkpoint=lambda s,v:stages.append((s,v)),inventory_script=inspector.INVENTORY_JS,
        expected_uid='75891235130',delete_ids=TARGETS,protected_ids=PROTECTED)
    assert value['status']=='batch_controls_observed' and value['batch_entry_click_count']==1 and value['entry_ack_returned']
    native=value['inventory']['native_controls'];assert len(native)==5
    associated={r['unique_native_post_id']:r for r in native if r['unique_native_post_id']}
    assert set(associated)==set(TARGETS+PROTECTED)
    assert all(r['checked_read_allowed'] and r['checked'] is False and len(r['label_associations'])==1 for r in associated.values())
    assert all(r['label_associations'][0]['association']=='native_wrapping_label' for r in associated.values())
    assert page.evaluate('()=>[window.entries,window.changes,window.deletes]')==[1,0,0]
    assert value['inventory']['visible_modal_count']==0 and not value['selection_performed'] and not value['delete_performed'] and not value['delete_allowed']
    page.close()


def test_wrong_scope_and_unapproved_checkbox_rpc_stop_before_any_native_interaction(tmp_path,monkeypatch):
    run=tmp_path/'batch';run.mkdir();arm=run/'ARM.json';arm.write_text('{}');monkeypatch.setattr(bridge,'ARM',arm)
    cfg=dict(account_id='original-account',owner_id='original-owner',generation=33,tab_id='original-tab',authority={})
    plan_ref=dict(path=str(run/'PLAN.json'),sha256='bound');plan=dict(config={},request={},state={'same':True});req=dict(action=bridge.ACTION)
    monkeypatch.setattr(bridge,'_plan',lambda ref:(plan,cfg,req));monkeypatch.setattr(bridge,'_config',lambda ref:cfg)
    actor=NS(owner_id='wrong-owner',generation=33);calls=[]
    class Owner:
        def get_page(self,tab):return Page(self,tab)
        def cmd(self,kind,**kw):calls.append((kind,kw));raise AssertionError('native RPC forbidden')
    resource=NS(session=Owner())
    def guard(a,r,c):
        if a.owner_id!=c['owner_id']:raise ValueError('wrong original owner')
        return plan['state']
    monkeypatch.setattr(bridge,'validate_live',guard)
    def malicious(page,**kw):page.locator('input[type="checkbox"]').click()
    monkeypatch.setattr(bridge,'_load',lambda key,config:NS(open_batch_controls=malicious,ENTRY=adapter.ENTRY,BATCH_JS=adapter.BATCH_JS,ENTRY_PROBE=adapter.ENTRY_PROBE) if key=='adapter' else inspector)
    monkeypatch.setattr(bridge,'read',lambda ref:{'expected_public_uid':'75891235130','delete_douyin_only_ids':TARGETS,'protected_post_ids':PROTECTED})
    ref=bridge.reference(arm)
    with pytest.raises(ValueError):bridge._perform(actor,resource,plan_ref,ref)
    assert not calls and not (run/'ACTION_CLAIM.json').exists()
    actor.owner_id='original-owner';result=bridge._perform(actor,resource,plan_ref,ref)
    assert result['status']=='batch_observation_unknown' and calls==[]
    error=json.loads((run/'UNKNOWN.json').read_text(encoding='utf8'))
    assert error['reason']=='cleanup_only_observed_batch_entry_click_allowed' and error['batch_entry_native_dispatches']==0
    assert bridge._perform(actor,resource,plan_ref,ref)['status']=='batch_observation_unknown' and calls==[]
