"""Concrete roleless modal, late durable claim, native absence after one reload."""
import json
from pathlib import Path
import threading
from types import SimpleNamespace as NS

import pytest
from test_fanqie_backfill_editor_inspection_v1 import context
from src.operations_accounts import manual_work_cleanup_delete_runtime_v1 as bridge
from src.platform_adapter import douyin_work_cleanup_delete_v1 as adapter
from src.platform_adapter import douyin_work_cleanup_v1 as inspector


TARGETS=['7709043480894524722','7708948487446056192'];PROTECTED=['7709219071845256488','7700201288079920427']


@pytest.mark.parametrize('lost_ack',[False,True])
def test_roleless_exact_modal_once_keeps_protected_and_reloaded_native_ids_prove_absence(context,tmp_path,monkeypatch,lost_ack):
    contract_ref=bridge.reference(bridge.RUN/'DOUYIN_FINAL_DELETE_CONTRACT.json');contract=bridge.read(contract_ref);actual=bridge.read(contract['selection_result']);old_plan=bridge.read(actual['plan']);old_config=bridge.read(old_plan['config'])
    current=dict(old_config,sources=dict(old_config['sources'],cleanup_runtime=bridge.reference(bridge.__file__),adapter=bridge.reference(adapter.__file__)))
    history=bridge._final_contract_prior(dict(selection_result=contract['selection_result'],deletion_contract=contract_ref),current)
    assert history['event_nonce']==actual['inspection']['event_nonce'] and actual['inspection']['confirmation']['visible_modal_count']==0
    page=context.new_page();url=contract['post_confirm_readonly_reload_url'];page.goto(url)
    state=NS(deleted=False,confirms=0,private=0,reloads=0)
    def render(deleted=False):
        ids=PROTECTED if deleted else PROTECTED[:1]+TARGETS+PROTECTED[1:]
        page.set_content('<div><span>抖音号：</span><span>75891235130</span></div><div id="toolbar"><span>退出管理</span><input type="checkbox" class="semi-checkbox-input" aria-checked="false"><span>全选</span><span>已选 '+('0' if deleted else '2')+' 个作品</span><span>删除</span><span>权限设置</span></div><ul>'+''.join('<li><a href="/video/'+p+'">同标题作品</a>'+('<span>流量减少</span>' if p in TARGETS else '')+'<span class="semi-checkbox '+('semi-checkbox-checked' if p in TARGETS else 'semi-checkbox-unChecked')+'"><input class="semi-checkbox-input" type="checkbox" '+('checked aria-checked="true"' if p in TARGETS else 'aria-checked="false"')+'></span></li>' for p in ids)+'</ul>'+('' if deleted else '''<div id="confirmation" style="position:fixed;left:150px;top:80px;background:white;padding:25px;z-index:10">
          <h3>确认删除2个作品？</h3><p>删除后作品将无法找回，建议设为私密作品</p><button type="button" id="private" class="semi-button semi-button-secondary N1nTvZOT KDCUjpu2">设为私密</button><button type="button" id="confirm" class="semi-button semi-button-primary N1nTvZOT">确认删除</button></div>
          <script>window.confirmClicks=0;window.privateClicks=0;document.querySelector('#private').onclick=()=>window.privateClicks++;
          document.querySelector('#confirm').onclick=()=>{window.confirmClicks++;document.querySelectorAll('li').forEach(li=>{const id=li.querySelector('a').getAttribute('href').split('/').pop();if(['7709043480894524722','7708948487446056192'].includes(id))li.remove()});document.querySelector('#confirmation').remove();};</script>'''))
    render();folder=tmp_path/'confirm';folder.mkdir()
    def put(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return bridge.reference(path)
    auth=put(folder/'AUTH.json',dict(expected_public_uid='75891235130',delete_douyin_only_ids=TARGETS,protected_post_ids=PROTECTED))
    config=dict(authority=auth,tab_id='same-tab');request=dict(action=bridge.CONFIRM_ACTION,deletion_contract=contract_ref,selection_result=contract['selection_result'])
    reqref=put(folder/'REQUEST.json',request);pref=put(folder/'PLAN.json',{});plan=dict(state={},request=reqref)
    action=put(folder/'ACTION_CLAIM.json',dict(plan=pref,request=reqref,actor_thread_id=threading.get_ident()))
    monkeypatch.setattr(bridge,'_plan',lambda ref:(plan,config,request));monkeypatch.setattr(bridge,'validate_live',lambda *a:{})
    monkeypatch.setattr(bridge,'_load',lambda *a:adapter);monkeypatch.setattr(bridge,'FINAL_DELETE_CLAIM',folder/'GLOBAL_DELETE_CLAIM.json')
    actor=NS(owner_id='same-original-owner',generation=33);resource=NS();checkpoints=[]
    def checkpoint(stage,value):
        ref=put(folder/'inspection'/(stage.upper()+'.json'),value);checkpoints.append(ref);return ref
    def claim(ref):return bridge.claim_final_deletion(actor,resource,config,request,pref,action,ref)
    class Locator:
        def __init__(self,loc,selector):self.loc,self.selector=loc,selector
        def nth(self,index):return Locator(self.loc.nth(index),self.selector)
        def evaluate(self,js):return self.loc.evaluate(js)
        def click(self,**kw):
            assert self.selector==adapter.FINAL_CONFIRM and bridge.FINAL_DELETE_CLAIM.exists()
            self.loc.click(**kw);state.confirms=page.evaluate('()=>window.confirmClicks');state.private=page.evaluate('()=>window.privateClicks');state.deleted=True
            if lost_ack:raise RuntimeError('native click acknowledgement lost')
    class Original:
        _session=object();tab_id='same-tab'
        def evaluate(self,js):return page.evaluate(js)
        def locator(self,selector):return Locator(page.locator(selector),selector)
        def wait_for_timeout(self,ms):pass
        def goto(self,target,**kw):
            assert target==url and kw==dict(wait_until='commit',timeout=30000);state.reloads+=1;page.goto(target,**kw);render(state.deleted)
    result=adapter.confirm_exact_selection(Original(),guard=lambda:None,checkpoint=checkpoint,inventory_script=inspector.INVENTORY_JS,expected_uid='75891235130',delete_ids=TARGETS,protected_ids=PROTECTED,
        contract=contract,contract_ref=contract_ref,selection_result_ref=contract['selection_result'],claim_final_deletion=claim,final_claim_path=bridge.FINAL_DELETE_CLAIM)
    assert result['status']=='deletion_verified' and result['deleted'] and result['readonly_reload_count']==1
    assert result['final_ack_returned'] is (not lost_ack) and result['confirmation_scope']['native_role_modal_count']==0
    assert (state.confirms,state.private,state.reloads)==(1,0,1)
    final=page.evaluate(inspector.INVENTORY_JS);assert final['public_uids']==['75891235130'] and {x['native_post_id'] for x in final['cards']}==set(PROTECTED)
    with pytest.raises(FileExistsError):claim(result['preflight'])
    assert state.confirms==1 and not result['selection_performed']
    page.close()
