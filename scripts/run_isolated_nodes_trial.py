"""Three fresh independent requests; one bounded trial, no automatic retries."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_faithful_video_agent import TextLedger,NativeClient
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger
from src.content_factory.novel_adaptation import isolated_nodes as n,audio_first as a,contracts as c,restricted_transcription as r
from src.content_factory.corpus_screenplay_v1 import read,freeze
from src.content_factory.serial_story_runtime_v2 import run_lock

def prepare(run,prior,effort='medium',max_tokens=16384,authorization=None):
    if effort not in ('low','medium','high','xhigh','max'):raise ValueError('invalid_effort')
    if type(max_tokens) is not int or not 4096<=max_tokens<=32768:raise ValueError('invalid_output_budget')
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status'] in ('running','prepared','outcome_unknown'):raise ValueError('prior_not_terminal')
    run.mkdir(exist_ok=False)
    plan.update(route='isolated_nodes',version='isolated_nodes_v1',max_calls=state['calls_started']+3,
                baseline_calls=state['calls_started'],baseline_tokens=state['reported_tokens'])
    plan.pop('isolated_review_only',None)
    plan.pop('isolated_picture_only',None)
    plan['inference']={**plan['inference'],'writer_effort':effort,'writer_max_tokens':max_tokens}
    for key in ('review_failed_picture_only','review_existing_picture_only','preserve_source_facts'):plan.pop(key,None)
    paths=[Path(__file__),Path(n.__file__),Path(a.__file__),Path(r.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for name in ('SOURCE','INPUT','BACKGROUND'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    freeze(run/'PLAN.json',plan)
    freeze(run/'AUTHORIZATION.json',{'user':authorization or '提示词可能会出现返回需求串用的可能吗，这样也不多花token的花就按我说的来试试吧',
        'scope':'独立提示/独立请求，声音、画面、审核各一次，同原文19前情/20—21目标；不加反思重试，无媒体发布',
        'prior':str(prior),'baseline_calls':state['calls_started'],'max_calls':plan['max_calls'],
        'effort':effort,'max_output_tokens':max_tokens})
    state.update(status='prepared',stage=None,completed_stages=[]);TextLedger(run,plan,state,None).save()


def prepare_picture(run,prior,audio_from,authorization):
    """New bounded picture/review trial; bind an unchanged known audio result."""
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status'] in ('running','prepared','outcome_unknown'):
        raise ValueError('prior_not_terminal')
    if not authorization or not authorization.strip():raise ValueError('authorization_required')
    packet=read(prior/'INPUT.json');raw=read(audio_from/'audio_DIRECT_DECODED.json')
    if read(audio_from/'INPUT.json')!=packet:raise ValueError('audio_source_mismatch')
    bank=read(audio_from/'AUDIO_BANK.json')
    if a.build_bank(raw,packet)!=bank:raise ValueError('audio_bank_not_native')
    if read(prior/'AUDIO_BANK.json')!=bank:raise ValueError('prior_audio_changed')
    calls=[p for p in audio_from.glob('CALL_*.json') if read(p).get('stage')=='audio']
    if len(calls)!=1:raise ValueError('audio_receipt_ambiguous')
    number=int(calls[0].stem.split('_')[-1])
    if number>state['calls_started']:raise ValueError('audio_from_future_ledger')
    from src.content_factory.novel_adaptation.stream_evidence import audit_folder
    if audit_folder(audio_from/f'native_{number}')['completion_evidence']!='known':raise ValueError('unknown_audio')
    native=read(audio_from/f'RESPONSE_{number}.json')['native']
    tools=native['choices'][0]['message'].get('tool_calls',[])
    if len(tools)!=1 or json.loads(tools[0]['function']['arguments'])!=raw:raise ValueError('native_audio_mismatch')
    run.mkdir(exist_ok=False)
    for key in ('isolated_review_only','review_failed_picture_only','review_existing_picture_only','preserve_source_facts'):
        plan.pop(key,None)
    plan.update(route='isolated_nodes',version='isolated_picture_channels_v2',isolated_picture_only=True,
                max_calls=state['calls_started']+2,baseline_calls=state['calls_started'],baseline_tokens=state['reported_tokens'])
    paths=[Path(__file__),Path(n.__file__),Path(a.__file__),Path(r.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for name in ('SOURCE','INPUT','BACKGROUND'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    freeze(run/'AUDIO_BANK.json',bank);freeze(run/'audio_DIRECT_DECODED.json',raw)
    freeze(run/'REUSED_AUDIO.json',{'prior':str(audio_from),'call':number,'bank_sha256':c.digest(bank),
                                 'raw_sha256':c.digest(raw),'semantic_acceptance':False,'regenerate':False})
    freeze(run/'AUTHORIZATION.json',{'user':authorization,'scope':'同完整原文与原声音，画面及审核各一次；不生成声音、媒体或发布',
                                    'prior':str(prior),'baseline_calls':state['calls_started'],'max_calls':plan['max_calls']})
    freeze(run/'PLAN.json',plan)
    state.update(status='prepared',stage=None,completed_stages=[]);TextLedger(run,plan,state,None).save()


def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for f,h in plan['implementation_pin'].items():
            if hashlib.sha256(Path(f).read_bytes()).hexdigest()!=h:raise ValueError('changed_code')
        client=NativeClient(run,plan);strict=DirectLedger(run,plan,state,client);text=TextLedger(run,plan,state,client)
        packet=read(run/'INPUT.json')
        try:
            if plan.get('isolated_review_only'):
                bank=read(run/'AUDIO_BANK.json');layout=(run/'layout.txt').read_text('utf-8');gaps=read(run/'GAPS.json');validation=read(run/'LAYOUT_VALIDATION.json')
                candidate={'rendered':False,'raw_picture':layout,'audio_text':{i['audio_id']:i['text'] for i in bank['items']}}
                review=text.call('comparison','writer',n.REVIEW,n.review_payload(packet,bank,candidate,gaps,validation),c.obj(text=c.TEXT))
                (run/'review.md').write_text(review['text'],encoding='utf-8')
                freeze(run/'REVIEW_BINDING.json',{'candidate_sha256':c.digest(candidate),'layout_sha256':c.digest(layout),'audio_sha256':c.digest(bank),'gaps_sha256':c.digest(gaps),'rendered':False,'semantic_acceptance':False})
                state['completed_stages'].append('comparison');state['status']='failed_picture_reviewed_awaiting_primary'
                return
            if plan.get('isolated_picture_only'):
                audio=read(run/'audio_DIRECT_DECODED.json');bank=read(run/'AUDIO_BANK.json');binding=read(run/'REUSED_AUDIO.json')
                if a.build_bank(audio,packet)!=bank or c.digest(bank)!=binding['bank_sha256'] or c.digest(audio)!=binding['raw_sha256']:
                    raise ValueError('reused_audio_changed')
                state['completed_stages'].append('audio_reused');strict.save()
            else:
                audio=strict.call('audio','writer',n.AUDIO,n.audio_payload(packet),a.schema(packet))
                bank=a.build_bank(audio,packet);freeze(run/'AUDIO_BANK.json',bank)
                state['completed_stages'].append('audio');strict.save()
            raw=strict.call('picture','writer',n.PICTURE,n.picture_payload(packet,bank),n.picture_schema(packet))
            n.validate_picture(raw,packet);layout=raw['text'];freeze(run/'GAPS.json',raw['gaps'])
            (run/'layout.txt').write_text(layout,encoding='utf-8')
            validation=a.render_layout(layout,bank,packet);freeze(run/'LAYOUT_VALIDATION.json',validation)
            if not validation['format_passed']:raise ValueError('picture_contract_failed')
            candidate=r.render_background(read(run/'BACKGROUND.json'))+'\n\n# 独立节点生成候选（未验收）\n\n'+validation['rendered']
            (run/'screenplay.md').write_text(candidate,encoding='utf-8')
            state['completed_stages'].append('picture');strict.save()
            review=text.call('comparison','writer',n.REVIEW,n.review_payload(packet,bank,candidate,raw['gaps'],validation),c.obj(text=c.TEXT))
            (run/'review.md').write_text(review['text'],encoding='utf-8')
            freeze(run/'REVIEW_BINDING.json',{'candidate_sha256':c.digest(candidate),'audio_sha256':c.digest(bank),'gaps_sha256':c.digest(raw['gaps']),'semantic_acceptance':False})
            state['completed_stages'].append('comparison');state['status']='awaiting_primary_full_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:3000]})
        finally:text.save()

def prepare_review(run,prior):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status']!='needs_attention':raise ValueError('not_known_failure')
    if read(prior/'ERROR.json')['message']!='picture_contract_failed':raise ValueError('wrong_failure')
    if state['calls_started']+1>plan['max_calls']:raise ValueError('window_exhausted')
    from src.content_factory.novel_adaptation.stream_evidence import audit_folder
    number=state['calls_started']
    if audit_folder(prior/f'native_{number}')['completion_evidence']!='known':raise ValueError('unknown_picture')
    raw=read(prior/'picture_DIRECT_DECODED.json');native=read(prior/f'RESPONSE_{number}.json')['native']
    calls=native['choices'][0]['message'].get('tool_calls',[])
    if len(calls)!=1 or json.loads(calls[0]['function']['arguments'])!=raw:raise ValueError('native_mismatch')
    layout=(prior/'layout.txt').read_text('utf-8')
    if raw['text']!=layout or raw['gaps']!=read(prior/'GAPS.json'):raise ValueError('saved_picture_mismatch')
    if read(prior/'LAYOUT_VALIDATION.json')['layout_sha256']!=c.digest(layout):raise ValueError('diagnostic_mismatch')
    run.mkdir(exist_ok=False)
    for name in ('SOURCE','INPUT','BACKGROUND','AUDIO_BANK','GAPS','LAYOUT_VALIDATION','AUTHORIZATION'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    (run/'layout.txt').write_text(layout,encoding='utf-8')
    paths=[Path(__file__),Path(n.__file__),Path(a.__file__),Path(r.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan.update(isolated_review_only=True,version='isolated_nodes_raw_review_v1',implementation_pin={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    freeze(run/'PLAN.json',plan);freeze(run/'KNOWN_PICTURE.json',{'prior':str(prior),'call':number,'raw_sha256':c.digest(raw),'no_regeneration':True})
    state.update(status='prepared',stage=None);TextLedger(run,plan,state,None).save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute','prepare-review','prepare-picture']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);p.add_argument('--audio-from',type=Path);p.add_argument('--authorization');p.add_argument('--writer-effort',choices=['low','medium','high','xhigh','max'],default='medium');p.add_argument('--writer-max-tokens',type=int,default=16384);x=p.parse_args()
    if x.command=='prepare':prepare(x.run,x.prior,x.writer_effort,x.writer_max_tokens,x.authorization)
    elif x.command=='prepare-review':prepare_review(x.run,x.prior)
    elif x.command=='prepare-picture':prepare_picture(x.run,x.prior,x.audio_from,x.authorization)
    else:execute(x.run)
