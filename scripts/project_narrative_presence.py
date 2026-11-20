"""Extract occupancy from a fixed candidate, then replay without rewriting prose."""
import argparse,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation.narrative_presence import schema,replay,body_schema,bind_body
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient
from src.content_factory.novel_adaptation import presence_evidence

ACCESS_PROMPT='''只分析固定候选中的镜头视点与跨空间视听，不修改人物位置、进出或剧本。
从evidence_catalog选择固定地址，不抄写引文。camera_cut是切换摄影视点，只使远端可见、不使角色互相听见；sightline是同一时点从门口等看见远端；hearing才产生听众范围。
每个区间选start/end锚点：before_audio或audio:编号。audio编号严格对应当前段音轨列表，从0起。start在该音轨开始前，end在该音轨结束后；before_audio仅表示音轨前。
确实有明确依据的才标explicit；需要推断人物开口与关门先后时标inferred或uncertain并说明。程序不会执行不确定关系，不要为了通过而强行标明确。
初始投影仅供查位置，旧sensory_windows不是事实依据。只有新的access会替换旧视听窗口。镜头硬切不表示门被打开；内心音轨也不是在房间里广播。'''


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','context','design','run'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--additional-calls',type=int,default=0)
    p.add_argument('--sensory-only',action='store_true')
    p.add_argument('--access-ids',action='store_true')
    p.add_argument('--program-bind',action='store_true',help='Bind candidate SHA from frozen INPUT, not model transcription.')
    a=p.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    candidate=read(a.prior/'CANDIDATE.json');source=read(a.prior/'SOURCE.json')
    packet=read(a.context/'PACKET.json');design=read(a.design/'EPISODE.json')['design']
    people=[e['id'] for e in packet['entities'] if e['kind']=='character'];places=[r['id'] for r in design['places']]
    if a.additional_calls<0:raise ValueError('negative_engineering_extension')
    ceiling=plan['max_calls'];plan.update(max_calls=max(ceiling,old['calls_started']+a.additional_calls))
    payload={'candidate':candidate,'candidate_sha256':digest(candidate),'people':people,'places':design['places'],
             'identity_labels':packet['entities']}
    previous=None
    if a.program_bind and (a.sensory_only or a.access_ids):raise ValueError('program_bind_full_projection_only')
    if a.sensory_only and a.access_ids:raise ValueError('choose_one_projection_mode')
    if a.sensory_only or a.access_ids:
        previous=read(a.prior/'PRESENCE_PROJECTION_ENVELOPE_DECODED.json')
        if previous['candidate_sha256']!=digest(candidate):raise ValueError('projection_candidate_mismatch')
        payload['previous_projection']=previous
        payload['repair_scope']='Only add sensory_windows to segment records; keep initial locations, moves, segment order and existing uncertainties unchanged. Additional uncertainties are allowed.'
    if a.access_ids:
        payload['evidence_catalog']={key:{k:v for k,v in value.items() if k!='text'}
            for key,value in presence_evidence.catalog(candidate).items()}
        # Exact text remains once in candidate; addresses resolve it losslessly.
        payload.pop('previous_projection',None)
        payload['previous_locations_and_moves']={'initial_locations':previous['initial_locations'],
            'segments':[{'id':r['id'],'moves':[{k:v for k,v in m.items() if k not in ('quote','evidence_field')}
                         for m in r['moves']]} for r in previous['segments']]}
    a.run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',source),('CANDIDATE',candidate),('INPUT',payload),('ENGINEERING_EXTENSION',{
        'prior':str(a.prior),'prior_state_sha256':digest(old),'old_ceiling':ceiling,'new_ceiling':plan['max_calls'],
        'net_additional':plan['max_calls']-ceiling,'calls_carried':old['calls_started'],'tokens_carried':old['reported_tokens'],
        'scope':'Authorized MiniMax text: candidate occupancy extraction and bounded independent verification; no unknown replay.'})]:freeze(a.run/(name+'.json'),value)
    implementation=a.run/'implementation';implementation.mkdir()
    manifest={}
    for f in [Path(__file__),Path('src/content_factory/novel_adaptation/narrative_presence.py'),
              Path('src/content_factory/novel_adaptation/scenes.py'),Path('src/content_factory/novel_adaptation/protocol_envelope.py'),
              Path('src/content_factory/novel_adaptation/presence_evidence.py')]:
        b=f.read_bytes();(implementation/f.name).write_bytes(b);manifest[str(f)]=hashlib.sha256(b).hexdigest()
    freeze(implementation/'MANIFEST.json',manifest)
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
           'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=StringEnvelopeLedger(a.run,plan,state,StringEnvelopeClient(a.run,plan));ledger.save()
    try:
        result=ledger.call('ACCESS_IDS' if a.access_ids else 'PRESENCE_PROJECTION','writer',ACCESS_PROMPT if a.access_ids else '''从固定完整候选提取人物位置和进出，不写剧本、不修复缺失动作。
逐段按原顺序返回全部segment_id。初始位置为第一段开始前位置，未出场的背景人物放__OFFSCREEN__。
visible_people仅表示镜头看见的人，不能推断未列的人已经离场。每个move必须有本段action或continuity_obligations中的精确引文；entry_continuity只用于该场第一段，exit_continuity只用于该场最后段。引文必须真能支持此人物的进出，不能借一句泛泛描写编造移动。
可选sensory_windows只描述有据的跨空间直达视听，例如门开时从过道看见并听见厨房内人物；不改变人物位置，不允许隔墙自动听见。place是远端地点；visible和audible分别设定；through_audio_index是窗口从本段开始持续到第几句音轨结束（零起始，-1只覆盖音轨前画面）。随后自动关闭且不延续到下段。每项quote必须精确来自本段action/camera/continuity_obligations。不能确定关门相对台词的顺序时列入uncertainties，不把推断当剧本明示。
phase=start表示本段音轨之前；end表示所有音轨之后；after_audio_index为零起始音轨编号。非after_audio时编号填null。
镜头有角色或有人开口，并不授权你补造他们进场；缺乏进出依据、起始位置不确定、矛盾都写uncertainties，不能为让状态通过而补写动作。同一个人未离开地点时，不因下个镜头换了地方而自动跟过去。
不把背景中的原著未来人物放进当前场。保留全部真实进出事件；如果台词或旁白角色在镜头外但仍在同一房间，仍保持位置。''',payload,presence_evidence.schema(candidate,places) if a.access_ids else (body_schema(candidate,people,places) if a.program_bind else schema(candidate,people,places)))
        if a.program_bind:
            result=bind_body(candidate,result,read(a.run/'INPUT.json')['candidate_sha256'],people,places)
            freeze(a.run/'PROGRAM_BOUND_PROJECTION.json',result)
        if a.access_ids:
            result,receipt=presence_evidence.compile_access(candidate,previous,result,places)
            freeze(a.run/'ACCESS_RESOLUTION.json',receipt)
            freeze(a.run/'PROJECTED_PRESENCE.json',result)
        if a.sensory_only:
            from copy import deepcopy
            reduced=deepcopy(result)
            for row in reduced['segments']:row.pop('sensory_windows',None)
            new_uncertainties=reduced.pop('uncertainties');original=deepcopy(previous)
            old_uncertainties=original.pop('uncertainties')
            if reduced!=original or new_uncertainties[:len(old_uncertainties)]!=old_uncertainties:
                raise ValueError('sensory_repair_changed_unselected_projection')
        freeze(a.run/'PRESENCE_REPLAY.json',replay(candidate,result,people,places))
        state['status']='projection_replayed_awaiting_semantic_coverage_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()


if __name__=='__main__':main()
