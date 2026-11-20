"""Observed four-input Arco form; real local Chrome, no external requests."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_fanqie_backfill_editor_inspection_v1 import context
from src.platform_adapter import fanqie_new_post_backfill_v1 as flow
from src.platform_adapter.browser_session import Page


OLD='https://www.douyin.com/video/7709043480894524722'
NEW='https://www.douyin.com/video/7709219071845256488'
TARGET=dict(book_id='7302660145530539062',book_name='你敢惹我？我有六个反派儿子',alias='从旧饭桌开始改命')


@pytest.fixture
def sample(context,tmp_path):
    n=context.new_page();n.goto('https://kol.fanqieopen.com/page/promotion-list')
    n.set_content('''<input id="private" value="never-read"><input type="password" value="secret">
    <table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th><th>别名状态</th><th>书籍状态</th><th>发文详情</th><th>操作</th></tr></thead>
    <tbody><tr><td>从旧饭桌开始改命</td><td><span class="book-name">你敢惹我？我有六个反派儿子</span> id: 7302660145530539062</td><td>AIGC</td><td>生效中</td><td>可用</td>
    <td id="filled">已填写（1条）</td><td><span class="arco-link" id="view" style="cursor:pointer;pointer-events:auto">查看</span><span class="arco-link" id="delete" style="cursor:pointer">删除</span></td></tr></tbody></table>
    <div class="arco-drawer" id="drawer" hidden></div>
    <script>
    window.submits=0;window.deletes=0;window.adds=0;window.views=0;window.openers=0;window.badDate=false;
    window.rows=[{url:'https://www.douyin.com/video/7709043480894524722',day:'2026.11.17'}];
    Object.defineProperty(document.querySelector('#private'),'value',{get(){throw Error('private read')}});
    document.querySelector('#delete').onclick=()=>window.deletes++;
    function details(){window.views++;drawer.hidden=false;drawer.innerHTML='<div class="arco-drawer-scroll"><h2>推广计划</h2><h3>基础信息</h3><p>书名 你敢惹我？我有六个反派儿子</p><p>别名 从旧饭桌开始改命</p><p>发文类型 AIGC</p><h3>抖音发文</h3>'+
      window.rows.map((r,i)=>'<div><p>发文 '+(i+1)+'</p><p>发文时间 '+r.day+'</p><p>发文链接 '+r.url+'</p></div>').join('')+
      '<h3>其他平台发文</h3><p>-</p><button type="button" id="close">关闭</button><button type="button" id="open">回填发文</button></div>';
      document.querySelector('#close').onclick=()=>drawer.hidden=true;document.querySelector('#open').onclick=editor;}
    function editor(){window.openers++;drawer.innerHTML='<h2>回填发文</h2><h3>基础信息</h3><p>书名 你敢惹我？我有六个反派儿子</p><p>别名 从旧饭桌开始改命</p><p>发文类型 AIGC</p><section><h3>抖音发文</h3><div class="entry"><div class="picker"><input id="date" class="arco-picker-start-time" placeholder="选择发文日期"></div><div class="url"><input id="link" class="arco-input arco-input-size-large" placeholder="输入抖音发文链接,https://开头"></div><button type="button" class="remove">删除</button></div><button type="button" class="add">添加发文</button></section>'+
      '<section><h3>其他平台发文</h3><div class="entry"><div class="picker"><input class="arco-picker-start-time" placeholder="选择发文日期"></div><div class="url"><input placeholder="输入发文链接"></div><button type="button" class="remove">删除</button></div><button type="button" class="add">添加发文</button></section><button type="button">取消</button><button type="button" id="submit">提交</button>';
      document.querySelectorAll('.remove').forEach(e=>e.onclick=()=>window.deletes++);document.querySelectorAll('.add').forEach(e=>e.onclick=()=>window.adds++);
      document.querySelector('#date').onkeydown=e=>{if(e.key==='Enter'&&window.badDate)e.target.value='2026-11-17'};
      document.querySelector('#submit').onclick=()=>{window.submits++;window.rows.push({url:document.querySelector('#link').value,day:document.querySelector('#date').value.replaceAll('-','.')});drawer.hidden=true;filled.textContent='已填写（2条）';};}
    document.querySelector('#view').onclick=details;
    </script>''')
    request=dict(schema='fanqie_new_publication_backfill_request/v1',draft_only=False,native_mode='create_new_post_in_blank_backfill_form',new_backfill_limit=1,
        preserve_existing_records=True,no_delete_or_replace_actions=True,**TARGET,retained_publication=dict(canonical_url=OLD,publish_date='2026-11-17'),
        new_publication=dict(post_id='7709219071845256488',canonical_url=NEW,publish_date='2026-11-18',native_created_epoch=1794942450),
        resource_id='private-resource',binding_version='bound',environment_key='same-env',platform_identity_key='uid:2521598930983028',submit_claim_path=str(tmp_path/'GLOBAL_SUBMIT_CLAIM.json'))
    subject=dict(resource_id=request['resource_id'],binding_version='bound',environment_key='same-env',platform_identity_key=request['platform_identity_key'],owner_id='same-owner',generation=66,task_id='same-cid')
    reqpath=tmp_path/'REQUEST.json';reqpath.write_text(json.dumps(request,ensure_ascii=False),encoding='utf8');reqref=flow.reference(reqpath)
    commands=[];state=NS(lost_ack=False)
    class Owner:
        def cmd(self,kind,**kw):
            assert kw.pop('tab_id')=='same-tab';commands.append((kind,dict(kw)))
            sel=kw.get('selector');index=kw.get('index',-1);loc=n.locator(sel).nth(index) if sel and index>=0 else n.locator(sel) if sel else None
            if kind=='current_url':return {'url':n.url}
            if kind=='evaluate':return {'value':loc.evaluate(kw['js']) if sel else n.evaluate(kw['js'])}
            if kind=='locator_count':return {'count':loc.count()}
            if kind=='click':
                loc.click(timeout=kw.get('timeout',8000))
                if state.lost_ack and sel==flow.SUBMIT:raise RuntimeError('lost submit acknowledgement')
                return {}
            if kind=='fill':loc.fill(kw['value']);return {}
            if kind=='press':loc.press(kw['key']);return {}
            if kind=='wait_for_timeout':return {}
            if kind=='screenshot':n.screenshot(path=kw['path'],full_page=False);return {}
            raise AssertionError('forbidden RPC '+kind)
    owner=Owner();page=Page(owner,'same-tab');claims=[]
    def claim(ref):
        proof=json.loads(Path(ref['path']).read_text(encoding='utf8'));assert proof['subject']==subject and proof['request']==reqref
        assert proof['retained_records']==[request['retained_publication']] and proof['new_publication']==request['new_publication']
        assert proof['actual_form']['date']['value']=='2026-11-18' and proof['actual_form']['link']['value']==NEW
        assert all(i['value']=='' for i in proof['actual_form']['other_inputs'])
        path=tmp_path/'GLOBAL_SUBMIT_CLAIM.json'
        with path.open('x',encoding='utf8') as f:json.dump({'schema':'fanqie_new_backfill_submit_claim/v1','preflight':ref,'request':reqref,'subject':subject},f)
        claims.append(flow.reference(path));return claims[-1]
    yield NS(native=n,page=page,request=request,ref=reqref,subject=subject,out=tmp_path/'evidence',claim=claim,claims=claims,commands=commands,state=state)
    n.close()


def run(x):return flow.run_action(x.page,request=x.request,request_ref=x.ref,subject=x.subject,guard=lambda:None,evidence_directory=x.out,claim_submission=x.claim)


def test_observed_blank_form_new_link_keeps_old_and_confirms_native_both_records(sample):
    x=sample;r=run(x)
    assert r['status']=='confirmed' and r['submitted'] and r['submit_ack_returned'] and r['submit_click_count']==1
    assert x.native.evaluate('()=>[window.submits,window.openers,window.views,window.adds,window.deletes]')==[1,1,2,0,0]
    assert r['records']==[x.request['retained_publication'],dict(canonical_url=NEW,publish_date='2026-11-18')]
    assert len(x.claims)==1 and len([1 for a,k in x.commands if a=='click' and k['selector']==flow.SUBMIT])==1
    assert not any(a in {'set_input_files','goto','api_request','new_tab'} for a,_ in x.commands)
    encoded=json.dumps(r,ensure_ascii=False);assert 'never-read' not in encoded and 'secret' not in encoded


def test_lost_submit_ack_uses_only_native_readback_and_never_clicks_again(sample):
    x=sample;x.state.lost_ack=True;r=run(x)
    assert r['status']=='confirmed' and not r['submit_ack_returned'] and r['submit_error_type']=='RuntimeError'
    assert x.native.evaluate('()=>window.submits')==1 and len(x.claims)==1
    actions=[(a,k) for a,k in x.commands];position=next(i for i,(a,k) in enumerate(actions) if a=='click' and k['selector']==flow.SUBMIT)
    assert not any(a in {'fill','press'} or a=='click' and k['selector']==flow.SUBMIT for a,k in actions[position+1:])


def test_wrong_native_date_commit_blocks_before_global_claim_or_submit(sample):
    x=sample;x.native.evaluate('()=>window.badDate=true');r=run(x)
    assert r['status']=='not_submitted' and r['reason']=='date_commit_unconfirmed' and not r['submitted']
    assert not x.claims and x.native.evaluate('()=>[window.submits,window.adds,window.deletes]')==[0,0,0]
    assert x.native.locator('#link').input_value()==''
