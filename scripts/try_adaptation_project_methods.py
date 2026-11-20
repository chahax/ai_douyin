"""Audited prompt-method probes; NOT a run of upstream applications/agents."""
import argparse, hashlib, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read, freeze, digest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger, NativeClient
from src.content_factory.serial_story_runtime_v2 import run_lock

ROOT=Path('data/research/20261029_adaptation_projects')
PRIOR=Path('data/corpus_production_trials/20261029_questioned_holdout_three_v4')
COMMON='''本次为真实小说忠实改编方法测试，只改编第20章的完整事件，19章仅作前情。
按原文事件顺序组织三个连续段落：夜谈至早餐出门、乘车至试衣、挑衣至预约送货离店。
不要按章号伪造集号。不强制固定时长。可以压缩重复说明，但须保留主要事件和人物关系。
允许表演、机位及自然口语补足；不得为了反转、钩子或人数限制新增事件、删掉必要人物、改时间、改行动对象。
若参考规范与本任务冲突，以以上忠实改编要求为准。未知信息不强行补成事实。
本次不调用外部工具，工具本可提供的原文和前阶段结果已完整附在输入中。
text字段承载本阶段完整文字；不要请求用户确认，不执行文件操作，不输出媒体。
'''

def bundles():
    scene=ROOT/'SceneCoAgent/data/skills'
    team=ROOT/'novel-to-script-team'
    return {
      'baseline':[
        ('understand','阅读完整目标章及前章，解释本次事件顺序、角色关系、动机和需要保留的条件及歧义。仅分析本次改编所需信息。',[]),
        ('plan','根据原文与分析规划三个连续段落，明确每段事件、人物、地点、时间承接及表现方法，不提前编写完整对白。',[]),
        ('write','根据原文与已有分析规划，写完整可拍剧本，明确人物动作神情与对白、旁白或心声，避免画面和旁白重复解释。',[])],
      'sceneco_method':[
        ('understand','根据完整原文为当前局部改编建立故事骨架。',[scene/'script_execution_skeleton.md']),
        ('plan','为当前三个连续段落建立改编策略。',[scene/'script_execution_adaptation.md']),
        ('write','编写本次三个连续段落的完整剧本。',[scene/'script_execution_script.md'])],
      'team_method':[
        ('understand','分析本次原文、人物关系与改编重点。',[team/'references/00-first-principles.md',team/'references/01-adaptation-system.md']),
        ('plan','规划本次三个连续段落，作为一个局部连载单元。',[team/'references/00-first-principles.md',team/'references/02-episode-architecture.md']),
        ('write','写本次三个连续段落的完整剧本。',[team/'references/00-first-principles.md',team/'references/03-script-writing-standard.md',team/'skills/script-writing-skill/SKILL.md'])]}

def prepare(run):
    old=read(PRIOR/'STATE.json');plan=read(PRIOR/'PLAN.json');source=read(PRIOR/'SOURCE.json')
    if old['pending'] is not None or old['status']!='holdout_complete_needs_revision':raise ValueError('prior_not_settled')
    run.mkdir(exist_ok=False)
    manifest={};arms={}
    for arm,stages in bundles().items():
        arms[arm]=[]
        for stage,instruction,files in stages:
            texts=[]
            for path in files:
                content=path.read_text(encoding='utf-8');manifest[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                texts.append(f'参考方法文件：{path.name}\n{content}')
            arms[arm].append({'stage':stage,'prompt':'\n\n'.join(texts)+'\n\n本次测试任务（优先于参考规范）：\n'+COMMON+'\n'+instruction})
    plan.update(version='upstream_prompt_methods_probe',baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'],max_calls=old['calls_started']+9)
    plan['implementation_pin']={str(Path(__file__).resolve()):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    source_subset=[ch for ch in source['chapters'] if ch['index'] in [19,20]]
    for name,value in [('PLAN',plan),('SOURCE',source),('INPUT',{'chapters':source_subset,'target_chapter':20}),('METHODS',arms),('UPSTREAM_MANIFEST',manifest),
      ('AUTHORIZATION',{'user':'试试','scope':'same authorized novel MiniMax text only; bounded 9 calls; no application deployment, no media','prior':str(PRIOR),'prior_state_sha256':digest(old)}),
      ('EVALUATION_FROZEN',{'not_sent':True,'known_regression_not_blind':True,'checks':['night private conversation separated from father next room','breakfast then same outing, not dusk','six children plus father; six seated father standing','two hands plus four ahead, then five boys trying clothes','like mother is not actual mother present','quantity CH20-P143 contextual distributive interpretation, retain punctuation ambiguity','delivery call and address arrangement not already delivered','no invented new conflict or speaker certainty'],'style':['natural speech','avoid redundant narration','clear action and expression'],'comparison':'3 stages per arm same source, model, effort, max output; one run each, prompts differ, not causal proof or full upstream execution'})]:freeze(run/(name+'.json'),value)
    state={**old,'status':'prepared','pending':None,'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'method_results':{}}
    DirectLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        ledger=DirectLedger(run,plan,state,NativeClient(run,plan))
        for arm,stages in read(run/'METHODS.json').items():
            previous={}
            try:
                for stage in stages:
                    name=arm+'_'+stage['stage']
                    value=ledger.call(name,'writer',stage['prompt'],{**read(run/'INPUT.json'),'this_arm_prior_results':previous},c.obj(text=c.TEXT))
                    previous[stage['stage']]=value['text']
                    (run/(name+'.md')).write_text(value['text'],encoding='utf-8')
                state['method_results'][arm]='generated_pending_primary_review'
            except Exception as exc:
                freeze(run/(arm+'_ERROR.json'),{'type':type(exc).__name__,'message':str(exc)[:2000]})
                state['method_results'][arm]='failed'
                if state['pending'] is not None:
                    state['status']='outcome_unknown';ledger.save();return
            ledger.save()
        state['status']='methods_complete_awaiting_primary_review';ledger.save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    (prepare if a.command=='prepare' else execute)(a.run)
