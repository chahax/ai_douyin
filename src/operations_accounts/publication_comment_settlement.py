"""Read-only settlement of one already attempted, locked publication comment."""
import hashlib
import json
import re
import time
from pathlib import Path

from src.shared.published_work_scope import inspect_observed_public_work

ROOT = Path(__file__).resolve().parents[2]

_READ_COMMENTS_JS = r"""arg=>{
  const stamp={url:location.href,time_origin:performance.timeOrigin};
  const visible=n=>{const r=n.getBoundingClientRect();return n.isConnected&&getComputedStyle(n).visibility!=='hidden'&&r.width>0&&r.height>0&&r.bottom>0&&r.right>0&&r.x<innerWidth&&r.y<innerHeight};
  const clean=s=>String(s||'').replace(/https?:\/\/\S+/gi,'[url]').replace(/\b(token|access_token|authorization|cookie|session|password)\s*[:=]\s*\S+/gi,'[redacted]').replace(/\s+/g,' ').trim().slice(0,100);
  const shape=n=>{const r=n.getBoundingClientRect();return {tag:n.tagName,role:clean(n.getAttribute('role')),data_e2e:clean(n.getAttribute('data-e2e')),
    aria_label:clean(n.getAttribute('aria-label')),class_tokens:Array.from(n.classList).filter(c=>/^[A-Za-z_-][A-Za-z0-9_-]{0,63}$/.test(c)&&!/(token|password|authorization|cookie|session)/i.test(c)).slice(0,8),
    visible:!!visible(n),width:Math.round(r.width),height:Math.round(r.height),contenteditable:n.getAttribute('contenteditable')==='true',
    comment_id:/^[0-9]{1,30}$/.test(n.getAttribute('data-comment-id')||'')?n.getAttribute('data-comment-id'):null};};
  const reject=(reason,diagnostic={})=>({exact_visible:false,reason,document:stamp,diagnostic});
  const url=new URL(location.href),details=document.querySelectorAll('[data-e2e="video-detail"]');
  if(url.protocol!=='https:'||!['douyin.com','www.douyin.com'].includes(url.host)||url.pathname!=='/video/'+arg.id||details.length!==1)return reject('work_identity_changed');
  const detail=details[0],players=detail.querySelectorAll('[data-e2e="player-container"]'),lists=detail.querySelectorAll('[data-e2e="comment-list"]');
  if(players.length!==1||!players[0].classList.contains('video_'+arg.id))return reject('work_identity_changed');
  if(lists.length!==1)return reject('comment_list_not_unique',{comment_list_count:lists.length});
  const list=lists[0],panel=list.parentElement;
  if(!visible(list)||list.closest('form,[contenteditable=true],[inert]')||list.querySelectorAll('*').length>2000)return reject('comment_list_not_readable');
  const safe=n=>!n.closest('form,[contenteditable=true],textarea,input,[data-e2e="detail-video-info"],h1');
  const items=Array.from(list.querySelectorAll('[data-e2e="comment-item"]'));
  if(items.length>250)return reject('comment_items_truncated');
  const matches=[],known=[];
  for(const item of items){
    if(!visible(item)||!safe(item))continue;
    const named=Array.from(new Set(item.querySelectorAll('[data-e2e="comment-content"],[data-e2e="comment-item-content"]')));
    const content=named.filter(n=>visible(n)&&safe(n));
    const entry={item:shape(item),content_count:content.length,named_content_nodes:named.length,exact_text:content.length===1&&content[0].innerText.trim()===arg.text};
    known.push(entry);
    if(content.length===1&&content[0].innerText.trim()===arg.text)matches.push({item:shape(item),content:shape(content[0]),source:'named_comment_content'});
    if(named.length===0&&!item.parentElement?.closest('[data-e2e="comment-item"]')){
      const excluded='form,[contenteditable=true],textarea,input,header,h1,h2,h3,h4,h5,h6,[role="heading"],blockquote,q,[role="blockquote"],[data-e2e*="reply" i],[data-e2e*="quote" i]';
      const spans=Array.from(item.querySelectorAll('span')).filter(n=>visible(n)&&safe(n)&&!n.closest(excluded)&&
        n.closest('[data-e2e="comment-item"]')===item&&n.innerText.trim()===arg.text);
      const deepest=spans.filter(n=>!spans.some(other=>other!==n&&n.contains(other)));
      entry.observed_span_leaf_count=deepest.length;
      if(deepest.length===1&&deepest[0].children.length===0){
        const leaf=deepest[0];let ancestor=leaf.parentElement,chain=0;
        while(ancestor&&chain<8&&item.contains(ancestor)&&ancestor!==item&&ancestor.tagName==='SPAN'&&visible(ancestor)&&
          !ancestor.closest(excluded)&&ancestor.closest('[data-e2e="comment-item"]')===item&&ancestor.innerText.trim()===arg.text){chain++;ancestor=ancestor.parentElement;}
        entry.observed_span_chain=chain;
        if(chain>=3){entry.exact_text=true;matches.push({item:shape(item),content:shape(leaf),source:'observed_nested_span/20261019',span_ancestor_count:chain});}
      }
    }
  }
  const all=Array.from(list.querySelectorAll('div,span,p'));
  const exact=all.filter(n=>visible(n)&&safe(n)&&n.innerText.trim()===arg.text);
  const leaves=exact.filter(n=>!exact.some(other=>other!==n&&n.contains(other)));
  const projected=leaves.slice(0,12).map(n=>{const ancestors=[];for(let p=n.parentElement,depth=1;p&&depth<=4&&list.contains(p);p=p.parentElement,depth++){
    ancestors.push({...shape(p),depth});if(p===list)break;}return {...shape(n),approved_text_exact:true,ancestors};});
  const errorPattern=/(?:(?:字符|字数).{0,12}(?:限制|超|多)|(?:超出|超过|超长|最多).{0,12}(?:字|字符)|发布失败|发送失败|评论失败|审核|登录后.{0,8}评论|请先登录|内容.{0,8}(?:违规|不符合|限制))/;
  const errors=Array.from(document.querySelectorAll('[role="alert"],[role="status"],[data-e2e]')).slice(0,4000)
    .filter(n=>visible(n)&&safe(n)&&!list.contains(n)&&(n.matches('[role="alert"],[role="status"]')||/toast/i.test(n.getAttribute('data-e2e')||'')));
  if(panel&&panel!==detail)errors.push(...Array.from(panel.querySelectorAll('div,span,p')).slice(0,1000).filter(n=>!n.children.length&&!list.contains(n)&&visible(n)&&safe(n)));
  const errorNodes=Array.from(new Set(errors)).filter(n=>{const text=n.innerText.trim();return text.length>0&&text.length<=200&&errorPattern.test(text)});
  const diagnostic={schema:'comment_readonly_dom_diagnostic/v1',comment_list:shape(list),known_items:known.slice(0,12),known_items_truncated:known.length>12,
    approved_text_leaf_count:leaves.length,approved_text_candidates:projected,approved_text_candidates_truncated:leaves.length>12,
    shallow_tree:Array.from(list.children).slice(0,12).map(n=>({...shape(n),children:Array.from(n.children).slice(0,8).map(shape),children_truncated:n.children.length>8})),
    shallow_tree_truncated:list.children.length>12,visible_errors:errorNodes.slice(0,12).map(n=>({...shape(n),text:clean(n.innerText)})),visible_errors_truncated:errorNodes.length>12};
  return {exact_visible:matches.length===1,reason:matches.length===1?'known_exact_comment_visible':matches.length>1?'exact_comment_ambiguous':'known_exact_comment_missing',
    known_exact_matches:matches.length,match:matches.length===1?matches[0]:null,document:stamp,diagnostic};
}"""

