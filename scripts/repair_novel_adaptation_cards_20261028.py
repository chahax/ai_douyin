"""Use the two remaining card-trial calls for explicit defects, not regeneration."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.repair import schema_for,apply_proposal

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT/'data/corpus_production_trials/20261028_adaptation_cards_v2'
RUN=ROOT/'data/corpus_production_trials/20261028_adaptation_cards_targeted'
FINDINGS={
 'identity':{'juweihui':'居委会在此作为监督机构，不是实际到场地点。',
   'su-mo-parents':'父母是两人的集合，不是单一可表演人物。',
   'bread':'当前记录同时引章1路人赠予和章3购买面包，应标明物类，不能当同一块面包实例。'},
 'character':{'F034':'前几天叶南提出，今天叶东坚持；效仿叶东的因果无据。',
   'F035':'原文老六死活不要二哥的钱，不能写先给了弟弟。',
   'F055':'此处是苏墨回顾原书以后眼伤，并非当前人物已受眼伤的过去。',
   'F056':'当前眼睛完好，原书未来的拖伤致盲不能标当前线past。'},
 'environment':{'ENV-008':'原文只确认厨房门被关，后续门缝偷窥未明确是厨房门；不要合并为同一门。'},
 'event':{'E006':'老六拒收因为不愿二哥挨打，宁可挨打的是二哥与原文相反。',
   'E010':'老二叶南是未来金融大佬，老六叶西决是未来神医，当前记录反了。',
   'E021':'米袋是如果不到月底空则受罚，不能把条件写成必然。'}}
ADDITIONS={'su-mo-bedroom','siblings-room'}


def main():
    prior=read(PARENT/'STATE.json')
    if prior['pending'] is not None or prior['calls_started']!=4:raise ValueError('parent_not_known_four_calls')
    RUN.mkdir(exist_ok=False)
    source=read(PARENT/'SOURCE.json');plan=read(PARENT/'PLAN.json')
    plan.update(max_calls=2,version='novel_adaptation/targeted-card-repair',source_sha256=digest(source))
    banks={k:read(PARENT/(k+'_BOUND.json'))['candidate'] for k in ('identity','character','environment','event')}
    freeze(RUN/'PLAN.json',plan);freeze(RUN/'SOURCE.json',source);freeze(RUN/'BEFORE.json',banks)
    freeze(RUN/'AUTHORIZATION.json',{'user':'重构为长任务并实测','original_card_bound':8,
        'used_v1b':2,'used_v2':4,'remaining':2,'media':False,'findings':FINDINGS})
    freeze(PARENT/'BUDGET_TRANSFER.json',{'child':str(RUN),'used':4,'remaining':2,'original_card_total_used':6})
    state={'status':'prepared','calls_started':0,'reported_tokens':0,'pending':None}
    ledger=Ledger(RUN,plan,state,NativeClient(RUN,plan));ledger.save()
    try:
        selected=[]
        for bank,issues in FINDINGS.items():
            root='entities' if bank=='identity' else 'facts'
            for row in banks[bank][root]:
                if row['id'] in issues:selected.append({'bank':bank,'record':row,'issue_to_check':issues[row['id']]})
        proposal=ledger.call('CARD_PATCH','writer',
            '对照完整原文核对并修复指定记录。仅返回这些记录，保持id，其他内容由程序原样保留。'
            '实体display_name可整理，来源使用原段ID。身份记录新增的两个地点分别对应苏墨醒来所在屋、叶嫣儿给老六上药的另一间屋；不推定睡觉分配或空间朝向。'
            '纠正意见也需按原文判断，不加入无据事实。',
            {'complete_chapters':c.indexed_chapters(source),'entities':banks['identity'],
             'records':selected,'required_addition_ids':sorted(ADDITIONS)},schema_for(source,banks,FINDINGS,ADDITIONS))
        after=apply_proposal(banks,proposal,FINDINGS,ADDITIONS,source)
        freeze(RUN/'AFTER.json',after)
        state['status']='patched_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(RUN/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:2000]})
    finally:ledger.save()

if __name__=='__main__':main()
