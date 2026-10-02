"""Controlled, bounded text-review evaluation; truth never sent to the model."""
from __future__ import annotations
import argparse, hashlib, json, random, sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.evaluate_minimax_script_events import REVIEW_PROMPT,evidence_errors
from scripts.evaluate_minimax_scripts import request_once
from scripts.reviewer_evaluation_contract import inspect_review
from src.content_factory.creative_workflow_contract import parse_json_object
from src.content_factory.reusable_production import read,write
RUN=ROOT/'data/model_evaluations/deepseek_reviewer_20260927'

def beat(before,during,after,dialogue=None,event='人物完成本拍行动。'):
    return dict(id='',duration_seconds=10,event=event,trigger='承接前一时刻的可见状态。',before=before,during=during,after=after,dialogue=dialogue or [])
def script(title,beats):
    for i,b in enumerate(beats): b['id']=f'B{i+1:02}'
    return dict(title=title,premise=title+'：人物作出一个可见的小改变。',selected_candidate_id='C01',duration_seconds=sum(b['duration_seconds'] for b in beats),beats=beats)
def fixtures():
    cases=[]
    def add(key,brief,base,mutant,expected,paths):
        cases.append(dict(key=key,brief=brief,clean=base,mutant=mutant,expected=expected,paths=paths))
    s=script('收好',[beat('林乔站在桌旁，打开的唯一纸箱里已经放好围巾，胶带在桌上。','她把围巾边角掖进箱内。','她合上箱盖。'),beat('林乔拿起桌上的胶带。','林乔正在封箱，将胶带沿箱盖接缝贴牢。','她把胶带放回桌面。'),beat('林乔双手托住已经封好的纸箱。','她把纸箱抱到门旁地面放稳。','她松手直起身，回看空出的桌面。')])
    m=deepcopy(s);m['beats'][1]['after']='她把胶带放回桌面，又拿起桌上的账本翻开看了一眼，再合上放回桌面。'
    add('forbidden_prop',dict(theme='独自收好旧围巾',duration_seconds=[30,30],constraints=['画面只能有林乔一人、一张桌、一只纸箱、一条围巾和一卷胶带；禁止引入任何其他道具。','无对白；结尾不超过10秒。']),s,m,'新增明确禁止的账本道具',['beats.1.after'])
    s=script('报平安',[beat('成年值班员安宁独自在值班室，右手拿着对讲机，尚未按住通话键。','她望向已关好的窗户。','她垂眼看向对讲机。'),beat('安宁按住通话键，保持按住。','她说完后才松开通话键。','她将对讲机放到桌面。',[dict(speaker='安宁',text='窗户关好了。')]),beat('安宁坐回椅子。','她看着安静的窗户，肩膀放松下来。','她静静坐着。')])
    m=deepcopy(s);m['beats'][1]['before']='安宁把对讲机举到嘴边，手指离通话键还有一厘米。';m['beats'][1]['during']='安宁说完后才按下通话键，随后松开。'
    add('push_to_talk',dict(theme='值班员用对讲机汇报',duration_seconds=[30,30],constraints=['普通按住才能发送语音的对讲机，无语音缓存或自动声控。','唯一一句汇报必须通过对讲机完整发送；无需对方回话。']),s,m,'汇报发生在按键之前，不能实际发送',['beats.1.before','beats.1.during','beats.1.dialogue.0.text'])
    s=script('一次撤回',[beat('陆明和朋友周禾面对面，陆明右腕戴着一个撤回按钮。','周禾听完，眼神暗下来。','陆明看着周禾，意识到自己的话伤人。',[dict(speaker='陆明',text='我从来没把你当朋友。')]),beat('陆明闭着嘴，拇指移到腕上按钮旁。','陆明始终没有发声，按下按钮一次。','短促白光过后，周禾的记忆回到那句伤人的话之前，两人仍面对面。'),beat('陆明抬眼看着周禾。','周禾听完轻轻点头。','陆明放下手，周禾和他并肩坐下。',[dict(speaker='陆明',text='我怕你离开，刚才差点说反话。')])])
    m=deepcopy(s);m['beats'][1]['dialogue']=[dict(speaker='陆明',text='撤回。')];m['beats'][1]['during']='陆明说完这句，按下按钮一次。'
    add('last_sentence',dict(theme='一次撤回后诚实表达',duration_seconds=[30,30],constraints=['按钮一生只能按一次，只能撤回按下之前本人最后说出的一句话及对方对那句话的记忆；不能撤回更早的话。','本片应成功撤回第一拍伤人的一句话。','不出现其他超能力。']),s,m,'撤回前新增发言，最后一句变成“撤回”而非伤人话',['beats.1.dialogue.0.text','beats.1.during','beats.1.after'])
    s=read(ROOT/'data/model_evaluations/minimax_module_release_20260927/accepted_scripts/C04/script.json');m=deepcopy(s);m['beats'][2]['dialogue']=[dict(speaker='江遥',text='你先走。')]
    add('silent',dict(theme='办公室门口相互礼让',duration_seconds=[24,32],constraints=['完全无对白、旁白、字幕和可读文字。','允许两个人、一扇门和一个纸袋；无碰撞。']),s,m,'静默要求下新增一句对白',['beats.2.dialogue.0.text'])
    s=script('留下的位置',[beat('被关心的客人程雨坐在长椅左端，主动关心他的朋友许川站在长椅右侧。','程雨听见后抬头看许川。','许川停在原地等待，没有靠近。',[dict(speaker='许川',text='我可以陪你待一会儿吗？')]),beat('程雨看着长椅右端的空位。','他垂眼停顿片刻，慢慢松开攥着的手。','他转头再次看向许川。'),beat('程雨向左侧挪出更多空位。','程雨拍了拍身旁的空位，主动邀请许川坐下。','许川坐到程雨身旁，两人安静看向前方。')])
    m=deepcopy(s);m['beats'][2]['before']='许川走到长椅右端自行坐下。';m['beats'][2]['during']='许川拍拍自己身旁，邀请程雨靠近些。';m['beats'][2]['after']='程雨被动挪过去，两人安静看向前方。'
    add('ending_actor',dict(theme='被关心的人开始接受陪伴',duration_seconds=[30,30],constraints=['程雨是被关心者，许川是主动关心他的朋友。','结尾必须由程雨主动留出座位并邀请许川坐下，不可由许川代为完成邀请。']),s,m,'结尾邀请主体反转，程雨未主动留座',['beats.2.before','beats.2.during','beats.2.after'])
    s=script('未锁的柜门',[beat('沈宁走进空房间。镜头清楚拍到柜门门闩没有插入锁孔，随后回到沈宁脸上。','沈宁走到桌前。','她低头检查桌面。'),beat('沈宁拿起桌上一只空杯，查看后放回。','她听见身后柜门轻响。','她转身望向柜门。'),beat('沈宁向柜门走近。','她停在柜门前，伸手到门闩旁。','她的手悬停一刻，脸上从紧张转为疑惑。'),beat('沈宁轻推未插入锁孔的门闩，柜门便打开。','柜内空无一物，她看着门闩松一口气。','她把柜门重新合上，这次把门闩插入锁孔。')])
    s['beats'][0]['event']='观众先获得门闩没有插入锁孔的线索，沈宁进入房间。'
    m=deepcopy(s);m['beats'][0]['before']='沈宁走进空房间。镜头只拍她的脸，柜门与门闩均不入画。';m['beats'][2]['after']='她的手悬停一刻。此刻镜头第一次清楚拍到门闩没有插入锁孔，再回到她疑惑的脸。'
    add('clue_time',dict(theme='轻悬念：柜门声来自未插好的门闩',duration_seconds=[40,40],constraints=['总时长40秒，关键线索“门闩未插入锁孔”须在前20秒的实际画面中清楚呈现给观众。','第四拍沈宁亲手验证线索，不能只有摘要交代。']),s,m,'实际线索延迟至第三拍20秒之后，第一拍event摘要不算实际画面',['beats.0.before','beats.2.after'])
    return cases

