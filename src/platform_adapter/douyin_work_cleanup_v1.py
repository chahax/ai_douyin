"""Read current native creator-card controls. Deletion is not implemented.

Full captions distinguish duplicate titles, but never substitute for a native
post ID. Only public canonical anchors or visible player identifiers bind IDs.
"""
import json
from urllib.parse import urlsplit


MANAGE='https://creator.douyin.com/creator-micro/content/manage'
INVENTORY_JS=r'''() => {
 const locationProof={origin:location.origin,path:location.pathname};
 const profile=location.origin==='https://www.douyin.com'&&location.pathname==='/user/self';
 const manage=location.origin==='https://creator.douyin.com'&&location.pathname==='/creator-micro/content/manage';
 if(!profile&&!manage)return {schema:'douyin_cleanup_card_inventory/v1',location:locationProof,ready:false,reason:'current_profile_or_manage_required',cards:[]};
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&!e.closest('[hidden],[aria-hidden="true"],[inert]')&&getComputedStyle(e).visibility!=='hidden';
 const text=e=>(e.innerText||'').trim();
 const publicId=raw=>{try{const u=new URL(raw,location.href);const m=u.pathname.match(/^\/video\/(\d{10,24})\/?$/);
   return u.protocol==='https:'&&!u.username&&!u.password&&['www.douyin.com','douyin.com'].includes(u.host)&&m?m[1]:null}catch{return null}};
 if(profile){
   const leaves=[...document.querySelectorAll('span,div,p')].filter(e=>visible(e)&&!e.children.length);
   const ids=[];for(const label of leaves.filter(e=>/^抖音号\s*[:：]?\s*(?:\d+)?$/.test(text(e)))){
     for(let p=label,d=0;p&&d<3;p=p.parentElement,d++){const s=text(p);if(s.length>240)break;
       const m=s.match(/抖音号\s*[:：]\s*(\d{5,30})(?!\d)/);if(m){ids.push(m[1]);break;}}}
   const anchors=[...document.querySelectorAll('a[href]')].filter(e=>visible(e)&&publicId(e.getAttribute('href')));
   const groups=[...new Set(anchors.map(e=>e.closest('li')).filter(e=>visible(e)&&e.querySelectorAll('*').length<=300))];
   const cards=groups.slice(0,30).map((li,index)=>{const a=anchors.filter(e=>li.contains(e));const native=[...new Set(a.map(e=>publicId(e.getAttribute('href'))))];
     const tags=[...li.querySelectorAll('*')].filter(e=>visible(e)&&!e.children.length&&text(e)==='流量减少');
     const raw=text(li);return {index,native_post_id:native.length===1?native[0]:null,native_id_bound:native.length===1,
       native_id_evidence:a.map(e=>({post_id:publicId(e.getAttribute('href')),source:'visible_native_anchor'})),
       status_text:tags.length===1?'流量减少':null,reduced_traffic_label_count:tags.length,caption_text:raw.slice(0,6000),caption_truncated:raw.length>6000,
       structural_card_bound:true,delete_controls:[],delete_allowed:false};});
   const batch=[...document.querySelectorAll('button,[role="button"],span,div')].filter(e=>visible(e)&&!e.children.length&&text(e)==='批量管理');
   return {schema:'douyin_cleanup_card_inventory/v1',location:locationProof,surface:'original_self_profile',ready:groups.length>0,
     visible_card_count:groups.length,cards,public_uids:[...new Set(ids)],batch_controls:batch.slice(0,5).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',text:text(e),class_name:(e.getAttribute('class')||'').slice(0,300),disabled:e.matches(':disabled,[aria-disabled="true"]')})),
     truncated:groups.length>30||batch.length>5,inputs_read:false,private_state_read:false,delete_allowed:false};
 }
 const all=[...document.querySelectorAll('.video-card-sfaSzz')].filter(visible);
 const blockers=[...document.querySelectorAll('div,span,p')].filter(e=>visible(e)&&!e.children.length&&['安全验证','请完成验证','请完成安全验证','登录后可查看','请先登录'].includes(text(e)));
 const cards=all.slice(0,30).map((wrapper,index)=>{
   const content=[...wrapper.querySelectorAll('.video-card-content-Xt386b')].filter(visible);const card=content.length===1?content[0]:null;
   const captions=card?[...card.querySelectorAll('[class*="info-title-text-"]')].filter(visible):[];
   const statuses=card?[...card.querySelectorAll('.info-status-QukAhD')].filter(visible):[];
   const dates=card?[...card.querySelectorAll('[class*="info-time-"]')].filter(visible):[];
   const leaves=card?[...card.querySelectorAll('div,span,button,a')].filter(e=>visible(e)&&!e.children.length):[];
   const nativeIds=[];if(card){for(const e of [...card.querySelectorAll('a[href]')].filter(visible)){const id=publicId(e.getAttribute('href'));if(id)nativeIds.push({post_id:id,source:'visible_native_anchor'});}
     for(const e of [...card.querySelectorAll('[data-e2e="player-container"]')].filter(visible))for(const c of e.classList){const m=c.match(/^video_(\d{10,24})$/);if(m)nativeIds.push({post_id:m[1],source:'visible_native_player_class'});}}
   const ids=[...new Set(nativeIds.map(x=>x.post_id))];
   const controls=leaves.filter(e=>text(e)==='删除作品').map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',class_name:(e.getAttribute('class')||'').slice(0,300),text:text(e),type:e.tagName==='BUTTON'?e.type:'',disabled:e.matches(':disabled,[aria-disabled="true"]'),cursor:getComputedStyle(e).cursor,pointer_events:getComputedStyle(e).pointerEvents}));
   return {index,content_count:content.length,caption_count:captions.length,caption_text:captions.length===1?text(captions[0]).slice(0,6000):null,
     caption_truncated:captions.some(e=>text(e).length>6000),status_count:statuses.length,status_text:statuses.length===1?text(statuses[0]).slice(0,100):null,
     native_dates:dates.slice(0,3).map(e=>text(e).slice(0,100)),native_id_evidence:nativeIds,native_post_id:ids.length===1?ids[0]:null,native_id_bound:ids.length===1,
     delete_controls:controls,operation_labels:leaves.map(text).filter(t=>['编辑作品','设置权限','作品置顶','删除作品'].includes(t)),
     structural_card_bound:content.length===1&&wrapper.querySelectorAll('*').length<=200,delete_allowed:false};});
 return {schema:'douyin_cleanup_card_inventory/v1',location:locationProof,ready:all.length>0&&blockers.length===0,visible_card_count:all.length,cards,
   human_required:blockers.length>0,challenge_markers:blockers.map(text),truncated:all.length>30,inputs_read:false,private_state_read:false,delete_allowed:false};
}'''