_SCROLL_LIST_JS = r"""(list,id)=>{
  const detail=list.closest('[data-e2e="video-detail"]'),players=detail?.querySelectorAll('[data-e2e="player-container"]');
  const url=new URL(location.href);
  if(url.protocol!=='https:'||!['douyin.com','www.douyin.com'].includes(url.host)||url.pathname!=='/video/'+id||
    document.querySelectorAll('[data-e2e="video-detail"]').length!==1||!detail||players.length!==1||!players[0].classList.contains('video_'+id)||
    detail.querySelectorAll('[data-e2e="comment-list"]').length!==1||!list.isConnected||list.ownerDocument!==document||
    list.closest('form,[contenteditable=true],[inert]'))return {scrolled:false};
  list.scrollIntoView({behavior:'instant',block:'center',inline:'nearest'});return {scrolled:true};
}"""


def _load_ref(reference):
    if not isinstance(reference, dict) or not re.fullmatch(r'[0-9a-f]{64}',str(reference.get('sha256',''))):
        raise ValueError('Frozen source reference required')
    path=Path(reference['path']).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Source must remain in project')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=reference['sha256']:raise ValueError('Frozen source changed')
    value=json.loads(data)
    if not isinstance(value,dict):raise ValueError('Frozen source must be an object')
    return path,value


