"""Observe exact alias row controls and open its native read-only 查看 once.

The caller owns the Page/session, identity guard and immutable checkpoint/once
intent. This module never uploads, submits, deletes, reads input values, or
claims that a platform supports appending another publication link.
"""
import json
import re
from urllib.parse import urlsplit


class DetailsControlsNotConfirmed(ValueError):
    pass


def _need(ok,reason):
    if not ok:raise DetailsControlsNotConfirmed(reason)


def _target(book_id,book_name,alias):
    _need(isinstance(book_id,str) and re.fullmatch(r'\d{10,24}',book_id),'exact_book_id_required')
    for text in (book_name,alias):
        _need(isinstance(text,str) and text==text.strip() and 0<len(text)<=200 and not any(ord(c)<32 for c in text),'exact_target_required')
    return dict(book_id=book_id,book_name=book_name,alias=alias)


_PUBLIC_DOM = r"""
 const allowed=()=>location.origin==='https://kol.fanqieopen.com';
 const visible=e=>{if(!e||!e.isConnected||e.getClientRects().length===0||e.closest('[hidden],[aria-hidden="true"]'))return false;
  for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||['hidden','collapse'].includes(s.visibility)||Number(s.opacity)===0)return false}return true};
 const text=e=>(e?.innerText||'').trim().replace(/\s+/g,' ');
 const publicUrl=href=>{try{const u=new URL(href,location.href);if(u.protocol!=='https:'||u.username||u.password)return null;
   return {origin:u.origin,path:u.pathname}}catch{return null}};
 const meta=e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',text:text(e).slice(0,500),
  class_name:(e.getAttribute('class')||'').slice(0,240),type:e instanceof HTMLButtonElement?e.type:(e.getAttribute('type')||''),
  disabled:e.matches(':disabled,[aria-disabled="true"]'),tabindex:e.getAttribute('tabindex'),
  cursor:getComputedStyle(e).cursor,pointer_events:getComputedStyle(e).pointerEvents,
  href:e.tagName==='A'?publicUrl(e.getAttribute('href')):null,target:e.tagName==='A'?(e.getAttribute('target')||''):null});
 const eligible=e=>{if(!visible(e)||text(e)!=='查看'||e.matches(':disabled,[aria-disabled="true"]')||getComputedStyle(e).pointerEvents==='none')return false;
   if(e.querySelector('button,a,input,select,textarea,[role="button"],[role="link"],[role="option"],[role="radio"],[role="checkbox"],[role="switch"]'))return false;
   if(e.tagName==='BUTTON')return e.type==='button';
   if(e.tagName==='A'){const href=e.getAttribute('href');if(!href||href.trim().startsWith('#'))return false;const u=publicUrl(href);return !!u&&u.origin===location.origin&&['','_self'].includes(e.getAttribute('target')||'')&&
     !/(?:delete|remove|upload|submit|apply)/i.test(u.path)}
   if(['button','link'].includes(e.getAttribute('role')||''))return !e.matches('input,select,textarea,label,[contenteditable="true"]');
   const roleless=(e.tagName==='DIV'&&e.classList.contains('link'))||
     (e.tagName==='SPAN'&&e.classList.contains('arco-link')&&getComputedStyle(e).pointerEvents==='auto');
   return roleless&&getComputedStyle(e).cursor==='pointer'&&
     ![...e.children].some(c=>visible(c)&&text(c));
 };
 const cellProjection=cell=>{if(!cell)return null;const all=[...cell.querySelectorAll('*')].filter(visible);
   return {text:text(cell).slice(0,1600),nodes:all.slice(0,60).map((e,index)=>({index,...meta(e)})),truncated:all.length>60}};
 const tableSnapshot=()=>{const tables=[...document.querySelectorAll('table')].filter(visible);const table=tables.length===1?tables[0]:null;
   const headers=table?[...table.querySelectorAll('thead th')].filter(visible).map(text):[];
   const rows=table?[...table.querySelectorAll('tbody tr')]:[];const status=headers.indexOf('发文详情'),ops=headers.indexOf('操作');
   const data=rows.map((row,index)=>{if(!visible(row))return {index,visible:false};const cells=[...row.children].filter(e=>e.tagName==='TD');const op=cells[ops];
     const controls=op?[...op.querySelectorAll('button,a,[role="button"],[role="link"],div.link,span.arco-link')]:[];
     return {index,visible:visible(row),cells:cells.map(text),book_names:[...row.querySelectorAll('[class*="book-name"]')].filter(visible).map(text),
       status_cell:cellProjection(cells[status]),operation_cell:cellProjection(op),view_controls:controls.map((e,control_index)=>visible(e)?({control_index,...meta(e),eligible:eligible(e)}):null).filter(Boolean)};});
   return {schema:'fanqie_filled_details_controls_rows/v2',location:{origin:location.origin,path:location.pathname},visible_tables:tables.length,
    headers,rows:data.filter(r=>r.visible).slice(0,200),all_table_rows:rows.length,truncated:data.filter(r=>r.visible).length>200,
    loading:[...document.querySelectorAll('.arco-spin-loading,.arco-spin-loading-layer,[aria-busy="true"]')].some(visible),input_values_read:false,hidden_state_read:false};};
"""

