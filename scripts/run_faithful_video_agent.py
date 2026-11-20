"""Full text-agent iteration; model reviews never authorize release."""
import argparse,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c,faithful_video_contract as f
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient
from src.content_factory.serial_story_runtime_v2 import run_lock

class TextLedger(DirectLedger):
    def call(self,name,role,prompt,payload,schema):
        try:return super().call(name,role,prompt,payload,schema)
        except RuntimeError as exc:
            if str(exc)!='native_tool_submission_missing' or self.state['pending'] is not None:raise
            n=self.state['calls_started'];native=read(self.run/f'RESPONSE_{n:03}.json')['native'];choice=native['choices'][0]
            from src.content_factory.novel_adaptation.stream_evidence import audit_folder
            if audit_folder(self.run/f'native_{n:03}')['completion_evidence']!='known':raise
            msg=choice['message'];text=msg.get('content')
            if choice['finish_reason']!='stop' or msg.get('tool_calls') or not isinstance(text,str) or not text.strip():raise
            value={'text':text};freeze(self.run/(name+'_TEXT_ADOPTION.json'),{'native_sha256':digest(native),'mapping':'entire content to text, unchanged','semantic_acceptance':False})
            freeze(self.run/(name+'_DIRECT_DECODED.json'),value);return value

def continue_known(run,prior):
    old=read(prior/'STATE.json');plan=read(prior/'PLAN.json')
    if old['pending'] is not None or old['calls_started']!=291 or read(prior/'ERROR.json')['message']!='native_tool_submission_missing':raise ValueError('unsupported_adoption')
    from src.content_factory.novel_adaptation.stream_evidence import audit_folder
    native=read(prior/'RESPONSE_291.json')['native'];choice=native['choices'][0]
    if audit_folder(prior/'native_291')['completion_evidence']!='known' or choice['finish_reason']!='stop' or choice['message'].get('tool_calls'):raise ValueError('unknown_adoption')
    run.mkdir(exist_ok=False)
    for name in ['SOURCE','INPUT','ADJUSTMENT','AUTHORIZATION','EVALUATION']:freeze(run/(name+'.json'),read(prior/(name+'.json')))
    plan['implementation_pin']={str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,f.__file__]};freeze(run/'PLAN.json',plan)
    value={'text':choice['message']['content']};freeze(run/'understanding_DIRECT_DECODED.json',value)
    freeze(run/'KNOWN_ADOPTION.json',{'prior':str(prior),'native_sha256':digest(native),'stage':'understanding','semantic_acceptance':False})
    (run/'understanding.md').write_text(value['text'],encoding='utf-8')
    old.update(status='prepared',completed_stages=['understanding']);DirectLedger(run,plan,old,None).save()

def prepare(run,prior,authorization=None,diagnosis=None):
    old=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json')
    retained=list(old.get('retained_unknowns',[]))
    if old['pending'] is not None:
        auth=read(authorization) if authorization else {}
        if old['pending']!=290 or auth.get('call')!=290 or auth.get('decision')!='retain_unknown_no_longer_wait':raise ValueError('unknown_disposition_required')
        if auth.get('prior_state_sha256')!=digest(old):raise ValueError('disposition_state_mismatch')
        retained.append({'call':290,'prior':str(prior),'state_sha256':digest(old),'usage':None,'disposition':auth})
    elif old['status'] in ['prepared','running']:raise ValueError('prior_active')
    iteration=2 if diagnosis else 1
    adjustment=read(diagnosis) if diagnosis else {'cause':'商业改编模板与忠实视频转写目标冲突','change':'统一忠实边界，分离理解、场景、正文、两种审核和承接','prompt_addition':''}
    if iteration==2:
        if old.get('iteration')!=1 or old['pending'] is not None or not adjustment.get('cause') or not adjustment.get('change'):raise ValueError('first_round_diagnosis_required')
    run.mkdir(exist_ok=False)
    ceiling=plan['max_calls'] if iteration==2 else old['calls_started']+14
    plan.update(version='faithful_video_agent_v'+str(iteration),max_calls=ceiling,iteration=iteration,
      baseline_calls=plan['baseline_calls'] if iteration==2 else old['calls_started'],
      baseline_tokens=plan['baseline_tokens'] if iteration==2 else old['reported_tokens'])
    plan['implementation_pin']={str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,f.__file__]}
    packet=f.source_packet(source,[19],[20,21])
    if iteration==2 and packet!=read(prior/'INPUT.json'):raise ValueError('comparison_source_changed')
    for name,value in [('PLAN',plan),('SOURCE',source),('INPUT',packet),('ADJUSTMENT',adjustment),('AUTHORIZATION',{'user':'允许保留290未知记录，继续两轮完整Agent测试','disposition':read(authorization) if authorization else None,'prior':str(prior),'scope':'MiniMax text only, full workflow twice, no media or publishing'}),('EVALUATION',{'not_sent_to_model':True,'checks':['人物核心关系','原文事件因果顺序','对话主体含义','条件与知情','完整画面声音表达','跨场衔接','合理表现补足不硬判错'],'second_round_requires_causal_change':True})]:freeze(run/(name+'.json'),value)
    state={'status':'prepared','pending':None,'calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],'retained_unknowns':retained,'reported_usage_complete':False,'iteration':iteration,'completed_stages':[]}
    DirectLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        ledger=TextLedger(run,plan,state,NativeClient(run,plan));results={};packet=read(run/'INPUT.json')
        try:
            for stage in f.STAGES:
                if stage in state['completed_stages']:
                    results[stage]=read(run/(stage+'_DIRECT_DECODED.json'))['text'];continue
                inputs=f.stage_inputs(packet,results,stage,state['iteration'])
                prompt=f.stage_prompt(stage,state['iteration'])+'\n'+read(run/'ADJUSTMENT.json').get('prompt_addition','')+'\n只输出text字段内本阶段文字，不提前代做其他阶段。'
                value=ledger.call(stage,'writer',prompt,inputs,c.obj(text=c.TEXT));results[stage]=value['text']
                (run/(stage+'.md')).write_text(value['text'],encoding='utf-8')
                if stage.endswith('_review') or stage=='handoff':freeze(run/(stage+'_BINDING.json'),f.bind_review(results['screenplay'],value))
                state['completed_stages'].append(stage);ledger.save()
            state['status']='awaiting_primary_full_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:2000]})
        finally:ledger.save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute','continue-known']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);p.add_argument('--authorization',type=Path);p.add_argument('--diagnosis',type=Path);a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior,a.authorization,a.diagnosis)
    elif a.command=='continue-known':continue_known(a.run,a.prior)
    else:execute(a.run)