def _full_proof(page,post_id,title,tags):
    value=inspect_observed_public_work(page,post_id,title,required_hashtags=tags)
    return dict(value,post_id=post_id,publish_url=f'https://www.douyin.com/video/{post_id}',
        post_verified=value.get('verified')is True,ai_declaration_verified=value.get('ai_label_visible')is True,
        fiction_declaration_verified=value.get('fiction_notice_visible')is True,
        player_verified=value.get('verified')is True and value.get('player',{}).get('ready')is True)


def verify_only(adapter,frozen_command,post_id,*,evidence_dir):
    """Observe an existing comment; never enter any posting or activation path."""
    context=adapter.runtime_context;text=str(frozen_command.get('comment')or'').strip();post_id=str(post_id)
    title=frozen_command.get('title');tags=frozen_command.get('hashtags');prior=frozen_command.get('publish_evidence')or{}
    command_id=frozen_command.get('original_comment_command_id')
    if (not context or not re.fullmatch(r'[0-9]+',post_id)or not text or not frozen_command.get('authorization')or
        frozen_command.get('account_uuid')!=context.account_uuid or frozen_command.get('account_key')!=context.account_key or
        not re.fullmatch(r'[0-9a-f]{32}',str(command_id))or not isinstance(title,str)or not title or not isinstance(tags,list)or
        prior.get('verified')is not True or prior.get('expected_title')!=title or prior.get('expected_hashtags')!=tags or
        str(prior.get('expected_post_id')or prior.get('post_id')or'')!=post_id):raise ValueError('Exact frozen work and account proof required')
    identity={'account_uuid':context.account_uuid,'post_id':post_id,'comment_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    claim_ref=frozen_command['source_claim'];receipt_ref=frozen_command['source_unknown_receipt']
    claim_path,claim=_load_ref(claim_ref);receipt_path,unknown=_load_ref(receipt_ref)
    comment_root=(ROOT/'data/publish_comments').resolve();url=f'https://www.douyin.com/video/{post_id}'
    if (claim_path!=comment_root/f'{key}.submitted.json'or receipt_path!=comment_root/f'{key}.receipt.json'or
        claim.get('identity')!=identity or claim.get('status')!='submission_started'or unknown.get('identity')!=identity or
        unknown.get('schema')!='authorized_publication_comment/v1'or unknown.get('status')!='outcome_unknown'or
        unknown.get('submission_lock_retained')is not True or unknown.get('post_url')!=url or unknown.get('comment')!=text):
        raise ValueError('Original unknown receipt and retained claim must match')
    out=Path(evidence_dir).resolve()
    if not out.is_relative_to(ROOT)or out==comment_root or out.is_relative_to(comment_root):raise ValueError('Independent project evidence directory required')
    out.mkdir(parents=True,exist_ok=True);target=out/'readonly-comment-receipt.json'
    if target.exists():
        value=json.loads(target.read_text(encoding='utf-8'))
        if value.get('identity')!=identity or value.get('source_claim')!=claim_ref or value.get('source_unknown_receipt')!=receipt_ref or value.get('original_comment_command_id')!=command_id:raise ValueError('Readonly evidence identity changed')
        return dict(value,readonly_evidence_ref={'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    guard=getattr(adapter.session,'_guard',None);page=None;observations=[];proof={'post_verified':False};scrolled=False
    def check():
        if callable(guard):guard()
    def finish(status,reason,read=None):
        _load_ref(claim_ref);_load_ref(receipt_ref)
        value={'schema':'authorized_publication_comment_readonly/v1','status':status,'identity':identity,'post_url':url,'comment':text,
            'original_comment_command_id':command_id,'source_unknown_receipt':receipt_ref,'source_claim':claim_ref,
            'exact_visible':status=='matching_comment_already_visible','new_submission':False,'ownership_verified':False,
            'reason':reason,'publish_evidence':proof,'observations':observations,'scroll_attempted':scrolled}
        if read is not None:value['native_read']=read
        if page is not None:
            try:
                check();shot=out/'comment-readonly-ui.png'
                if callable(getattr(page,'screenshot',None)):page.screenshot(path=str(shot),full_page=False)
                else:page._cmd('screenshot',path=str(shot),full_page=False)
                value['ui_evidence_path']=str(shot)
            except Exception as exc:value['ui_evidence_error_type']=type(exc).__name__
        with target.open('x',encoding='utf-8')as handle:json.dump(value,handle,ensure_ascii=False,indent=2)
        return dict(value,readonly_evidence_ref={'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    try:
        check()
        if adapter._require_runtime_identity(force=True)is not None:return finish('human_required','original_identity_unverified')
        page=adapter.session.open_page(url);started=time.monotonic();read=None
        for index in range(8):
            if time.monotonic()-started>=20:break
            check();proof=_full_proof(page,post_id,title,tags)
            if proof.get('human_required'):return finish('human_required','native_challenge_visible')
            if proof.get('moderation_markers'):return finish('unconfirmed','work_review_not_clear')
            if proof.get('reason')in('canonical_or_frozen_title_missing','native_player_id_mismatch','native_caption_title_mismatch'):
                return finish('unconfirmed','work_identity_changed')
            if proof.get('verified'):
                selector=f'[data-e2e="video-detail"]:has([data-e2e="player-container"].video_{post_id}) [data-e2e="comment-list"]'
                lists=page.locator(selector)
                if not scrolled and lists.count()==1:
                    check();scrolled=True
                    if not lists.evaluate('list=>('+_SCROLL_LIST_JS+')(list,'+json.dumps(post_id)+')').get('scrolled'):return finish('unconfirmed','comment_list_scroll_identity_unknown')
                    check();proof=_full_proof(page,post_id,title,tags)
                    if not proof.get('verified'):return finish('human_required'if proof.get('human_required')else'unconfirmed','after_scroll_work_changed')
                check();read=page.evaluate('()=>('+_READ_COMMENTS_JS+')('+json.dumps({'id':post_id,'text':text},ensure_ascii=False)+')')
                (out/f'native-read-{index+1}.json').write_text(json.dumps(read,ensure_ascii=False,indent=2),encoding='utf-8')
                observations.append({'attempt':index+1,'work_verified':True,'exact_visible':read.get('exact_visible')is True,'reason':read.get('reason')})
                if read.get('exact_visible'):
                    check();proof=_full_proof(page,post_id,title,tags)
                    stamp=page.evaluate('()=>({url:location.href,time_origin:performance.timeOrigin})')
                    if proof.get('verified')and stamp==read.get('document')and time.monotonic()-started<20:return finish('matching_comment_already_visible','known_exact_comment_visible',read)
                    return finish('human_required'if proof.get('human_required')else'unconfirmed','final_work_identity_unverified',read)
                if read.get('reason')in('work_identity_changed','exact_comment_ambiguous','comment_list_not_unique'):return finish('unconfirmed',read['reason'],read)
            else:observations.append({'attempt':index+1,'work_verified':False,'reason':proof.get('reason')})
            if index<7:page.wait_for_timeout(min(1500,max(1,int((20-(time.monotonic()-started))*1000))))
        return finish('unconfirmed','readonly_wait_exhausted',read)
    except Exception as exc:
        return finish('unconfirmed','readonly_observation_failed',{'error_type':type(exc).__name__})
