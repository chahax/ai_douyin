"""One new publication in the observed blank Fanqie form, preserving old rows.

The caller supplies the original Page, fresh owner/identity guard and durable
global submit claim callback. This adapter never navigates, uploads, adds or
deletes a row. A lost submit acknowledgement only permits read-only observation.
"""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import time

from .fanqie_backfill_editor_inspection_v1 import inspect_backfill_editor,opener_script,BackfillEditorNotConfirmed
from .fanqie_filled_details_controls_v2 import _PUBLIC_DOM,_target,inspect_filled_details_controls,DetailsControlsNotConfirmed


LINK_PLACEHOLDER='输入抖音发文链接,https://开头'
DRAWER='.arco-drawer:visible'
LINK=DRAWER+' input[placeholder="'+LINK_PLACEHOLDER+'"]:visible'
DATE=LINK+' >> xpath=ancestor::*[count(.//input[@placeholder="选择发文日期"])=1][1] >> input[placeholder="选择发文日期"]:visible'
SUBMIT=DRAWER+' button:visible >> xpath=self::*[normalize-space(.)="提交"]'


class NewPostBackfillNotConfirmed(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def need(ok,code):
    if not ok:raise NewPostBackfillNotConfirmed(code)


def reference(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _once(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
    return reference(path)


def _records(opener):
    need(opener.get('eligible') is True and opener.get('retained_link_observed') is True,'retained_details_not_confirmed')
    content=opener.get('scope',{}).get('visible_text','')
    need(isinstance(content,str) and 0<len(content)<12000,'retained_details_truncated')
    pairs=re.findall(r'发文时间\s+(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s+发文链接\s+(https://(?:www\.)?douyin\.com/video/\d{10,24})(?!\d)',content)
    need(len(pairs)>0 and content.count('发文时间')==len(pairs),'retained_date_link_pairing_unconfirmed')
    records=[]
    for raw_date,url in pairs:
        y,m,d=map(int,re.split(r'[-./]',raw_date))
        try:canonical=date(y,m,d).isoformat()
        except ValueError:raise NewPostBackfillNotConfirmed('retained_date_invalid') from None
        records.append(dict(canonical_url=url,publish_date=canonical))
    need(len({(r['canonical_url'],r['publish_date']) for r in records})==len(records),'retained_records_ambiguous')
    return records


def form_script(target,element=None):
    tail=r'''
 const target=TARGET;
 if(!allowed()||location.pathname!=='/page/promotion-list')return {schema:'fanqie_new_post_form/v1',eligible:false,reason:'location'};
 const candidates=[...document.querySelectorAll('.arco-drawer')].filter(e=>visible(e)&&text(e).includes(target.book_name)&&text(e).includes(target.alias)&&text(e).includes('AIGC'));
 const minimal=candidates.filter(e=>!candidates.some(o=>o!==e&&e.contains(o))),scope=minimal.length===1?minimal[0]:null;
 const inputs=scope?[...scope.querySelectorAll('input:not([type="hidden"]):not([type="password"])')].filter(visible):[];
 const links=inputs.filter(e=>e.getAttribute('placeholder')==='输入抖音发文链接,https://开头'),link=links.length===1?links[0]:null;
 let row=null,dates=[];
 if(link)for(let p=link.parentElement,d=0;p&&p!==scope&&d<12;p=p.parentElement,d++){
   const found=[...p.querySelectorAll('input:not([type="hidden"]):not([type="password"])')].filter(visible);
   const ds=found.filter(e=>e.getAttribute('placeholder')==='选择发文日期'&&e.classList.contains('arco-picker-start-time'));
   if(found.length===2&&found.includes(link)&&ds.length===1){row=p;dates=ds;break;}}
 const day=dates.length===1?dates[0]:null;
 const others=inputs.filter(e=>e!==link&&e!==day);
 const submit=scope?[...scope.querySelectorAll('button')].filter(e=>visible(e)&&text(e)==='提交'):[];
 const button=submit.length===1?submit[0]:null;
 const active=e=>!!e&&!e.disabled&&!e.readOnly&&getComputedStyle(e).pointerEvents!=='none';
 const safe=e=>{const raw=String(e.value||'');const u=publicUrl(raw);
   if(raw===''||/^\d{4}[-./]\d{1,2}[-./]\d{1,2}$/.test(raw))return raw;
   if(u&&['https://www.douyin.com','https://douyin.com'].includes(u.origin)&&/^\/video\/\d{10,24}$/.test(u.path))return u.origin+u.path;
   return null;};
 const identity=scope?{book_name:target.book_name,alias:target.alias,aigc:text(scope).includes('AIGC')}:null;
 const valid=!!scope&&inputs.length===4&&links.length===1&&!!row&&active(link)&&active(day)&&others.length===2
   &&others.filter(e=>e.getAttribute('placeholder')==='选择发文日期').length===1&&others.filter(e=>e.getAttribute('placeholder')==='输入发文链接').length===1;
 const value={schema:'fanqie_new_post_form/v1',location:{origin:location.origin,path:location.pathname},scope_count:minimal.length,
   identity,input_count:inputs.length,link_count:links.length,row_date_count:dates.length,row_input_count:row?2:0,
   eligible:valid,date:day?{value:safe(day),placeholder:day.getAttribute('placeholder'),disabled:day.disabled,read_only:day.readOnly}:null,
   link:link?{value:safe(link),placeholder:link.getAttribute('placeholder'),disabled:link.disabled,read_only:link.readOnly}:null,
   other_inputs:others.map(e=>({placeholder:e.getAttribute('placeholder')||'',value:safe(e)})),
   submit:{unique_count:submit.length,tag:button?'button':null,type:button?.type||null,text:button?text(button):null,enabled:!!button&&!button.disabled&&button.getAttribute('aria-disabled')!=='true'&&getComputedStyle(button).pointerEvents!=='none'},
   add_delete_actions_performed:false,private_values_returned:false};
 RETURN
 '''.replace('TARGET',json.dumps(target,ensure_ascii=False))
    if element is None:return '() => {'+_PUBLIC_DOM+tail.replace('RETURN','return value;')+'}'
    expression={'date':'day','link':'link','submit':'button'}[element]
    return 'el => {'+_PUBLIC_DOM+tail.replace('RETURN','return {same_element:el==='+expression+',form:value};')+'}'


def _valid_form(value,target,expected_date,expected_link,*,blank=False):
    need(value.get('eligible') is True and value.get('scope_count')==1 and value.get('input_count')==4
         and value.get('identity')==dict(book_name=target['book_name'],alias=target['alias'],aigc=True),'new_form_identity_unconfirmed')
    need(value.get('date',{}).get('value')==('' if blank else expected_date)
         and value.get('link',{}).get('value')==('' if blank else expected_link),'new_form_readback_mismatch')
    need(len(value.get('other_inputs',[]))==2 and all(i.get('value')=='' for i in value['other_inputs']),'other_platform_fields_not_empty')
    button=value.get('submit',{})
    need(button==dict(unique_count=1,tag='button',type='button',text='提交',enabled=True),'native_submit_not_confirmed')


def run_action(page,*,request,request_ref,subject,guard,evidence_directory,claim_submission):
    """Caller validated request, same original Page and late claim callback."""
    need(request.get('schema')=='fanqie_new_publication_backfill_request/v1' and request.get('draft_only') is False
         and request.get('native_mode')=='create_new_post_in_blank_backfill_form' and type(request.get('new_backfill_limit')) is int and request['new_backfill_limit']==1
         and request.get('preserve_existing_records') is True and request.get('no_delete_or_replace_actions') is True,'request_invalid')
    target=_target(request['book_id'],request['book_name'],request['alias']);old=request['retained_publication'];new=request['new_publication']
    need(reference(request_ref['path'])==request_ref and json.loads(Path(request_ref['path']).read_text(encoding='utf8'))==request,'request_ref_changed')
    need(set(subject)=={'resource_id','binding_version','environment_key','platform_identity_key','owner_id','generation','task_id'}
         and all(subject.get(k)==request[k] for k in ('resource_id','binding_version','environment_key','platform_identity_key'))
         and isinstance(subject.get('owner_id'),str) and subject['owner_id'] and type(subject.get('generation')) is int
         and isinstance(subject.get('task_id'),str) and subject['task_id'],'managed_subject_changed')
    need(re.fullmatch(r'https://www\.douyin\.com/video/\d{10,24}',new['canonical_url']) and new['canonical_url'].endswith('/'+new['post_id'])
         and old['canonical_url']!=new['canonical_url'] and date.fromisoformat(new['publish_date']).isoformat()==new['publish_date'],'new_publication_invalid')
    folder=Path(evidence_directory).resolve();folder.mkdir(parents=True,exist_ok=True)
    _once(folder/'ACTION_STARTED.json',dict(schema='fanqie_new_post_backfill_action/v1',request_sha256=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),at_epoch=time.time()))
    original,tab=getattr(page,'_session',None),getattr(page,'tab_id',None)
    checkpoints=[];baseline=[];table_snapshot={};submission_claim=None;claim_requested=False;dispatched=False;ack=False;submit_error=None;deadline=time.monotonic()+300
    def check():
        need(time.monotonic()<deadline,'bounded_deadline_reached');guard()
        need(reference(request_ref['path'])==request_ref,'request_ref_changed')
        need(getattr(page,'_session',None) is original and getattr(page,'tab_id',None)==tab,'original_page_changed')
    def rpc(method,*args,**kwargs):check();value=method(*args,**kwargs);check();return value
    def save(stage,value):
        check();ref=_once(folder/(stage.upper()+'.json'),value);checkpoints.append(ref);return ref
    def checkpoint(stage,value):
        if stage=='table_controls':table_snapshot.update(value['samples'][-1])
        if stage=='exact_row_controls':
            headers=table_snapshot.get('headers',[]);cells=value['selected']['row']['cells']
            need(all(headers.count(k)==1 for k in ('发文类型','别名状态','书籍状态'))
                 and all(cells[headers.index(k)]==v for k,v in (('发文类型','AIGC'),('别名状态','生效中'),('书籍状态','可用'))),'active_aigc_row_required')
        if stage=='editor_opener_before':
            baseline[:]=_records(value)
            need(old in baseline and new['canonical_url'] not in [r['canonical_url'] for r in baseline],'retained_records_changed')
        return save('before_'+stage,value)
    def result(status,reason,**extra):
        value=dict(schema='fanqie_new_post_backfill/v1',status=status,reason=reason,target=target,
            retained_records=baseline,new_publication=new,submitted=dispatched,submit_click_dispatched=dispatched,submit_ack_returned=ack,submit_error_type=submit_error,
            submission_claim=submission_claim,submission_claim_requested=claim_requested,submit_click_count=int(dispatched),uploaded=False,added=False,deleted=False,replaced=False,automatic_retry=False,old_ledger_changed=False,
            checkpoint_refs=list(checkpoints),**extra)
        _once(folder/'RESULT.json',value);return value
    try:
        editor=inspect_backfill_editor(page,**target,retained_url=old['canonical_url'],guard=check,checkpoint=checkpoint)
        save('before_editor_receipt',editor)
        need(editor.get('status')=='editor_controls_observed' and editor.get('stable') is True and baseline,'blank_editor_not_confirmed')
        initial=rpc(page.evaluate,form_script(target));save('blank_form',initial);_valid_form(initial,target,new['publish_date'],new['canonical_url'],blank=True)
        _once(folder/'FORM_ENTRY_INTENT.json',dict(date=new['publish_date'],canonical_url=new['canonical_url'],fields_allowed=2,add_delete_actions_allowed=0))
        day=page.locator(DATE);link=page.locator(LINK)
        proof=rpc(day.evaluate,form_script(target,'date'));need(proof.get('same_element') is True,'date_element_not_confirmed');_valid_form(proof['form'],target,new['publish_date'],new['canonical_url'],blank=True)
        rpc(day.fill,new['publish_date']);rpc(day.press,'Enter')
        proof=rpc(link.evaluate,form_script(target,'link'));need(proof.get('same_element') is True and proof['form'].get('date',{}).get('value')==new['publish_date']
             and proof['form'].get('link',{}).get('value')=='','date_commit_unconfirmed')
        rpc(link.fill,new['canonical_url'])
        samples=[];stable=0;previous=None
        for _ in range(8):
            form=rpc(page.evaluate,form_script(target));samples.append(form)
            signature=json.dumps(form,sort_keys=True,ensure_ascii=False);stable=stable+1 if signature==previous else 1;previous=signature
            if stable>=2:break
            rpc(page.wait_for_timeout,150)
        form_ref=save('filled_form',dict(samples=samples));_valid_form(form,target,new['publish_date'],new['canonical_url']);need(stable>=2,'form_not_stable')
        button=page.locator(SUBMIT);fresh=rpc(button.evaluate,form_script(target,'submit'))
        need(fresh.get('same_element') is True,'submit_element_not_confirmed');_valid_form(fresh['form'],target,new['publish_date'],new['canonical_url'])
        preflight=save('submit_preflight',dict(schema='fanqie_new_post_backfill_preflight/v1',request=request_ref,subject=subject,target=target,retained_records=baseline,new_publication=new,
            form=form_ref,actual_form=fresh['form'],observed_at=time.time(),submission_limit=1,no_add_delete_actions=True))
        check();claim_requested=True;submission_claim=claim_submission(preflight);check()
        need(isinstance(submission_claim,dict) and set(submission_claim)=={'path','sha256'}
             and Path(submission_claim['path']).resolve()==Path(request['submit_claim_path']).resolve()
             and reference(submission_claim['path'])==submission_claim,'submission_claim_not_confirmed')
        claimed=json.loads(Path(submission_claim['path']).read_text(encoding='utf8'))
        need(claimed.get('schema')=='fanqie_new_backfill_submit_claim/v1' and claimed.get('preflight')==preflight
             and claimed.get('request')==request_ref and claimed.get('subject')==subject,'submission_claim_not_bound')
        _once(folder/'SUBMIT_CLICK_INTENT.json',dict(submission_claim=submission_claim,preflight=preflight,click_limit=1))
        # Claim and durable click-intent precede this single native click. Never
        # retry if the acknowledgement is lost; only read the current UI below.
        check()
        dispatched=True
        try:button.click(timeout=8000);ack=True;check()
        except Exception as error:submit_error=type(error).__name__
        after=[];closed=False
        for _ in range(12):
            state=rpc(page.evaluate,form_script(target));after.append(state)
            if state.get('scope_count')==0 or state.get('input_count')==0:closed=True;break
            rpc(page.wait_for_timeout,250)
        save('after_form_transition',dict(samples=after,editor_closed=closed))
        if not closed:return result('submission_unknown','editor_not_closed',preflight=preflight)
        observed=rpc(page.evaluate,opener_script(target,old['canonical_url']))
        if observed.get('eligible') is not True:
            details=inspect_filled_details_controls(page,**target,guard=check,checkpoint=lambda stage,value:save('after_'+stage,value))
            save('after_details_receipt',details)
            need(details.get('status')=='visible_change_observed','new_details_not_confirmed')
            observed=rpc(page.evaluate,opener_script(target,old['canonical_url']))
        readback_records=_records(observed)
        readback=save('after_exact_records',dict(opener=observed,records=readback_records))
        confirmed=all(r in readback_records for r in baseline) and dict(canonical_url=new['canonical_url'],publish_date=new['publish_date']) in readback_records
        try:
            image=folder/'NEW_BACKFILL_READBACK.png';rpc(page._cmd,'screenshot',path=str(image),full_page=False);shot=dict(status='saved',file=reference(image))
        except Exception as error:shot=dict(status='unavailable',error_type=type(error).__name__)
        return result('confirmed' if confirmed else 'submission_unknown','old_and_new_native_records_verified' if confirmed else 'new_record_not_observed',
            preflight=preflight,readback=readback,screenshot=shot,records=readback_records)
    except (NewPostBackfillNotConfirmed,BackfillEditorNotConfirmed,DetailsControlsNotConfirmed) as error:
        save('known_observation_block',dict(error_type=type(error).__name__,reason=str(error),submit_claimed=submission_claim is not None,submit_click_dispatched=dispatched))
        return result('submission_unknown' if claim_requested or dispatched else 'not_submitted',str(error))
    except Exception as error:
        _once(folder/'NATIVE_FAILURE.json',dict(error_type=type(error).__name__,submit_claimed=submission_claim is not None,submit_click_dispatched=dispatched,automatic_retry=False))
        if claim_requested or dispatched:return result('submission_unknown','native_rpc_failed')
        raise
