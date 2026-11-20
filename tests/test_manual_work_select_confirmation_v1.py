"""Native UI causality, plus actual immutable producer history/RPC boundary."""
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


def test_real_prevent_default_component_selection_native_false_mixed_global_opens_only_confirmation(context):
    page=context.new_page();page.goto('https://www.douyin.com/user/self?from_tab_name=main')
    page.set_content('''<div><span>抖音号：</span><span>75891235130</span></div><section id="toolbar"><div>退出管理</div>
      <div class="semi-checkbox" id="globalwrap"><input class="semi-checkbox-input" type="checkbox" aria-checked="false" id="all"></div><span>全选</span>
      <span id="counter">已选 0 个作品</span><div id="delete">删除</div><div>权限设置</div></section><ul>'''+''.join(
      '<li><a href="/video/'+p+'">'+('相同两分钟标题' if p in TARGETS[:1]+PROTECTED[:1] else '作品')+'</a>'+('<span>流量减少</span>' if p in TARGETS else '')+
      '<div class="semi-checkbox"><input class="semi-checkbox-input" type="checkbox" aria-checked="false"></div></li>' for p in PROTECTED[:1]+TARGETS+PROTECTED[1:])+'''</ul>
      <script>window.chosen=new Set();window.clicked=[];window.opens=0;window.confirms=0;
      document.querySelectorAll('li input').forEach(input=>input.onclick=e=>{e.preventDefault();const post=input.closest('li').querySelector('a').getAttribute('href').split('/').pop();window.clicked.push(post);
        setTimeout(()=>{window.chosen.add(post);input.parentElement.classList.add('semi-checkbox-checked');counter.textContent='已选 '+chosen.size+' 个作品';
          all.indeterminate=true;all.setAttribute('aria-checked','mixed');globalwrap.classList.add('semi-checkbox-checked','semi-checkbox-indeterminate');},0);});
      document.querySelector('#all').onclick=e=>{e.preventDefault();window.clicked.push('GLOBAL')};
      document.querySelector('#delete').onclick=()=>{window.opens++;const dialog=document.createElement('div');dialog.className='semi-modal';dialog.setAttribute('role','dialog');
        dialog.innerHTML='<h2>实际确认内容留待读取</h2><p>2 个作品</p><button id="confirm" type="button">测试确认</button><button type="button">取消</button>';document.body.append(dialog);document.querySelector('#confirm').onclick=()=>window.confirms++;};</script>''')
    stages=[]
    class Original:
        _session=object();tab_id='original-tab'
        def locator(self,selector):return page.locator(selector)
        def evaluate(self,script):return page.evaluate(script)
        def wait_for_timeout(self,ms):page.wait_for_timeout(ms)
    value=adapter.select_targets_open_confirmation(Original(),guard=lambda:None,checkpoint=lambda s,v:stages.append((s,v)),inventory_script=inspector.INVENTORY_JS,
        expected_uid='75891235130',delete_ids=TARGETS,protected_ids=PROTECTED)
    assert value['status']=='confirmation_observed' and value['selected_ids']==TARGETS and not value['confirmation_performed'] and not value['deleted']
    assert page.evaluate('()=>[...window.clicked]')==TARGETS and page.evaluate('()=>[window.opens,window.confirms]')==[1,0]
    assert page.evaluate('()=>[...document.querySelectorAll("input")].map(e=>e.checked)')==[False]*5
    proof=next(v for s,v in stages if s=='delete_entry_proof');assert proof['selected_count']==2
    selected={x['post_id'] for x in proof['controls'] if x['post_id'] and x['public_selected']};assert selected==set(TARGETS)
    global_control=next(x for x in proof['controls'] if x['post_id'] is None)
    assert global_control['aria_checked']=='mixed' and global_control['indeterminate'] and not global_control['native_checked']
    assert all(not x['public_selected'] for x in proof['controls'] if x['post_id'] in PROTECTED)
    page.close()


def test_actual_old_batch_producer_history_survives_current_delta_and_protected_click_is_denied(tmp_path,monkeypatch):
    old_result=bridge.reference(bridge.RUN/'batch_controls_001/RESULT.json');actual=bridge.read(old_result);old_plan=bridge.read(actual['plan']);old_config=bridge.read(old_plan['config'])
    config=dict(old_config,sources=dict(old_config['sources'],cleanup_runtime=bridge.reference(bridge.__file__),adapter=bridge.reference(adapter.__file__)))
    history=bridge._batch_prior(dict(batch_result=old_result),config)
    assert history['batch_result']==old_result and history['producer_source_snapshot']['cleanup_runtime']['sha256']==bridge.BATCH_PRODUCER_SHA['cleanup_runtime']
    assert config['sources']['cleanup_runtime']['sha256']!=old_config['sources']['cleanup_runtime']['sha256']
    root=tmp_path/'protocol';root.mkdir();arm=root/'ARM.json';arm.write_text('{}');monkeypatch.setattr(bridge,'ARM',arm)
    cfg=dict(account_id='original',owner_id='same-owner',generation=33,tab_id='same-tab',authority={});plan=dict(config={},request={},state={},batch_entry_clicks_allowed=0,selections_allowed=2);req=dict(action=bridge.SELECT_ACTION)
    pref=dict(path=str(root/'PLAN.json'),sha256='test');monkeypatch.setattr(bridge,'_plan',lambda ref:(plan,cfg,req));monkeypatch.setattr(bridge,'_config',lambda ref:cfg);monkeypatch.setattr(bridge,'validate_live',lambda *a:{})
    class Owner:
        def get_page(self,tab):return Page(self,tab)
        def cmd(self,kind,**kw):pytest.fail('protected native interaction forwarded')
    def evil(page,**kw):page.locator(adapter.checkbox_selector(PROTECTED[0])).nth(0).click(timeout=8000)
    fake=NS(select_targets_open_confirmation=evil,checkbox_selector=adapter.checkbox_selector,DELETE_ENTRY=adapter.DELETE_ENTRY)
    monkeypatch.setattr(bridge,'_load',lambda key,c:fake if key=='adapter' else inspector)
    monkeypatch.setattr(bridge,'read',lambda ref:dict(expected_public_uid='75891235130',delete_douyin_only_ids=TARGETS,protected_post_ids=PROTECTED))
    result=bridge._perform(NS(owner_id='same-owner',generation=33),NS(session=Owner()),pref,bridge.reference(arm))
    assert result['status']=='batch_observation_unknown'
    unknown=json.loads((root/'UNKNOWN.json').read_text(encoding='utf8'))
    assert unknown['target_native_dispatches']==[] and unknown['delete_entry_native_dispatches']==0 and unknown['reason']=='cleanup_only_exact_targets_and_toolbar_entry_allowed'
