"""Small real local DOM regression for the existing draft repair, no platform."""
import json
import sys
import threading
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v5 import draft,native,put
from src.operations_accounts import manual_republication_flow_v5 as v5
from src.operations_accounts import manual_republication_flow_v6 as flow


@pytest.fixture
def repair(draft,monkeypatch):
    x=draft;oldplan=put(x.run/'v5_plan_copy.json',flow.read(v5.reference(x.run/'v5/PLAN.json')))
    oldaction=v5.reference(x.run/'v5/ACTION_CLAIM.json')
    config=dict(x.config,sources=dict(x.config['sources'],flow_v5=v5.reference(v5.__file__)))
    cref=put(x.run/'CONFIG_V6.json',config)
    request=dict(schema='manual_republication_operator_request/v6',config=cref,action='repair_existing_draft',
        prior_draft_plan=oldplan,prior_draft_action=oldaction,prior_unknown=put(x.run/'V5_UNKNOWN.json',{}),
        prior_failure=put(x.run/'V5_FAILURE.json',{}),field_projection=put(x.run/'V5_PROJECTION.json',{}),draft_fence=put(x.run/'V5_FENCE.json',{}))
    reqref=put(x.run/'REQUEST_V6.json',request)
    planref=put(x.run/'v6/PLAN.json',dict(config=cref,request=reqref,prior=flow.read(oldplan)['prior']))
    put(x.run/'v6/ACTION_CLAIM.json',dict(schema='manual_republication_existing_draft_action_claim/v6',plan=planref,config=cref,request=reqref,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='same-tab',actor_thread_id=threading.get_ident(),
        action='repair_existing_draft',navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))
    x.config,x.request,x.out=config,request,x.run/'v6/preparation';x.fail_fill=False
    oldcmd=x.resource.session.cmd
    def command(kind,**kw):
        if kind=='screenshot':
            x.commands.append((kind,dict(kw)));x.page.screenshot(path=kw['path'],full_page=kw.get('full_page',False));return {'status':'ok'}
        result=oldcmd(kind,**kw)
        if kind=='fill' and x.fail_fill:raise RuntimeError('native locator.fill acknowledgement timeout\nurl=https://creator.douyin.com/creator-micro/content/post/video?token=secret\nCookie: hidden secret value')
        return result
    x.resource.session.cmd=command
    import src.operations_accounts as ops
    runtime=NS(validate_live=lambda *args:None)
    monkeypatch.setitem(sys.modules,'src.operations_accounts.manual_republication_runtime_v6',runtime)
    monkeypatch.setattr(ops,'manual_republication_runtime_v6',runtime,raising=False)
    return x


def run(x,out=None):return flow.run_action(x.actor,x.resource,x.config,x.request,out or x.out)


def test_missing_description_direct_fill_and_full_metadata_readback(repair):
    x=repair;x.page.locator('#title').fill(x.metadata['title']);result=run(x)
    assert result['title_fill_skipped'] and not result['description_fill_skipped']
    fills=[kw for action,kw in x.commands if action=='fill']
    assert len(fills)==1 and fills[0]['selector']==v5.EDITOR+':visible'
    assert not any(a=='click' and kw.get('selector')==v5.EDITOR+':visible' for a,kw in x.commands)
    assert result['metadata_readback_matched'] and result['hashtag_readback_verified']
    assert result['initial_screenshot']['status']=='saved'
    assert not any(a in {'goto','set_input_files','new_tab','ai_content_declaration'} for a,_ in x.commands)
    events=[json.loads(line) for line in open(result['rpc_trace']['path'],encoding='utf8')]
    assert any(e['event']=='rpc_dispatched' and e['phase']=='fill_description' for e in events)


def test_already_matching_fields_and_tags_are_not_rewritten(repair):
    x=repair;x.page.locator('#title').fill(x.metadata['title'])
    x.page.locator('#editor').fill('\u200b'+x.metadata['description']+' '+ ' '.join('#'+t for t in x.metadata['hashtags'])+'\u200b')
    result=run(x)
    assert result['title_fill_skipped'] and result['description_fill_skipped']
    assert not any(a in {'fill','type_hashtag'} for a,_ in x.commands)
    assert result['metadata_readback_matched']


def test_native_fill_error_keeps_phase_sanitized_cause_and_readonly_scene(repair):
    x=repair;x.fail_fill=True
    with pytest.raises(flow.ExistingDraftRepairBlocked) as caught:run(x)
    error=caught.value;assert error.code=='repair_mutation_unknown' and error.diagnostics_ref
    failure=flow.read(error.diagnostics_ref)
    assert failure['safe_error']['phase']=='fill_title' and failure['safe_error']['action']=='fill'
    assert 'native locator.fill acknowledgement timeout' in failure['safe_error']['message']
    assert 'secret' not in failure['safe_error']['message'] and 'hidden' not in failure['safe_error']['message']
    assert failure['failure_capture']['field_projection'] and failure['failure_capture']['screenshot']['status']=='saved'
    before=len(x.commands)
    with pytest.raises(flow.ExistingDraftRepairBlocked):run(x)
    assert len(x.commands)==before and not any(a=='set_input_files' for a,_ in x.commands)
    assert flow.safe_message(RuntimeError('https://username:password@example.test:443/public/path?token=secret#private'))=='https://example.test:443/public/path'


def test_changed_session_stops_capture_and_wrong_outdir_has_no_rpc(repair):
    x=repair
    with pytest.raises((flow.ExistingDraftRepairBlocked,FileNotFoundError)):run(x,x.run/'wrong/preparation')
    assert x.commands==[]
    x.hooks[0]=lambda *args:setattr(x.resource,'session',NS(_proc=NS(poll=lambda:None)))
    with pytest.raises(flow.ExistingDraftRepairBlocked):run(x)
    assert len(x.commands)==1 and not any(a in {'fill','screenshot'} for a,_ in x.commands)


def test_exact_observed_preview_tip_overlay_dismissed_once_before_metadata(repair):
    x=repair
    x.page.evaluate("""args=>{const overlay=document.createElement('div');overlay.id='preview-tip';overlay.style='position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.3)';
      const box=document.createElement('div');box.style='background:white';
      const heading=document.createElement('h3');heading.textContent=args.title;const body=document.createElement('p');body.textContent=args.body;
      const button=document.createElement('button');button.type='button';button.textContent='我知道了';button.id='tip-close';button.onclick=()=>overlay.remove();
      box.append(heading,body,button);overlay.append(box);document.body.append(overlay)}""",dict(title=flow.PREVIEW_TIP_TITLE,body=flow.PREVIEW_TIP_BODY))
    result=run(x)
    assert result['preview_tip_dismissed'] and flow.read(result['preview_tip_before'])['eligible']
    clicks=[kw for a,kw in x.commands if a=='click' and kw.get('selector')==flow.PREVIEW_TIP_SELECTOR]
    assert len(clicks)==1 and result['metadata_readback_matched']
    assert flow.read(result['preview_tip_after'])['samples'][-1]['candidate_count']==0
    x.page.evaluate("""()=>{let box=document.createElement('div');box.innerHTML='<h3>其他提示</h3><p>需要同意法律条款</p><button type="button">我知道了</button>';document.body.append(box)}""")
    assert not x.page.evaluate(flow.preview_tip_script())['eligible']
