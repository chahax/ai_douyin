"""Two narrow protocol/real DOM cases. No live account or platform actions."""
import ast
import json
import os
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace as NS

import psutil
import pytest
from test_fanqie_backfill_editor_inspection_v1 import context
from src.operations_accounts import manual_work_cleanup_runtime_v1 as bridge
from src.operations_accounts import manual_republication_flow_v1 as reader
from src.operations_accounts.browser_control import BrowserControlStore,BrowserControlActor
from src.platform_adapter import douyin_work_cleanup_v1 as adapter


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return bridge.reference(path)


def test_real_current_profile_native_ids_tags_duplicate_titles_protected_without_effects(context):
    page=context.new_page();page.goto('https://www.douyin.com/user/self?from_tab_name=main')
    page.set_content('''<div><span>抖音号：</span><span>75891235130</span></div><button>批量管理</button><ul>
      <li><a href="/video/7709219071845256488">一袋面包，看清这个家｜两分钟完整版</a></li>
      <li><a href="/video/7709043480894524722">一袋面包，看清这个家｜两分钟完整版</a><span>流量减少</span></li>
      <li><a href="/video/7708948487446056192">弟弟说出面包的来历，哥哥攥紧了拳头</a><span>流量减少</span></li>
      <li><a href="/video/7700201288079920427">渡口的单程票</a></li></ul><input type="password" value="secret">
      <script>window.clicks=0;document.addEventListener('click',()=>window.clicks++);Object.defineProperty(document.querySelector('input'),'value',{get(){throw Error('private read')}})</script>''')
    calls=[];stages=[]
    class Page:
        _session=object();tab_id='original-tab'
        def _cmd(self,kind):calls.append(kind);assert kind=='current_url';return {'url':page.url}
        def evaluate(self,script):calls.append('evaluate');return page.evaluate(script)
        def wait_for_timeout(self,ms):calls.append('wait_for_timeout')
    value=adapter.inspect_cards(Page(),guard=lambda:None,checkpoint=lambda stage,value:stages.append((stage,value)))
    ids={c['native_post_id']:c for c in value['inventory']['cards']}
    assert value['status']=='cards_observed' and value['inventory']['public_uids']==['75891235130']
    assert set(ids)==bridge.DELETE_CANDIDATES|bridge.PROTECTED
    assert all(ids[i]['status_text']=='流量减少' for i in bridge.DELETE_CANDIDATES)
    assert all(ids[i]['status_text'] is None for i in bridge.PROTECTED)
    assert all(c['native_id_bound'] and not c['delete_allowed'] for c in ids.values())
    assert value['navigations_count']==value['api_request_count']==0 and not value['delete_entry_clicked'] and not value['deletion_confirmed']
    assert set(calls)<={'current_url','evaluate','wait_for_timeout'} and page.evaluate('()=>window.clicks')==0
    page.close()


