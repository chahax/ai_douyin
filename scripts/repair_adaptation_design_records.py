"""Repair only reviewed design record fields, carrying the cumulative ledger."""
import argparse,sys
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c,scenes as sc


def apply(design,proposal,scope):
    out=deepcopy(design);seen=set()
    expected={(group,key) for group,rows in scope['records'].items() for key in rows}
    for row in proposal['corrections']:
        key=(row['group'],row['id'])
        if key not in expected or key in seen:raise ValueError('record_scope')
        seen.add(key);allowed=scope['records'][key[0]][key[1]]['fields']
        if set(row['changes'])!=set(allowed):raise ValueError('field_scope')
        target=next(r for r in out[key[0]] if r['id']==key[1]);target.update(deepcopy(row['changes']))
    if seen!=expected:raise ValueError('record_coverage')
    return out


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','run','scope'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--ledger-prior',type=Path)
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    source=read(a.prior/'SOURCE.json');packet=read(a.prior/'PACKET.json');design=read(a.prior/'DESIGN_COMPILED.json');scope=read(a.scope)
    if scope['design_sha256']!=digest(design) or scope['source_sha256']!=digest(source):raise ValueError('scope_stale')
    ledger_path=a.ledger_prior or a.prior
    if a.ledger_prior:
        old=read(a.ledger_prior/'STATE.json')
        if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('ledger_prior_not_terminal')
    specs={'objective':c.TEXT,'duration_seconds':{'type':'integer','minimum':1,'maximum':180},
           'action':c.TEXT,'inputs':c.array(c.TEXT,1),'retained_inputs':c.array(c.TEXT)}
    fields={};addresses={}
    for group,rows in scope['records'].items():
        if group not in ('scenes','recipes'):raise ValueError('invalid_group')
        for key,info in rows.items():
            address=group+'__'+key;addresses[address]=(group,key)
            fields[address]=c.obj(**{f:specs[f] for f in info['fields']})
    schema=c.obj(records=c.obj(**fields))
    plan=read(a.prior/'PLAN.json');plan['max_calls']=old['calls_started']+1
    a.run.mkdir(parents=True,exist_ok=False)
    for name,obj in [('SOURCE',source),('PACKET',packet),('BEFORE',design),('SCOPE',scope),('PLAN',plan)]:freeze(a.run/(name+'.json'),obj)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'state_sha256':digest(old),'calls_carried':old['calls_started'],
        'ledger_prior':str(ledger_path),
        'tokens_carried':old['reported_tokens'],'engineering_extension':1,'authorization':'MiniMax同书文本持续授权，无媒体或旧任务重派'})
    snap=a.run/'implementation';snap.mkdir()
    for f in list(Path('src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]: (snap/f.name).write_bytes(f.read_bytes())
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        proposal=ledger.call('DESIGN_RECORD_PATCH','writer','''只修改scope指定记录的指定字段。其他字段由程序原样保留，不返回。
保持正确剧情信息，不扩写新事件。条件句、原主身份、食材加工前后状态严格对照原文。成品炖菜已经含熟肉，分餐从成品取肉；原生肉加工后消耗，不再当作分餐原料。
制作动作只安排一次，后场承接已切片下锅的状态。原文未描述白米饭可作为普通影视补足，但不要扩大为新剧情。duration_seconds依实际信息量估算，不用静默凑时长。
按records固定键返回对应字段；duration_seconds是JSON整数，inputs/retained_inputs是JSON字符串数组，空数组为[]，不是空字符串或item包装对象。
米袋原文是如果没到月底就空了会被惩罚，不要改写为每回已经发生的事实或原主的惯常设想；这处背景在本场不必重复解释，保持原条件和归属即可。''',
            {'complete_chapters':c.indexed_chapters(source),'design':{k:v for k,v in design.items() if k not in ('source_constraints','world_framework')},'scope':scope},schema)
        errors=c.schema_issues(proposal,schema,'record_patch')
        if errors:raise c.ContractError(errors)
        proposal={'corrections':[{'group':addresses[key][0],'id':addresses[key][1],'changes':value} for key,value in proposal['records'].items()]}
        freeze(a.run/'BOUND_RECORD_PATCH.json',proposal)
        out=apply(design,proposal,scope);sc.initial_state(out,{'entities':packet['entities']})
        freeze(a.run/'DESIGN_COMPILED.json',out);state['status']='design_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