def inspect_cards(page,*,guard,checkpoint):
    """Current original Page only. No navigation or clicks."""
    original,tab=getattr(page,'_session',None),getattr(page,'tab_id',None)
    def rpc(method,*args,**kw):
        guard()
        if getattr(page,'_session',None) is not original or getattr(page,'tab_id',None)!=tab:raise ValueError('cleanup_original_page_changed')
        value=method(*args,**kw);guard();return value
    current=rpc(page._cmd,'current_url')['url'];u=urlsplit(current)
    if u.scheme!='https' or u.hostname not in {'www.douyin.com','douyin.com','creator.douyin.com'}:raise ValueError('cleanup_original_origin_unconfirmed')
    samples=[];signature=None;stable=0
    for _ in range(8):
        value=rpc(page.evaluate,INVENTORY_JS);samples.append(value)
        current=json.dumps(value,sort_keys=True,ensure_ascii=False);stable=stable+1 if current==signature else 1;signature=current
        if value.get('human_required') or value.get('ready') and stable>=2:break
        rpc(page.wait_for_timeout,350)
    checkpoint('native_card_samples',dict(samples=samples))
    return dict(schema='manual_work_cleanup_inventory/v1',status='cards_observed' if value.get('ready') and stable>=2 else 'cards_not_confirmed',
        inventory=value,stable=stable>=2,navigation_performed=False,navigations_count=0,api_request_count=0,
        native_public_uid_independently_observed=value.get('surface')=='original_self_profile' and len(value.get('public_uids',[]))==1,input_performed=False,delete_entry_clicked=False,deletion_confirmed=False,submitted=False,
        file_selected=False,published=False,delete_allowed=False)
