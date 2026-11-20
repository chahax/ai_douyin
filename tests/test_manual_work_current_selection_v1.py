"""Zero-event actual DOM obstruction probe and immutable UNKNOWN/RPC guards."""
import json
from types import SimpleNamespace as NS

import pytest
from test_fanqie_backfill_editor_inspection_v1 import context
from src.operations_accounts import manual_work_cleanup_delete_runtime_v1 as bridge
from src.platform_adapter import douyin_work_cleanup_delete_v1 as adapter
from src.platform_adapter.browser_session import Page


def test_native_overlay_geometry_and_raw_false_selection_are_only_observed(context):
    page=context.new_page();page.goto('https://www.douyin.com/user/self?from_tab_name=main')
    page.set_content('''<style>.semi-checkbox{display:inline-block;position:relative;width:24px;height:24px}.semi-checkbox input{position:absolute;inset:0;width:24px;height:24px;opacity:0;z-index:1}.mask{position:absolute;inset:0;z-index:2;background:#eee}</style>
    <span>已选 0 个作品</span><ul>'''+''.join('<li><a href="/video/'+post+'">作品</a><span class="semi-checkbox semi-checkbox-unChecked"><input class="semi-checkbox-input" type="checkbox" aria-checked="false"><span class="mask"></span></span></li>' for post in ['7709219071845256488','7709043480894524722','7708948487446056192','7700201288079920427'])+'''</ul>
    <script>window.clicks=0;document.addEventListener('click',()=>window.clicks++);document.querySelectorAll('input').forEach(e=>Object.defineProperty(e,'value',{get(){throw Error('value read')}}));</script>''')
    class Original:
        _session=object();tab_id='same-tab'
        def evaluate(self,script):return page.evaluate(script)
    stages=[];value=adapter.inspect_current_selection(Original(),guard=lambda:None,checkpoint=lambda s,v:stages.append((s,v)))
    observed=value['observation'];assert observed['selected_count_texts']==['已选 0 个作品'] and observed['visible_modal_count']==0
    old=next(c for c in observed['controls'] if c['post_ids']==['7709043480894524722'])
    assert not old['native_checked'] and old['aria_checked']=='false' and old['style']['opacity']=='0'
    assert not old['center_hit_is_input'] and old['center_hit_inside_component'] and old['center_hit']['class_name']=='mask' and len(old['hit_stack'])>1
    assert observed['original_attempt_event_recorder']['capture_event_count'] is None and observed['original_attempt_event_recorder']['nonce'] is None
    assert value['native_events_dispatched']==0 and page.evaluate('()=>window.clicks')==0
    page.close()


def test_actual_original_unknown_history_preserved_and_inspection_rpc_cannot_click(tmp_path,monkeypatch):
    ref=bridge.reference(bridge.RUN/'select_001/UNKNOWN.json');original=__import__('pathlib').Path(ref['path']).read_bytes();old=bridge.read(ref);plan=bridge.read(old['plan']);cfg=bridge.read(plan['config'])
    current=dict(cfg,sources=dict(cfg['sources'],cleanup_runtime=bridge.reference(bridge.__file__),adapter=bridge.reference(adapter.__file__)))
    proof=bridge._unknown_selection_prior(dict(prior_unknown=ref),current)
    assert proof['dispatched_native_selectors']==['7709043480894524722'] and not proof['original_dom_events_known']
    assert __import__('pathlib').Path(ref['path']).read_bytes()==original
    assert bridge._safe_error(RuntimeError('Locator.click: Timeout 8000ms exceeded.\nCookie: secret'))=='Locator.click: Timeout 8000ms exceeded.'
    assert 'token' not in bridge._safe_error(RuntimeError('Read failed https://user:pass@host/path?token=secret'))
    folder=tmp_path/'protocol';folder.mkdir();arm=folder/'ARM.json';arm.write_text('{}');monkeypatch.setattr(bridge,'ARM',arm)
    config=dict(tab_id='same-tab',owner_id='same-owner',generation=33,authority={});plan=dict(config={},request={},state={},batch_entry_clicks_allowed=0,selections_allowed=0);request=dict(action=bridge.INSPECT_SELECTION_ACTION)
    pref=dict(path=str(folder/'PLAN.json'),sha256='fixture');monkeypatch.setattr(bridge,'_plan',lambda ref:(plan,config,request));monkeypatch.setattr(bridge,'_config',lambda ref:config);monkeypatch.setattr(bridge,'validate_live',lambda *a:{})
    class Owner:
        def get_page(self,tab):return Page(self,tab)
        def cmd(self,kind,**kw):pytest.fail('readonly action forwarded a native click')
    def evil(page,**kw):page.locator(adapter.checkbox_selector('7709043480894524722')).nth(0).click(timeout=8000)
    fake=NS(inspect_current_selection=evil)
    monkeypatch.setattr(bridge,'_load',lambda key,c:fake);monkeypatch.setattr(bridge,'read',lambda ref:dict(expected_public_uid='75891235130',delete_douyin_only_ids=['7709043480894524722'],protected_post_ids=['7709219071845256488']))
    value=bridge._perform(NS(owner_id='same-owner',generation=33),NS(session=Owner()),pref,bridge.reference(arm))
    unknown=json.loads((folder/'UNKNOWN.json').read_text(encoding='utf8'))
    assert value['status']=='batch_observation_unknown' and unknown['safe_error']=='cleanup_inspection_has_no_click_permission'
    assert unknown['target_native_dispatches']==[] and unknown['delete_entry_native_dispatches']==0
