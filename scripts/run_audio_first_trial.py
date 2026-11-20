"""One bounded audio -> picture -> review experiment, no production release."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_faithful_video_agent import TextLedger,NativeClient
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger
from src.content_factory.novel_adaptation import audio_first as a,contracts as c,restricted_transcription as r,screen_continuity as sc
from src.content_factory.corpus_screenplay_v1 import read,freeze
from src.content_factory.serial_story_runtime_v2 import run_lock

def comparison_payload(packet,bank,layout,validation,candidate=None):
    # Full source is already supplied; repeating every original range and the
    # rendered script inside diagnostics inflated the request beyond capacity.
    diagnostic={k:v for k,v in validation.items() if k not in ('rendered','visual_source_evidence')}
    diagnostic['visual_source_evidence']=[{k:v for k,v in e.items() if k!='originals'} for e in validation.get('visual_source_evidence',[])]
    value={'source':packet,'audio_bank':bank,'layout':layout,'format_diagnostics':diagnostic}
    if candidate is not None:value['complete_candidate']=candidate
    return value

def prepare(run,prior):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status'] in ('running','prepared','outcome_unknown'):raise ValueError('prior_not_terminal')
    run.mkdir(exist_ok=False)
    plan.update(route='audio_first',version='audio_first_v1',baseline_calls=state['calls_started'],
                baseline_tokens=state['reported_tokens'],max_calls=state['calls_started']+3)
    paths=[Path(__file__),Path(a.__file__),Path(r.__file__),Path(sc.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for name in ('SOURCE','INPUT','BACKGROUND'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    freeze(run/'PLAN.json',plan)
    freeze(run/'AUTHORIZATION.json',{'user':'行跑一遍试试','scope':'声音整理、画面组织、全稿审核各一次MiniMax文本；同原文19前情/20—21目标；315→318工程边界，无媒体发布','prior':str(prior)})
    state.update(status='prepared',completed_stages=[],stage=None)
    TextLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        client=NativeClient(run,plan);strict=DirectLedger(run,plan,state,client);text=TextLedger(run,plan,state,client)
        packet=read(run/'INPUT.json')
        try:
            if plan.get('review_failed_picture_only') or plan.get('review_existing_picture_only'):
                bank=read(run/'AUDIO_BANK.json');layout=(run/'layout.txt').read_text('utf-8');validation=read(run/'LAYOUT_VALIDATION.json')
                candidate=(run/'screenplay.md').read_text('utf-8') if (run/'screenplay.md').exists() else None
                suffix='' if candidate is not None else '\n本次画面格式失败，未合成为有效剧本。审查原始声音表与原始画面安排，不把格式失败当已渲染成功；仍定位实际内容错误。'
                review=text.call('comparison','writer',a.review_prompt(plan.get('preserve_source_facts',False))+suffix,comparison_payload(packet,bank,layout,validation,candidate),c.obj(text=c.TEXT))
                (run/'review.md').write_text(review['text'],encoding='utf-8')
                freeze(run/'REVIEW_BINDING.json',{'candidate_sha256':c.digest(candidate) if candidate is not None else None,'audio_sha256':c.digest(bank),'layout_sha256':c.digest(layout),'rendered_candidate':candidate is not None,'semantic_acceptance':False})
                state['completed_stages'].append('comparison');state['status']='awaiting_primary_full_review' if candidate is not None else 'failed_picture_reviewed_awaiting_primary'
                return
            raw=read(run/'audio_DIRECT_DECODED.json') if (run/'KNOWN_AUDIO_ADOPTION.json').exists() else strict.call('audio','writer',a.AUDIO_PROMPT,packet,a.schema(packet))
            bank=a.build_bank(raw,packet);freeze(run/'AUDIO_BANK.json',bank)
            state['completed_stages'].append('audio');strict.save()
            layout=text.call('picture','writer',a.picture_prompt(plan.get('preserve_source_facts',False)),{'source':packet,'audio_bank':bank},c.obj(text=c.TEXT))['text']
            (run/'layout.txt').write_text(layout,encoding='utf-8')
            validation=a.render_layout(layout,bank,packet);freeze(run/'LAYOUT_VALIDATION.json',validation)
            if not validation['format_passed']:raise ValueError('picture_contract_failed')
            candidate=r.render_background(read(run/'BACKGROUND.json'))+'\n\n# 声音与画面合成候选\n\n'+validation['rendered']
            (run/'screenplay.md').write_text(candidate,encoding='utf-8')
            state['completed_stages'].append('picture');text.save()
            review=text.call('comparison','writer',a.review_prompt(plan.get('preserve_source_facts',False)),comparison_payload(packet,bank,layout,validation,candidate),c.obj(text=c.TEXT))
            (run/'review.md').write_text(review['text'],encoding='utf-8')
            freeze(run/'REVIEW_BINDING.json',{'candidate_sha256':c.digest(candidate),'audio_sha256':c.digest(bank),'layout_sha256':c.digest(layout),'semantic_acceptance':False})
            state['completed_stages'].append('comparison');state['status']='awaiting_primary_full_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:3000]})
        finally:text.save()

def continue_audio(run,prior):
    """Reuse a known complete audio response after fixing a false hard gate."""
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status']!='needs_attention':raise ValueError('prior_not_known_failure')
    if read(prior/'ERROR.json')['message']!='speaker_missing_literal_evidence':raise ValueError('unsupported_failure')
    if state['calls_started']+2>plan['max_calls']:raise ValueError('window_exhausted')
    n=state['calls_started'];native_path=prior/f'RESPONSE_{n}.json'
    native=read(native_path)['native']
    from src.content_factory.novel_adaptation.stream_evidence import audit_folder
    if audit_folder(prior/f'native_{n}')['completion_evidence']!='known':raise ValueError('unknown_response')
    if native['choices'][0]['finish_reason']!='tool_calls':raise ValueError('unsupported_response')
    raw=read(prior/'audio_DIRECT_DECODED.json')
    calls=native['choices'][0]['message'].get('tool_calls',[])
    if len(calls)!=1 or json.loads(calls[0]['function']['arguments'])!=raw:raise ValueError('native_audio_mismatch')
    a.build_bank(raw,read(prior/'INPUT.json'))
    run.mkdir(exist_ok=False)
    for name in ('SOURCE','INPUT','BACKGROUND','audio_DIRECT_DECODED','AUTHORIZATION'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    paths=[Path(__file__),Path(a.__file__),Path(r.__file__),Path(sc.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan.update(version='audio_first_v1_1',implementation_pin={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    freeze(run/'PLAN.json',plan)
    freeze(run/'KNOWN_AUDIO_ADOPTION.json',{'prior':str(prior),'call':n,'native_response_sha256':hashlib.sha256(native_path.read_bytes()).hexdigest(),'raw_sha256':c.digest(raw),'scope':'完整原生声音不修改；证据字面不匹配改待审，后两阶段沿原318上界，非语义通过。'})
    state.update(status='prepared',stage=None,completed_stages=[]);TextLedger(run,plan,state,None).save()

def prepare_failed_picture(run,prior):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status']!='needs_attention':raise ValueError('prior_not_known_failure')
    if read(prior/'ERROR.json')['message'] not in ('picture_contract_failed','complete_request_exceeds_capacity'):raise ValueError('unsupported_failure')
    if state['calls_started']+1>plan['max_calls']:raise ValueError('window_exhausted')
    n=state['calls_started']
    from src.content_factory.novel_adaptation.stream_evidence import audit_folder
    if audit_folder(prior/f'native_{n}')['completion_evidence']!='known':raise ValueError('unknown_response')
    layout=(prior/'layout.txt').read_text('utf-8')
    if read(prior/'picture_DIRECT_DECODED.json')['text']!=layout:raise ValueError('layout_mismatch')
    if read(prior/'LAYOUT_VALIDATION.json')['layout_sha256']!=c.digest(layout):raise ValueError('validation_mismatch')
    run.mkdir(exist_ok=False)
    for name in ('SOURCE','INPUT','BACKGROUND','AUDIO_BANK','LAYOUT_VALIDATION','AUTHORIZATION'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    (run/'layout.txt').write_text(layout,encoding='utf-8')
    candidate_path=prior/'screenplay.md'
    if candidate_path.exists():
        expected=r.render_background(read(prior/'BACKGROUND.json'))+'\n\n# 声音与画面合成候选\n\n'+read(prior/'LAYOUT_VALIDATION.json')['rendered']
        if candidate_path.read_text('utf-8')!=expected:raise ValueError('candidate_mismatch')
        (run/'screenplay.md').write_bytes(candidate_path.read_bytes())
    paths=[Path(__file__),Path(a.__file__),Path(r.__file__),Path(sc.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan.update(review_failed_picture_only=not candidate_path.exists(),review_existing_picture_only=candidate_path.exists(),version='audio_first_known_picture_review_v2',implementation_pin={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    freeze(run/'PLAN.json',plan)
    freeze(run/'FAILURE_ADOPTION.json',{'prior':str(prior),'layout_sha256':c.digest(layout),'source_sha256':c.digest(read(prior/'INPUT.json')),'no_regeneration':True})
    state.update(status='prepared',stage=None);TextLedger(run,plan,state,None).save()

def prepare_fact_trial(run,prior,audio_from):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status'] in ('running','prepared','outcome_unknown'):raise ValueError('prior_not_terminal')
    original=read(prior/'INPUT.json');old_state=read(audio_from/'STATE.json');raw=read(audio_from/'audio_DIRECT_DECODED.json')
    if old_state['pending'] is not None:raise ValueError('audio_pending')
    if read(audio_from/'INPUT.json')!=original:raise ValueError('different_audio_source')
    if read(prior/'AUDIO_BANK.json')['raw_sha256']!=c.digest(raw):raise ValueError('different_prior_audio')
    n=old_state['calls_started'];native_path=audio_from/f'RESPONSE_{n}.json';native=read(native_path)['native']
    from src.content_factory.novel_adaptation.stream_evidence import audit_folder
    if audit_folder(audio_from/f'native_{n}')['completion_evidence']!='known':raise ValueError('unknown_audio_response')
    calls=native['choices'][0]['message'].get('tool_calls',[])
    if native['choices'][0]['finish_reason']!='tool_calls' or len(calls)!=1 or json.loads(calls[0]['function']['arguments'])!=raw:raise ValueError('native_audio_mismatch')
    a.build_bank(raw,original)
    run.mkdir(exist_ok=False)
    for name in ('SOURCE','INPUT','BACKGROUND'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    freeze(run/'audio_DIRECT_DECODED.json',raw)
    freeze(run/'KNOWN_AUDIO_ADOPTION.json',{'prior':str(audio_from),'call':n,'raw_sha256':c.digest(raw),'native_response_sha256':hashlib.sha256(native_path.read_bytes()).hexdigest(),'semantic_acceptance':False,'scope':'固定已有声音输入；本轮只生成画面与审核。'})
    plan.update(version='audio_first_source_preservation_v2',review_failed_picture_only=False,review_existing_picture_only=False,preserve_source_facts=True,
                max_calls=state['calls_started']+2,baseline_calls=state['calls_started'],baseline_tokens=state['reported_tokens'])
    paths=[Path(__file__),Path(a.__file__),Path(r.__file__),Path(sc.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    freeze(run/'PLAN.json',plan)
    freeze(run/'AUTHORIZATION.json',{'user':'你确认我的方向可信后开始一起修复轮输出结果','scope':'原文明确信息不改、未知不猜；同源声音复用，MiniMax画面和审核各一次；318→320工程窗口，不生成媒体发布','prior':str(prior)})
    state.update(status='prepared',stage=None,completed_stages=[]);TextLedger(run,plan,state,None).save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute','continue-audio','prepare-failed-picture','prepare-review','prepare-facts']);p.add_argument('--run',required=True,type=Path);p.add_argument('--prior',type=Path);p.add_argument('--audio-from',type=Path);args=p.parse_args()
    if args.command=='prepare':prepare(args.run,args.prior)
    elif args.command=='continue-audio':continue_audio(args.run,args.prior)
    elif args.command in ('prepare-failed-picture','prepare-review'):prepare_failed_picture(args.run,args.prior)
    elif args.command=='prepare-facts':prepare_fact_trial(args.run,args.prior,args.audio_from)
    else:execute(args.run)