def prepare():
    cases=fixtures();rng=random.Random(9272026);ids=rng.sample(range(101,999),12);groups=[[],[],[],[]];truth={}
    # A pair never appears in the same request; batches contain both labels.
    for i,c in enumerate(cases):
        for j,variant in enumerate(('clean','mutant')):
            sid=f'S{ids[2*i+j]}';group=(i//3)*2+((i+j)%2)
            groups[group].append(dict(sample_id=sid,brief=c['brief'],script=c[variant]))
            truth[sid]=dict(case=c['key'],variant=variant,expected_issue=c['expected'] if j else None,evidence_paths=c['paths'] if j else [])
    for group in groups:rng.shuffle(group)
    plan=dict(scope='此前实际使用的独立剧本文本审核提示词；不是整个生产writer_check/图像/音视频审核',reviewer_prompt=REVIEW_PROMPT,prompt_sha256=hashlib.sha256(REVIEW_PROMPT.encode()).hexdigest(),maximum_remote_calls=5,unique_samples=12,clean_controls=6,seeded_defects=6,repeat='batch_01 repeated once, identical payload, new call receipt',writer_calls=0,media_calls=0,automatic_approval=False,scoring='助手逐项判读：已知错误召回、正常稿误报、引用原文有效性；小型定向测试，不代表总体质量率。')
    RUN.mkdir(parents=True,exist_ok=True)
    for name,obj in [('PLAN.json',plan),('TRUTH.json',truth),('BATCHES.json',groups)]:
        p=RUN/name
        if p.exists() and read(p)!=obj:raise RuntimeError('Frozen fixture changed: '+name)
        write(p,obj)
    print('Prepared 12 blinded samples / 6 single-concept defects / cap 5 calls',flush=True)

def run():
    plan=read(RUN/'PLAN.json');groups=read(RUN/'BATCHES.json')
    for i,group in enumerate(groups+[groups[0]]):
        dest=RUN/f'batch_{i+1:02}';dest.mkdir(exist_ok=True)
        print('REVIEW '+str(i+1),flush=True)
        result=request_once(dest/'call.json','director',[dict(role='system',content=plan['reviewer_prompt']),dict(role='user',content=json.dumps(dict(samples=group),ensure_ascii=False))],None,plan['maximum_remote_calls'],RUN)
        if result['response_metadata'].get('finish_reason')=='length':raise RuntimeError('Truncated reviewer output')
        review=parse_json_object(result['response_text']);write(dest/'review.json',review)
        write(dest/'legacy_evidence_check.json',dict(errors=evidence_errors(review,group),automatic_approval=False))
        write(dest/'contract_check.json',inspect_review(review,group))
        print(json.dumps(dict(batch=i+1,review=review),ensure_ascii=False),flush=True)
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser();a.add_argument('phase',choices=['prepare','run']);args=a.parse_args();prepare() if args.phase=='prepare' else run()
