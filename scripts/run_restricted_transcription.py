"""Two explicit development rounds, each source -> transcription -> comparison."""
import argparse,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_faithful_video_agent import TextLedger,NativeClient
from src.content_factory.corpus_screenplay_v1 import read,freeze
from src.content_factory.novel_adaptation import audiovisual_transcription as a,restricted_transcription as r,contracts as c
from src.content_factory.novel_adaptation import screen_continuity as sc
from src.content_factory.serial_story_runtime_v2 import run_lock

def prepare(run,prior,round_number,diagnosis=None):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json')
    if state['pending'] is not None or state['status'] in ['prepared','running','outcome_unknown']:raise ValueError('prior_not_terminal')
    if round_number not in (1,2):raise ValueError('invalid_round')
    if round_number==2:
        if plan.get('route')!='restricted_transcription' or plan['round']!=1:raise ValueError('wrong_prior')
        if not diagnosis or not read(diagnosis).get('cause') or not read(diagnosis).get('change'):raise ValueError('causal_diagnosis_required')
        if state['calls_started']+2>plan['max_calls']:raise ValueError('window_exhausted')
    packet=a.packet(source,[19],[20,21])
    if round_number==2 and packet!=read(prior/'INPUT.json'):raise ValueError('different_source')
    run.mkdir(exist_ok=False)
    if round_number==1:
        plan.update(max_calls=state['calls_started']+4,baseline_calls=state['calls_started'],baseline_tokens=state['reported_tokens'])
    plan.update(route='restricted_transcription',round=round_number,version='restricted_transcription_v'+str(round_number),chapter_indices=[20,21],context_chapter_indices=[19])
    paths=[Path(__file__),Path(r.__file__),Path(a.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for name,value in [('PLAN',plan),('SOURCE',source),('INPUT',packet),('BACKGROUND',r.background(packet)),
        ('AUTHORIZATION',{'user':'嗯，检查流程后再修改2轮','scope':'同源MiniMax文本两轮开发测试，各2次，累计边界304到308；无媒体发布'}),
        ('DIAGNOSIS',read(diagnosis) if diagnosis else {'cause':'背景和演出仍自由编写，心理和对白归属混合','change':'背景程序原文引用，心理只用旁白，视听行分型'})]:freeze(run/(name+'.json'),value)
    state.pop('iteration',None);state.update(status='prepared',completed_stages=[],stage=None,round=round_number)
    TextLedger(run,plan,state,None).save()

def prepare_focus(run,prior,focus='semantic_coverage'):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json');original=read(prior/'INPUT.json')
    if state['pending'] is not None or state['status'] in ['prepared','running','outcome_unknown']:raise ValueError('prior_not_terminal')
    if plan.get('route')!='restricted_transcription':raise ValueError('wrong_prior')
    if focus not in ['semantic_coverage','source_locations','screen_continuity']:raise ValueError('invalid_focus')
    run.mkdir(exist_ok=False)
    plan.update(version='restricted_'+focus+'_v1',round=2,focus=focus,max_calls=state['calls_started']+2,
                baseline_calls=state['calls_started'],baseline_tokens=state['reported_tokens'])
    paths=[Path(__file__),Path(r.__file__),Path(a.__file__),Path('scripts/run_faithful_video_agent.py')]
    if focus=='screen_continuity':
        plan['max_calls']=state['calls_started']+3
        paths.extend([Path(sc.__file__),Path('tests/fixtures/screen_continuity_cases.json')])
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    authorization={'user':'行','scope':'逐点处理第一项：连续事件覆盖替代逐排版段强制音画，MiniMax完整同章转写与审核各一次，308到310工程窗口；不改地点/归属规则','prior':str(prior)}
    diagnosis={'cause':'每个目标段强制音画可能诱发标点被解释为动作','change':'覆盖单位改事件含义，纯省略号提供原始邻文提示，不自动判断含义','comparison_limit':'此前已离线修复编号示例及标点校验，本次同时使用；不是只改一项的严格模型消融'}
    if focus=='source_locations':
        authorization={'user':'好','scope':'逐点第二项：地点原文出处与空间关系审核，同章MiniMax转写/审核各一次；310到312工程窗口，不改人物归属','prior':str(prior)}
        diagnosis={'cause':'地点字段为自由文本，仅校验存在；转写将前文商场与后文便利店拼接，模型审漏报','change':'地点原段与连续原词验证，独立审核收到逐场地点原句证据；不把词语命中当场所语义成立'}
    if focus=='screen_continuity':
        authorization={'user':'嗯嗯','scope':'通用过渡省略与保留画面一致性规则；沿既有MiniMax同源授权，3次文本调用：合成对照判断、完整同章转写、审查；工程312→315，无媒体/发布','prior':str(prior)}
        diagnosis={'cause':'实际是一次完整生成，没有程序逐场传输；已证实地点出处不足以判断当前位置，不能把独立出门镜头当必需。','change':'普通地点描述，允许合并/省略过渡，判断保留画面是否与原文冲突；对白完整性另列。','limit':'新规则仍依靠模型语义判断；合成对照非小说留出，未实现状态引擎。'}
        freeze(run/'PROBE_CASES.json',read(Path('tests/fixtures/screen_continuity_cases.json')))
    for name,value in [('PLAN',plan),('SOURCE',read(prior/'SOURCE.json')),('INPUT',original),('BACKGROUND',read(prior/'BACKGROUND.json')),
        ('COVERAGE_GUIDANCE',r.coverage_guidance(original)),
        ('AUTHORIZATION',authorization),('DIAGNOSIS',diagnosis)]:freeze(run/(name+'.json'),value)
    state.update(status='prepared',completed_stages=[],stage=None)
    TextLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        ledger=TextLedger(run,plan,state,NativeClient(run,plan));original=read(run/'INPUT.json')
        payload=dict(original)
        if plan.get('focus') in ['semantic_coverage','source_locations','screen_continuity']:payload['coverage_guidance']=read(run/'COVERAGE_GUIDANCE.json')
        try:
            if plan.get('focus')=='screen_continuity':
                cases=read(run/'PROBE_CASES.json')
                probe=ledger.call('continuity_probe','writer',sc.probe_prompt(),{'cases':[{k:v for k,v in case.items() if k!='expected'} for case in cases]},c.obj(text=c.TEXT))
                freeze(run/'PROBE_SCORE.json',sc.score_probe(probe['text'],cases))
                (run/'probe.txt').write_text(probe['text'],encoding='utf-8')
                state['completed_stages'].append('continuity_probe');ledger.save()
            prompt=r.location_prompt(original) if plan.get('focus')=='source_locations' else r.prompt(plan['round'],original)
            if plan.get('focus')=='screen_continuity':prompt=sc.author_prompt(original)
            text=ledger.call('transcription','writer',prompt,payload,c.obj(text=c.TEXT))['text']
            (run/'transcription.txt').write_text(text,encoding='utf-8')
            candidate=r.render_background(read(run/'BACKGROUND.json'))+'\n\n# 视听转写候选\n\n'+text
            (run/'screenplay.md').write_text(candidate,encoding='utf-8')
            validation=(r.anchored_diagnostics(text,original) if plan['round']==2 else r.validate(text,original));freeze(run/'VALIDATION.json',validation)
            state['completed_stages'].append('transcription');ledger.save()
            review_payload={**a.review_input(original,candidate),'format_diagnostics':validation}
            if plan.get('focus') in ['semantic_coverage','source_locations','screen_continuity']:review_payload['coverage_guidance']=payload['coverage_guidance']
            review_prompt=r.review_prompt(plan['round'])
            if plan.get('focus')=='source_locations':
                locations=r.location_diagnostics(text,original);freeze(run/'LOCATION_VALIDATION.json',locations)
                review_payload['location_diagnostics']=locations;review_prompt=r.location_review_prompt()
            if plan.get('focus')=='screen_continuity':
                integrity=sc.dialogue_integrity(text);freeze(run/'DIALOGUE_INTEGRITY.json',integrity)
                review_payload['dialogue_integrity']=integrity;review_prompt=sc.review_prompt()
            review=ledger.call('comparison','writer',review_prompt,review_payload,c.obj(text=c.TEXT))
            (run/'review.md').write_text(review['text'],encoding='utf-8')
            freeze(run/'REVIEW_BINDING.json',{'candidate_sha256':c.digest(candidate),'review':review,'semantic_acceptance':False})
            state['completed_stages'].append('comparison');state['status']='awaiting_primary_full_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:2000]})
        finally:ledger.save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','prepare-focus','execute']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);p.add_argument('--round',type=int);p.add_argument('--diagnosis',type=Path);p.add_argument('--focus',choices=['semantic_coverage','source_locations','screen_continuity'],default='semantic_coverage');x=p.parse_args()
    if x.command=='prepare':prepare(x.run,x.prior,x.round,x.diagnosis)
    elif x.command=='prepare-focus':prepare_focus(x.run,x.prior,x.focus)
    else:execute(x.run)