def test_original_private_owner_guard_once_and_cached_bootstrap_unchanged(tmp_path,monkeypatch):
    run=tmp_path/'data/cleanup';run.mkdir(parents=True)
    monkeypatch.setattr(bridge,'RUN',run);monkeypatch.setattr(bridge,'ARM',run/'ARM.json')
    host=tmp_path/'host.py';host.write_text('# original host fixture')
    stub=tmp_path/'adapter.py';stub.write_text('''def inspect_cards(page,*,guard,checkpoint):
 guard();checkpoint('native_card_samples',{'same_original_page':True});guard()
 return dict(schema='manual_work_cleanup_inventory/v1',inventory={'cards':[],'public_uids':['75891235130']},navigations_count=0,api_request_count=0,input_performed=False,delete_entry_clicked=False,deletion_confirmed=False,submitted=False,file_selected=False,published=False,delete_allowed=False)
''')
    paths=dict(bridge.SOURCE_PATHS,host=host,adapter=stub);monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
    account='account:private';owner='backend:'+str(os.getpid())+':private';binding=NS(account_uuid=account,account_key='private',platform_identity_key='public_uid:75891235130',browser_environment_key='original',browser_profile_dir='private',storage_state_path='unused',confirmed_by='user',created_at='bound',public_uid='75891235130');profile=NS(account_uuid=account,profile_version=1)
    version=reader._binding_version(NS(binding=binding,profile=profile));store=BrowserControlStore(tmp_path/'data/browser.db');gen=store.acquire_owner(account,version,owner)['generation']
    command=store.submit(account,version,'manual','original-manual',dict(account_key='private',account_uuid=account),200);tab='same-original-tab'
    with store._db(write=True) as db:db.execute("update browser_control_commands set state='waiting_human',owner_id=?,generation=?,result=? where command_id=?",(owner,gen,json.dumps({'tab_id':tab}),command['command_id']))
    control=tmp_path/'data/control.db'
    with sqlite3.connect(control) as db:db.execute('create table account_controls(account_uuid text,state text,revision integer)');db.execute('insert into account_controls values(?,?,?)',(account,'paused',59))
    auth=put(run/'USER_AUTHORIZATION.json',dict(schema='explicit_platform_cleanup_rebind_authorization/v1',user_statement='delete only limited old works',account_key='private',account_uuid=account,expected_public_uid='75891235130',delete_douyin_only_ids=sorted(bridge.DELETE_CANDIDATES),protected_post_ids=sorted(bridge.PROTECTED),requires_current_native_reduced_traffic_label=True,new_publication_allowed=False,old_unknowns_and_claims_unchanged=True,models_and_media_calls_allowed=False))
    cfg=dict(schema=bridge.CONFIG_SCHEMA,backend_pid=os.getpid(),backend_create_time=psutil.Process().create_time(),account_key='private',account_id=account,owner_id=owner,generation=gen,binding_version=version,browser_db=str(store.path),control_db=str(control),control_snapshot={'state':'paused','revision':59},manual_command_id=command['command_id'],manual_request_sha256=command['request_sha'],tab_id=tab,authority=auth,sources={k:bridge.reference(p) for k,p in paths.items()})
    monkeypatch.setattr(bridge,'PINNED_SCOPE',{k:cfg[k] for k in bridge.PINNED_SCOPE});cref=put(run/'CONFIG.json',cfg);rref=put(run/'REQUEST.json',dict(schema='manual_work_cleanup_request/v1',config=cref,action=bridge.ACTION))
    actor=BrowserControlActor(store,account,version,owner,{});actor.generation=gen;actor._thread_id=threading.get_ident();calls=[]
    session=NS(config=NS(headless=False),_proc=NS(poll=lambda:None),worker_failure=lambda:'')
    page=NS(_session=session,tab_id=tab);session.get_page=lambda selected:(calls.append(selected) or page)
    resource=NS(account_uuid=account,manual_tasks={command['command_id']:tab},console_tasks={},session=session,runtime=NS(bindings=NS(get=lambda _:binding),profiles=NS(get=lambda _:profile)))
    plan=bridge.prepare(cref,rref,run/'inspect_001');arm=put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=plan));before=store.get(command['command_id'])
    resource.manual_tasks[command['command_id']]='wrong-tab'
    with pytest.raises(ValueError):bridge._perform(actor,resource,plan,arm)
    assert not calls and not (run/'inspect_001/ACTION_CLAIM.json').exists()
    resource.manual_tasks[command['command_id']]=tab
    assert bridge._perform(actor,resource,plan,arm)['status']=='inventory_completed'
    assert bridge._perform(actor,resource,plan,arm)['status']=='inventory_completed' and calls==[tab]
    assert store.get(command['command_id'])==before and resource.manual_tasks=={command['command_id']:tab}
    # The cached entry's byte/AST body is untouched; only install_if_armed has
    # the explicit new-plan route. No cached callable can silently old-load.
    source=bridge.ROOT/'src/operations_accounts/manual_republication_runtime_v10.py'
    old=bridge.ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1/bootstrap_before/manual_republication_runtime_v10.py'
    def node(path):return next(n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='install_fresh_if_armed')
    assert ast.dump(node(source),include_attributes=False)==ast.dump(node(old),include_attributes=False)
