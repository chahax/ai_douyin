"""Read-only content validation of existing candidates; never auto-release prose."""
import argparse,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.produce_serial_prose import SerialLedger
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.protocol_direct import NativeClient
from src.content_factory.serial_story_runtime_v2 import run_lock

def prepare(run,prior):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if state['pending'] is not None or state['status'] in ('running','prepared','outcome_unknown'):raise ValueError('prior_not_settled')
    run.mkdir(exist_ok=False)
    baseline=state['calls_started'];tokens=state['reported_tokens']
    ceiling=plan['max_calls'] if plan.get('version')=='complete_candidate_validation_v1' else baseline+4
    plan.update(version='complete_candidate_validation_v1',max_calls=ceiling,baseline_calls=baseline,baseline_tokens=tokens)
    plan['inference']={**plan['inference'],'writer_max_tokens':16384}
    paths=[__file__,'scripts/produce_serial_prose.py','src/content_factory/novel_adaptation/protocol_direct.py']
    plan['implementation_pin']={str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    for name in ('SOURCE','REGISTRY'):freeze(run/(name+'.json'),read(prior/(name+'.json')))
    for n,name in [(1,'EPISODE_01_FIELD_REPAIRED.json'),(7,'EPISODE_07_REPAIRED.json')]:
        path=prior/name
        if not path.exists():path=prior/f'CANDIDATE_{n:02}.json'
        value=read(path);freeze(run/f'CANDIDATE_{n:02}.json',value)
    freeze(run/'PLAN.json',plan)
    freeze(run/'AUTHORIZATION.json',{'user_statement':'生产验证','prior':str(prior.resolve()),'prior_state_sha256':digest(state),
        'scope':'MiniMax read-only complete episode1/7 validation with original chapters1/2 and12/13; no media or publishing',
        'max_new_calls':ceiling-baseline,'planned_calls':2,'automatic_semantic_release':False})
    state.update(status='prepared',pending=None,baseline_calls=baseline,baseline_tokens=tokens,validated_candidates=0)
    SerialLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for p,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha:raise ValueError('code_changed')
        source=read(run/'SOURCE.json');registry=read(run/'REGISTRY.json')
        ledger=SerialLedger(run,plan,state,NativeClient(run,plan))
        try:
            for n,chapters in [(1,[1,2]),(7,[12,13])]:
                candidate=read(run/f'CANDIDATE_{n:02}.json')
                payload={'candidate_sha256':digest(candidate),'candidate':candidate,'reviewed_identity_subset':registry,
                    'complete_source_chapters':[x for x in c.indexed_chapters(source) if x['index'] in chapters],
                    'scope':'第1集改编1—2章；第7集改编13章，12章仅作事件和时间上下文。人物卡是部分核对资料，不代表整稿已审核。'}
                result=ledger.call(f'AUDIT_{n:02}','writer',
                    '对当前完整剧本做生产验收审查。先通读完整原文，再逐场核查稿件。不要套用历史意见。'
                    '检查人物年龄/称谓/身份，进出与在场，条件/否定/猜测是否被当事实，时间顺序、道具及知情关系。'
                    '区分无害的表演/布景补足与改变原文事件因果的新增剧情。不能只因未逐字复制便判错误。'
                    '每个硬伤给当前稿精确短引文、原文段落编号与原句、因果解释及影响范围；无法确定列疑问，不硬判。'
                    '同时评估开场信息、重复旁白、可拍性及完整时长，说明对白/心声语速假设和动作时间，原稿无时码时只能估算。'
                    '只返回精炼审核结果，最多2000汉字；无问题处不逐句复述。最后明确通过/不通过/证据不足，且说明是否逐场完成。'
                    '不改写正文，不把审核建议当已修复。正文和continuity承接摘要同等检查。',payload,c.obj(review=c.TEXT))
                freeze(run/f'AUDIT_{n:02}_BOUND.json',{'candidate_sha256':digest(candidate),'source_sha256':digest(source),'result':result,'advisory_only':True})
                (run/f'第{n}集_模型完整审查.md').write_text(result['review'],encoding='utf-8')
                state['validated_candidates']+=1;ledger.save()
            state['status']='awaiting_primary_validation'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:2500]})
        finally:ledger.save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior)
    else:execute(a.run)
