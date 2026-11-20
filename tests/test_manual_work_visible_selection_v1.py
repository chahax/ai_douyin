"""Actual observed Semi overlay geometry and trusted native display events."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_fanqie_backfill_editor_inspection_v1 import context
from src.operations_accounts import manual_work_cleanup_delete_runtime_v1 as bridge
from src.platform_adapter import douyin_work_cleanup_delete_v1 as adapter
from src.platform_adapter import douyin_work_cleanup_v1 as inspector
from src.platform_adapter.browser_session import Page

TARGETS=['7709043480894524722','7708948487446056192'];PROTECTED=['7709219071845256488','7700201288079920427']


def test_native_input_times_out_under_observed_display_then_visible_targets_emit_one_trusted_click_each(context):
    from playwright.sync_api import TimeoutError as NativeTimeout
    page=context.new_page();page.goto('https://www.douyin.com/user/self?from_tab_name=main')
    page.set_content('''<style>.semi-checkbox,.semi-checkbox-inner{position:relative;display:inline-block;width:22px;height:22px}.semi-checkbox-input{position:absolute;inset:0;width:22px;height:22px;opacity:0;z-index:1}.semi-checkbox-inner-display{position:absolute;inset:0;z-index:2;background:#eee;cursor:pointer}</style>
    <div><span>抖音号：</span><span>75891235130</span></div><section id="toolbar"><span>退出管理</span><span class="semi-checkbox"><span class="semi-checkbox-inner"><input class="semi-checkbox-input" type="checkbox" aria-checked="false"><span class="semi-checkbox-inner-display"></span></span></span><span>全选</span><span id="count">已选 0 个作品</span><span id="delete">删除</span><span>权限设置</span></section><ul>'''+''.join(
        '<li><a href="/video/'+p+'">'+('同一个两分钟标题' if p in TARGETS[:1]+PROTECTED[:1] else '作品')+'</a>'+('<span>流量减少</span>' if p in TARGETS else '')+
        '<span class="semi-checkbox semi-checkbox-unChecked semi-checkbox-cardType_enable"><span class="semi-checkbox-inner"><input class="semi-checkbox-input" type="checkbox" aria-checked="false"><span class="semi-checkbox-inner-display"></span></span></span></li>' for p in PROTECTED[:1]+TARGETS+PROTECTED[1:])+'''</ul>
    <script>window.chosen=new Set();window.clicks=[];window.opens=0;window.confirms=0;
    document.querySelectorAll('li .semi-checkbox-inner-display').forEach(display=>display.onclick=()=>{const p=display.closest('li').querySelector('a').getAttribute('href').split('/').pop();window.clicks.push(p);window.chosen.add(p);
      display.closest('.semi-checkbox').classList.remove('semi-checkbox-unChecked');display.closest('.semi-checkbox').classList.add('semi-checkbox-checked');count.textContent='已选 '+chosen.size+' 个作品';
      const global=document.querySelector('#toolbar input');global.indeterminate=true;global.setAttribute('aria-checked','mixed');});
    document.querySelector('#toolbar .semi-checkbox-inner-display').onclick=()=>window.clicks.push('GLOBAL');
    document.querySelector('#delete').onclick=()=>{window.opens++;const modal=document.createElement('div');modal.className='semi-modal';modal.setAttribute('role','dialog');modal.innerHTML='<p>真实确认内容待只读采集</p><button id="confirm" type="button">确认按钮测试</button>';document.body.append(modal);confirm.onclick=()=>window.confirms++;};</script>''')
    with pytest.raises(NativeTimeout):page.locator(adapter.checkbox_selector(TARGETS[0])).nth(0).click(timeout=180)
    assert page.evaluate('()=>window.clicks')==[]
    stages=[]
    class Original:
        _session=object();tab_id='same-tab'
        def evaluate(self,js):return page.evaluate(js)
        def locator(self,selector):return page.locator(selector)
        def wait_for_timeout(self,ms):page.wait_for_timeout(ms)
    nonce='a'*32
    result=adapter.select_visible_targets_open_confirmation(Original(),guard=lambda:None,checkpoint=lambda s,v:stages.append((s,v)),inventory_script=inspector.INVENTORY_JS,
        expected_uid='75891235130',delete_ids=TARGETS,protected_ids=PROTECTED,event_nonce=nonce)
    assert result['status']=='confirmation_observed' and page.evaluate('()=>window.clicks')==TARGETS
    assert page.evaluate('()=>[window.opens,window.confirms]')==[1,0]
    assert page.evaluate('()=>[...document.querySelectorAll("input")].map(e=>e.checked)')==[False]*5
    final=result['event_recorder_final'];assert final['nonce']==nonce and final['active'] is False and final['trusted_display_click_counts']=={p:1 for p in TARGETS}
    assert final['blocked_event_count']==final['outside_target_trusted_clicks']==0
    assert all(e['is_trusted'] for e in final['events']) and {e['post_id'] for e in final['events']}==set(TARGETS)
    assert not result['confirmation_performed'] and not result['deleted']
    page.close()


def test_actual_zero_probe_history_and_protected_display_rpc_gate(tmp_path,monkeypatch):
    ref=bridge.reference(bridge.RUN/'current_selection_001/RESULT.json');result=bridge.read(ref);plan=bridge.read(result['plan']);old=bridge.read(plan['config'])
    config=dict(old,sources=dict(old['sources'],cleanup_runtime=bridge.reference(bridge.__file__),adapter=bridge.reference(adapter.__file__)))
    request=dict(current_selection_result=ref,prior_unknown=bridge.read(plan['request'])['prior_unknown'])
    before=Path(request['prior_unknown']['path']).read_bytes();proof=bridge._current_probe_prior(request,config)
    assert proof['past_dom_event_count'] is None and Path(request['prior_unknown']['path']).read_bytes()==before
    folder=tmp_path/'protocol';folder.mkdir();arm=folder/'ARM.json';arm.write_text('{}');monkeypatch.setattr(bridge,'ARM',arm)
    cfg=dict(tab_id='same-tab',owner_id='same-owner',generation=33,authority={});plan=dict(config={},request={},state={},batch_entry_clicks_allowed=0,selections_allowed=2,interaction_nonce='b'*32);request=dict(action=bridge.VISIBLE_SELECT_ACTION)
    pref=dict(path=str(folder/'PLAN.json'),sha256='private');monkeypatch.setattr(bridge,'_plan',lambda ref:(plan,cfg,request));monkeypatch.setattr(bridge,'_config',lambda ref:cfg);monkeypatch.setattr(bridge,'validate_live',lambda *a:{})
    class Owner:
        def get_page(self,tab):return Page(self,tab)
        def cmd(self,kind,**kw):pytest.fail('protected display click forwarded')
    def evil(page,**kwargs):page.locator(adapter.display_selector(PROTECTED[0])).nth(0).click(timeout=8000)
    fake=NS(select_visible_targets_open_confirmation=evil,display_selector=adapter.display_selector,DELETE_ENTRY=adapter.DELETE_ENTRY)
    monkeypatch.setattr(bridge,'_load',lambda k,c:fake if k=='adapter' else inspector);monkeypatch.setattr(bridge,'read',lambda ref:dict(expected_public_uid='75891235130',delete_douyin_only_ids=TARGETS,protected_post_ids=PROTECTED))
    assert bridge._perform(NS(owner_id='same-owner',generation=33),NS(session=Owner()),pref,bridge.reference(arm))['status']=='batch_observation_unknown'
    error=json.loads((folder/'UNKNOWN.json').read_text(encoding='utf8'));assert error['target_native_dispatches']==[] and error['delete_entry_native_dispatches']==0
