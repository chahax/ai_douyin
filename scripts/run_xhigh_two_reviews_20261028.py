"""Two new source-grounded revisions of a frozen reading; never resume old runs."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jsonschema import validate
from src.content_factory.corpus_screenplay_v1 import read, freeze, digest
from src.content_factory.serial_story_transport_v6 import Ledger, NativeClient

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT/'data/corpus_production_trials/20261028_v6_five_efforts/xhigh'
RUN = ROOT/'data/corpus_production_trials/20261028_xhigh_two_reviews'
SCHEMA = {'type':'object','additionalProperties':False,'required':['analysis','open_questions','corrections'],
 'properties':{'analysis':{'type':'string','minLength':1},
 'open_questions':{'type':'array','items':{'type':'string'}},
 'corrections':{'type':'array','items':{'type':'object','additionalProperties':False,
 'required':['old_statement','revised_statement','chapter','evidence'],
 'properties':{'old_statement':{'type':'string'},'revised_statement':{'type':'string'},
 'chapter':{'type':'integer','enum':[1,2,3]},'evidence':{'type':'string','minLength':1}}}}}}

def payload(source, candidate):
    return {'complete_chapters':source['chapters'], 'current_analysis':candidate['analysis'],
            'current_open_questions':candidate['open_questions'], 'candidate_sha256':digest(candidate)}

PROMPT = '''你负责小说改编之前的阅读理解复核。先完整阅读提供的三章原文，再独立核对当前分析。
逐项核对人物身份、说话人、动作主体与对象、物品来源/去向、否定与条件、先后顺序、地点及居住关系、人物知情。
区分原书未来、当前事件、过去、计划、猜测和美术补足。不要将当前同场推成同住、推测推成事实。
有错误就据原文修订，原稿正确的内容保留；不要为了表现复核而强行找错或加入原文没有的解释。
输出完整修订后的自然语言analysis、仍未确定的open_questions，以及本轮实际corrections。
corrections的chapter为证据所在章，evidence逐字摘取该章原文；不确定的判断不能当成确定事实。
不写剧本，不给无根据的自评通过分数。没有发现需要修订时corrections为空数组。
'''

def execute():
    RUN.mkdir(exist_ok=False)
    source=read(PARENT/'SOURCE.json')
    native=read(PARENT/'RESPONSE_001.json')['native']
    candidate=json.loads(native['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    plan=read(PARENT/'PLAN.json')
    plan.update(max_calls=2, user_statement='用xhigh可以多思考两轮试试', experiment='two_source_grounded_revisions')
    freeze(RUN/'PLAN.json',plan);freeze(RUN/'SOURCE.json',source);freeze(RUN/'INITIAL.json',candidate)
    freeze(RUN/'AUTHORIZATION.json',{'user_statement':plan['user_statement'],'model':'MiniMax-M3.1-Flash',
      'effort':'xhigh','new_calls':2,'source_sha256':digest(source),'parent_reading_sha256':digest(candidate),
      'reuse':'已知终态阅读输出，仅作为两轮新测试输入；不重跑旧失败任务','media':False})
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0}
    ledger=Ledger(RUN,plan,state,NativeClient(RUN,plan));ledger.save()
    try:
        for n in (1,2):
            # Second round receives current text, not previous diagnoses/corrections.
            result=ledger.call(f'REVIEW_{n}','writer',PROMPT,payload(source,candidate),SCHEMA)
            validate(result,SCHEMA)
            by_ch={c['index']:c['text'] for c in source['chapters']}
            bad=[i for i,c in enumerate(result['corrections']) if c['evidence'] not in by_ch[c['chapter']]]
            freeze(RUN/f'QUOTE_CHECK_{n}.json',{'bad_correction_indices':bad,'semantic_acceptance':False})
            # Preserve bad quotes for independent review; they never mean semantic pass.
            (RUN/f'ROUND_{n}_OUTPUT.md').write_text(result['analysis']+'\n\n待确认：\n'+'\n'.join(result['open_questions']),encoding='utf-8')
            candidate={'analysis':result['analysis'],'open_questions':result['open_questions']}
            print(f'round {n} completed; corrections={len(result["corrections"])}; bad_quotes={len(bad)}',flush=True)
        state['status']='completed_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(RUN/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:1500]})
    finally: ledger.save()

if __name__=='__main__':execute()