ROW_JS='() => {'+_PUBLIC_DOM+"if(!allowed())return {schema:'fanqie_filled_details_controls_rows/v2',location:{origin:location.origin,path:location.pathname},blocked:true};return tableSnapshot();}"

BODY_JS='() => {'+_PUBLIC_DOM+r"""
 if(!allowed())return {schema:'fanqie_filled_details_body/v2',location:{origin:location.origin,path:location.pathname},blocked:true};
 const cleanLine=value=>String(value).replace(/https?:\/\/[^\s<>"']+/g,s=>{const p=publicUrl(s);return p?p.origin+p.path:'[url omitted]'});
 const lines=[];let count=0,truncated=false,node;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while((node=walker.nextNode())){if(++count>20000){truncated=true;break}const parent=node.parentElement;
   if(!visible(parent)||parent.closest('script,style,input,textarea,[contenteditable="true"],[role="textbox"]'))continue;
   const value=node.nodeValue.trim();if(value){if(lines.length>=260){truncated=true;break}lines.push(cleanLine(value).slice(0,600));}}
 const all=[...document.querySelectorAll('button,a[href],input:not([type="hidden"]):not([type="password"]),select,textarea,[role="button"],[role="link"],[role="option"],[role="radio"],[role="checkbox"],[role="dialog"],[role="listbox"],div.link,span.arco-link')].filter(visible);
 const links=[];const add=(value,source,label)=>{const u=publicUrl(value);if(!u||!['https://www.douyin.com','https://douyin.com','https://v.douyin.com'].includes(u.origin))return;
   if(u.origin!=='https://v.douyin.com'&&!/^\/video\/\d+\/?$/.test(u.path))return;
   const item={...u,source,text:String(label||'').slice(0,300)};if(!links.some(x=>x.origin===u.origin&&x.path===u.path))links.push(item)};
 for(const e of [...document.querySelectorAll('a[href]')].filter(visible))add(e.getAttribute('href'),'visible_anchor',text(e));
 for(const line of lines)for(const match of line.matchAll(/https:\/\/[^\s<>"']+/g))add(match[0],'visible_text','');
 return {schema:'fanqie_filled_details_body/v2',location:{origin:location.origin,path:location.pathname},visible_text_lines:lines,
  controls:all.slice(0,120).map(meta),public_links:links.slice(0,100),truncated:truncated||all.length>120||links.length>100,
  input_values_read:false,hidden_state_read:false,append_capability_verified:false};
}"""


def _row(snapshot,target):
    _need(snapshot.get('schema')=='fanqie_filled_details_controls_rows/v2' and snapshot.get('location')=={'origin':'https://kol.fanqieopen.com','path':'/page/promotion-list'}
          and snapshot.get('visible_tables')==1 and snapshot.get('truncated') is False and snapshot.get('loading') is False,'promotion_table_not_ready')
    headers=snapshot['headers'];required=('关键词','书本信息','发文详情','操作')
    _need(all(headers.count(key)==1 for key in required),'promotion_headers_not_unique')
    columns={key:headers.index(key) for key in required};matches=[]
    for row in snapshot['rows']:
        cells=row['cells']
        if len(cells)!=len(headers) or cells[columns['关键词']]!=target['alias']:continue
        ids=re.findall(r'ID\s*[:：]?\s*(\d{10,24})(?!\d)',cells[columns['书本信息']],re.I)
        if ids!=[target['book_id']] or row['book_names']!=[target['book_name']]:continue
        filled=re.fullmatch(r'已填写\s*[（(]\s*(\d+)\s*条\s*[）)]',cells[columns['发文详情']])
        _need(filled is not None and int(filled.group(1))>0,'exact_filled_status_required')
        _need(not row['status_cell']['truncated'] and not row['operation_cell']['truncated'],'target_cell_projection_truncated')
        matches.append(dict(row=row,filled_count=int(filled.group(1)),operation_column=columns['操作']))
    _need(len(matches)==1,'exact_filled_alias_row_not_unique')
    return matches[0]


