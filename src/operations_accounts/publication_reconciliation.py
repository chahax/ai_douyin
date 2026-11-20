"""One authorized original-work reconciliation, never an uploader or publisher."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MANAGE='https://creator.douyin.com/creator-micro/content/manage'


def _active_ai_source(rows):
    clicks=[i for i,row in enumerate(rows) if row.get('stage')=='publish_click_dispatching']
    reserves=[i for i,row in enumerate(rows) if row.get('stage')=='submission_started']
    if len(clicks)!=1 or len(reserves)!=1 or reserves[0]>=clicks[0]:return False
    indexed=[(i,row) for i,row in enumerate(rows[:clicks[0]]) if row.get('stage')=='ai_declaration_verified']
    reads=[row for _,row in indexed]
    valid=lambda row: (row.get('evidence',{}).get('verified') is True and
        re.fullmatch(r'内容由\s*AI\s*生成',str(row.get('evidence',{}).get('label',''))) is not None)
    return bool(reads and indexed[-1][0]>reserves[0] and all(valid(row) for row in reads) and
        any(row.get('set_selected') is True for row in reads) and reads[-1].get('set_selected') is False)


def run_reconciliation(ctx,payload):
    from .publication_autonomous_reconciliation import get_verified_reconciliation_inputs
    from .publication_comment import post_authorized_publication_comment
    from src.platform_adapter.douyin_adapter import DouyinAdapter
    from src.platform_adapter.publish_verification import video_id,wait_for_published_video
    inputs=get_verified_reconciliation_inputs(payload)
    prepared,auth=inputs['prepared'],inputs['authorization']
    if not re.fullmatch(r'[a-f0-9]{32}',ctx.task_id):raise ValueError('invalid reconciliation task identity')
    resource=ctx.resource;session=resource.reconciliation_session
    if resource.account_uuid!=payload['account_uuid'] or resource.account_key!=payload['account_key']:
        raise ValueError('original account differs')
    out=ROOT/'data/publication_reconciliations'/ctx.task_id;out.mkdir(parents=True,exist_ok=True)
    evidence_file=out/'evidence.json'
    def finish(status,evidence,comment):
        result={'status':status,'publish_evidence':evidence,'comment':comment}
        frozen={'schema':'publication_reconciliation_evidence/20261019/v1',
            'account_uuid':payload['account_uuid'],'original_command_id':payload['original_command_id'],
            'reconciliation_command_id':ctx.task_id,'result':result}
        with evidence_file.open('x',encoding='utf-8') as handle:
            json.dump(frozen,handle,ensure_ascii=False,indent=2)
        return dict(result,evidence_ref={'path':str(evidence_file.resolve()),
            'sha256':hashlib.sha256(evidence_file.read_bytes()).hexdigest()})
    try:
        with (out/'started.json').open('x',encoding='utf-8') as handle:
            json.dump({'original_command_id':payload['original_command_id']},handle)
    except FileExistsError:
        if evidence_file.exists():
            old=json.loads(evidence_file.read_text(encoding='utf-8'))
            return dict(old['result'],evidence_ref={'path':str(evidence_file.resolve()),
                'sha256':hashlib.sha256(evidence_file.read_bytes()).hexdigest()})
        return finish('outcome_unknown',{'post_verified':False,'reason':'original reconciliation already started'},
                      {'status':'not_submitted'})
    evidence={'post_verified':False};comment={'status':'not_submitted'}
    try:
        ctx.check_dispatch()
        check=resource.runtime.verify_identity(resource.context,session=session)
        if not check.healthy:
            return finish('human_required',dict(evidence,identity_status=check.status),comment)
        page=session.open_page(MANAGE);page.wait_for_timeout(1500)
        discovery=None
        for index in range(8):
            ctx.check_dispatch();discovery=page.discover_published_work(prepared['title'])
            (out/f'discovery-{index+1}.json').write_text(json.dumps(discovery,ensure_ascii=False,indent=2),encoding='utf-8')
            if index in (0,7) or discovery.get('verified'):
                page._cmd('screenshot',path=str(out/f'manage-{index+1}.png'),full_page=False)
            if discovery.get('verified'):break
            if discovery.get('reason') not in ('title_not_unique','canonical_id_missing','independent_card_unbound','manage_loading','title_candidate_missing'):break
            page.wait_for_timeout(1000)
        if discovery and (discovery.get('reason')=='observed_cover_human_required' or
                discovery.get('diagnostic',{}).get('native_popup_resolution',{}).get('human_required') is True):
            return finish('human_required',dict(evidence,reason='observed_cover_human_required',discovery=discovery),comment)
        if not discovery or discovery.get('verified') is not True:
            return finish('verification_pending',dict(evidence,reason=(discovery or {}).get('reason','discovery_unavailable'),discovery=discovery),comment)
        post_id,url=discovery['post_id'],discovery['publish_url']
        if not post_id or url!=f'https://www.douyin.com/video/{post_id}' or video_id(url)!=post_id:
            return finish('outcome_unknown',dict(evidence,reason='exact work URL missing'),comment)
        ctx.check_dispatch();page.goto(url)
        verified=wait_for_published_video(page,post_id,ai_required=True,fiction_required=True,
            required_hashtags=prepared['hashtags'],expected_title=prepared['title'],
            evidence_path=str(out/'published-work.png'),dispatch_guard=ctx.check_dispatch)
        if verified.get('human_required') is True:
            return finish('human_required',dict(verified,post_verified=False,post_id=post_id,publish_url=url),comment)
        active_ok=_active_ai_source(inputs['journal_rows'])
        player=verified.get('player') or {}
        evidence=dict(verified,post_id=post_id,publish_url=url,post_verified=verified.get('verified') is True,
            ai_declaration_verified=verified.get('ai_label_visible') is True,
            fiction_declaration_verified=verified.get('fiction_notice_visible') is True,
            hashtags_verified=verified.get('hashtags_verified') is True,
            player_verified=player.get('ready') is True and player.get('error') is False and player.get('duration') is True,
            ai_active_source_verified=active_ok,ai_active_source='original_frozen_pre_submit_journal',
            ai_label_origin='unknown; display does not identify creator-selected origin')
        if (any(evidence.get(key) is not True for key in ('post_verified','ai_declaration_verified',
                'fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified'))
                or evidence.get('review_status')!='clear'):
            return finish('verification_pending',evidence,comment)
        text=prepared.get('comment','')
        if text:
            adapter=DouyinAdapter(session=session,runtime_context=resource.context)
            ctx.check_dispatch()
            comment=post_authorized_publication_comment(adapter,{'account_uuid':payload['account_uuid'],
                'account_key':payload['account_key'],'authorization':inputs['original_command']['payload']['authorization'],'comment':text,
                'title':prepared['title'],'hashtags':prepared['hashtags'],
                'publish_evidence':dict(evidence,verified=True,expected_post_id=post_id)},post_id)
            if comment.get('status')=='outcome_unknown':return finish('outcome_unknown',evidence,comment)
            if comment.get('status')=='human_required':return finish('human_required',evidence,comment)
            if comment.get('status') not in ('sent_visible','matching_comment_already_visible'):
                return finish('verification_pending',evidence,comment)
        else:comment={'status':'not_requested'}
        return finish('verified_published',evidence,comment)
    except Exception as exc:
        try:session.get_page()._cmd('screenshot',path=str(out/'failure-ui.png'),full_page=False)
        except Exception:pass
        return finish('outcome_unknown',dict(evidence,error_type=type(exc).__name__),comment)