def inspect_filled_details_controls(page,*,book_id,book_name,alias,guard,checkpoint):
    """A single caller-authorized native 查看, or projection-only if unproven.

    `checkpoint('view_click_intent', ...)` is the caller's durable once boundary;
    it must reject any already-consumed intent. This function never retries a
    click whose acknowledgement is missing and never closes other UI.
    """
    target=_target(book_id,book_name,alias);original=getattr(page,'_session',None);tab=getattr(page,'tab_id',None)
    def check():
        guard();_need(getattr(page,'_session',None) is original and getattr(page,'tab_id',None)==tab,'caller_owned_page_changed')
    def rpc(function,*args,**kwargs):check();result=function(*args,**kwargs);check();return result
    def save(stage,evidence):check();checkpoint(stage,evidence);check()
    current=urlsplit(rpc(page._cmd,'current_url')['url'])
    _need(current.scheme=='https' and current.netloc=='kol.fanqieopen.com' and current.path=='/page/promotion-list','original_promotion_page_required')
    samples=[];prior_signature=None;stable=0
    for _ in range(16):
        observed=rpc(page.evaluate,ROW_JS);samples.append(observed)
        signature=json.dumps(observed,ensure_ascii=False,sort_keys=True);stable=stable+1 if signature==prior_signature else 1;prior_signature=signature
        if stable>=2 and observed.get('loading') is False and observed.get('visible_tables')==1:break
        rpc(page.wait_for_timeout,200)
    save('table_controls',dict(target=target,samples=samples));selected=_row(observed,target)
    save('exact_row_controls',dict(target=target,selected=selected))
    before=rpc(page.evaluate,BODY_JS);save('body_before',dict(target=target,observation=before))
    eligible=[c for c in selected['row']['view_controls'] if c.get('eligible') is True]
    if len(eligible)!=1:
        return dict(schema='fanqie_filled_details_controls_observation/v2',status='view_control_not_confirmed',target=target,
            row=selected,body_before=before,view_clicks=0,uploaded=False,submitted=False,deleted=False,append_capability_verified=False,old_ledger_changed=False)
    chosen=eligible[0];row=selected['row'];column=selected['operation_column']
    selector=':nth-match(table:visible tbody tr, '+str(row['index']+1)+') > td:nth-child('+str(column+1)+') >> button,a,[role="button"],[role="link"],div.link,span.arco-link'
    control=page.locator(selector).nth(chosen['control_index'])
    fresh=rpc(page.evaluate,ROW_JS);_need(_row(fresh,target)==selected,'target_row_changed_before_view')
    proof_script='el=>{'+_PUBLIC_DOM+'return {eligible:eligible(el),metadata:meta(el)};}'
    proof=rpc(control.evaluate,proof_script)
    _need(proof.get('eligible') is True and proof.get('metadata')=={k:v for k,v in chosen.items() if k not in {'control_index','eligible'}},'native_view_control_changed')
    save('view_click_intent',dict(target=target,selected=selected,control=chosen,proof=proof,native_read_click_limit=1,append_capability_verified=False))
    # Local durable checkpointing can take time; revalidate after it as well.
    _need(_row(rpc(page.evaluate,ROW_JS),target)==selected,'target_row_changed_at_view_boundary')
    _need(rpc(control.evaluate,proof_script)==proof,'native_view_control_changed_at_boundary')
    # Native RPC errors remain fatal/unknown in the original managed actor.
    # Ordinary missing controls or no visible transition have typed outcomes.
    rpc(control.click,timeout=8000)
    observations=[];baseline=json.dumps(before,ensure_ascii=False,sort_keys=True);changed=False;previous=None;stable=0
    for _ in range(20):
        body=rpc(page.evaluate,BODY_JS);_need(body.get('location',{}).get('origin')=='https://kol.fanqieopen.com','details_origin_changed')
        observations.append(body);signature=json.dumps(body,ensure_ascii=False,sort_keys=True)
        changed=signature!=baseline;stable=stable+1 if signature==previous else 1;previous=signature
        if changed and stable>=2:break
        rpc(page.wait_for_timeout,250)
    save('body_after',dict(target=target,observations=observations,native_view_clicks=1))
    return dict(schema='fanqie_filled_details_controls_observation/v2',status='visible_change_observed' if changed and stable>=2 else 'view_result_unconfirmed',
        target=target,row=selected,body_before=before,body_after=observations[-1],view_clicks=1,
        visible_change_observed=changed,details_contract_verified=False,uploaded=False,submitted=False,deleted=False,
        append_capability_verified=False,old_ledger_changed=False)
