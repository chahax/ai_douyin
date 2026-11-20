"""Model authors events; deterministic timing refuses stretched or rushed text."""
import argparse,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.revise_cohort_screenplay import verify_candidate
from scripts.run_narrative_workflow import new_output,now,save
from src.trend_intelligence.narrative_workflow import read,identity,verify_file,digest

PROMPT='''你是项目编剧，按已审选题和实际反馈编写可演出的情节。只返回严格JSON，不写Markdown或自评。台词和实际动作由你写，程序负责排秒数。不要给起止秒数，不复用旧稿的缓慢排时。
结构：{"title":"标题","characters":[{"id":"T","name":"租客","goal":"目标"},{"id":"L","name":"房东","goal":"目标"}],"space":"固定站位/窗光/视线轴","props":{"P1":"初始所有人、位置和用途"},"payment":{"payer":"L","payee":"T","amount":"两千","method":"转账或现金"},"scenes":[{"id":"S01","framing":"景别/画面结构及光线","action":"此镜完整实际动作，包括拿放/转手/屏幕朝向/观众看到什么；对白期间并行做哪些动作","dialogue":[{"speaker":"L","text":"完整口语台词","delivery":"触发原因、语气、重音、急缓"}],"after_action":"对白结束后的有意义短动作，没有则写无","after_action_seconds":0.3,"end_state":{"P1":"此镜末实际位置/持有人/用途"},"result":"这一镜新增的事实或行动后果"}],"ending":"现场目标在实际动作中怎样兑现；资金/钥匙/手机终态","reference_usage":[{"source_id":"douyin:数字","use":"只写已审核允许的表达借鉴，不编原片实际结局"}]}
kind=short时8至10个有意义场景、总对白汉字含标点180—200，纯动作留白总计4—8秒；kind=long时14至18场景、总对白680—800字，纯动作留白总计15—25秒。不要固定四镜慢动作。程序把所有对白均匀安排在剩余时间，平均含标点字数必须4.3至5.7每秒，否则整稿拦截。所有台词数字用中文口语，不用阿拉伯数字。不能在after_action写超出其秒数能做的动作，长操作与对白并行但要有真实时间。
同一核心：租房押金两千，钉眼原本就有，双方通过具体可核验原记录与现场确认，房东自愿退给租客。不能说相册日期改不了或图片自动证明必胜；要有合理记录背景和房东认出/确认的事实。别凭空加扣款、换成别的金额。至少两人真实目标对抗；禁止旁白、教学、电话外援、警方、CTA、堵门/扣物逼付。结尾实际钱到租客且交接完成，不能承诺一下就走。
动作尽量少而精准，删除无必要银行卡、收据、反复掏手机。手机等道具每次转手/放下都写清，end_state完整列所有props，不能同一只手在同时做互斥动作。人物说话时嘴部可见。短版快速进入冲突；长版要新增有效核验尝试、被阻碍后的行动和代价，不能同义反问重复三轮。收场有情绪余波但别鸡汤、别平静闲聊拖尾。拍物件是让观众看见事实前后对照，禁止用抽象“对比成立”代替实际画面。
参考原片的方法而非拍成知识问答。素材中的领取款项、日期真实性、指印效力等未经核验结论不能作为一般规则。剧情具体原创，片头小字可标演绎。'''

def compile_body(candidate,kind):
    duration=45 if kind=='short' else 180
    actors={a['id']:a['name'] for a in candidate['characters']}
    goals={a['id']:a['goal'] for a in candidate['characters']}
    if actors!={'T':'租客','L':'房东'}:raise ValueError('Actor identities changed')
    pay=candidate['payment']
    if pay['payer']!='L' or pay['payee']!='T' or pay['amount']!='两千':raise ValueError('Refund identity/amount changed')
    scenes=candidate['scenes'];ids=[s['id'] for s in scenes]
    if not scenes or len(ids)!=len(set(ids)):raise ValueError('Invalid scene identity')
    reserve=sum(float(s['after_action_seconds']) for s in scenes)
    count=sum(len(d['text']) for s in scenes for d in s['dialogue'])
    if not 0<=reserve<duration:raise ValueError('Invalid action reserve')
    rate=count/(duration-reserve)
    if not 4.3<=rate<=5.7:raise ValueError(f'Speech cannot fit active pacing: {count} chars, {reserve}s action, rate={rate:.3f}')
    lines=[f"# {candidate['title']} · {duration}秒",'', '虚构情节演绎。', '', candidate['space'], '',
        f"人物：租客（{goals['T']}）；房东（{goals['L']}）。",'',
        '## 道具初态','']+[f'- {k}：{v}' for k,v in candidate['props'].items()]
    cursor=0;timing=[]
    for s in scenes:
        start=cursor
        if set(s['end_state'])!=set(candidate['props']):raise ValueError('Missing prop end state')
        if not 0<=float(s['after_action_seconds'])<=4:raise ValueError('Excessive standalone action pause')
        if not s['dialogue']:raise ValueError('No speech scene: review separate action timing first')
        spoken=[]
        for d in s['dialogue']:
            if d['speaker'] not in actors or not d['text'].strip() or any(c.isdigit() for c in d['text']):raise ValueError('Invalid spoken line')
            end=cursor+len(d['text'])/rate
            spoken.append(f"- {actors[d['speaker']]}【{cursor:.2f}-{end:.2f}秒】：{d['text']}")
            timing.append({'scene':s['id'],'speaker':d['speaker'],'start':round(cursor,2),'end':round(end,2),'text':d['text'],'delivery':d['delivery']})
            cursor=end
        cursor+=float(s['after_action_seconds'])
        lines+=['',f"## {s['id']} · {start:.2f}—{cursor:.2f}秒",'',s['framing'],'',f"动作：{s['action']}",'']+spoken
        lines+=['','语气：'+'；'.join(f"{actors[d['speaker']]}：{d['delivery']}" for d in s['dialogue']),
            f"对白后 {s['after_action_seconds']} 秒：{s['after_action']}",f"结果：{s['result']}",
            '尾态：'+'；'.join(f'{k}={v}' for k,v in s['end_state'].items())]
    if not math.isclose(cursor,duration,abs_tol=.001):raise ValueError('Timeline does not end at target')
    lines+=['','## 结局','',candidate['ending'],'','## 来源借鉴','']+[f"- {r['source_id']}：{r['use']}" for r in candidate['reference_usage']]
    lines+=['',f'排时：对白共{count}字（含标点），声明平均{rate:.2f}字/秒；独立动作共{reserve:.2f}秒。该计算不是实际声音审核。']
    return '\n'.join(lines)+'\n',{'duration':duration,'characters':count,'rate':rate,'action_seconds':reserve,'dialogue':timing}

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser()
    for key in ('parent-run','feedback-file','output-dir'):p.add_argument('--'+key,required=True)
    a=p.parse_args();parent,body=verify_candidate(a.parent_run);out=new_output(a.output_dir)
    review=read(verify_file(parent['summary']['review']))
    payload={'kind':parent['stage'],'prior_model_script':body,'actual_feedback':Path(a.feedback_file).read_text(encoding='utf-8-sig'),
        'approved_model_direction':review['accepted_model_excerpts'],'checked_source_usage':review['checked_evidence'],
        'constraints':review['author_constraints']}
    messages=[{'role':'system','content':PROMPT},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    save(out/'request.json',messages);(out/'prompt.md').write_text(PROMPT,encoding='utf-8')
    run={'schema':'cohort_compiled_screenplay/v1','status':'running','stage':parent['stage'],'started_at_bjt':now(),
        'parent':identity(Path(a.parent_run)/'run.json'),'summary':parent['summary'],'feedback':identity(a.feedback_file),
        'model_calls':1,'media_calls':0,'model':'MiniMax-M3','thinking':'disabled','timing_rule':'proportional_chars_with_explicit_action_reserve/v1','artifacts':{}}
    save(out/'run.json',run)
    reservation=Path(parent['summary']['run']['path']).parent.parent/'author_reservations'/(digest(out/'request.json')+'.json')
    with reservation.open('x',encoding='utf-8') as f:json.dump({'output':str(out),'reserved_at_bjt':now()},f)
    from src.shared.llm_client import LLMClient
    client=LLMClient(model='MiniMax-M3',extra_body={'thinking':{'type':'disabled'},'reasoning_split':True},max_tokens=16000,max_retries=0,timeout_seconds=600,preserve_invalid_json=True)
    try:
        if client.provider_name=='mock':raise ValueError('Real model required')
        try:raw=client.chat_completion_tracked(messages,caller='cohort_structured_screenplay',temperature=.2,json_mode=True,use_cache=False)
        finally:save(out/'response.json',getattr(client.provider,'last_response_metadata',{}))
        (out/'candidate.json').write_text(raw or 'null',encoding='utf-8')
        if read(out/'response.json').get('finish_reason')=='length':raise ValueError('Truncated candidate')
        candidate=read(out/'candidate.json')
        known=set(review['selected_source_ids'])
        if any(r['source_id'] not in known for r in candidate['reference_usage']):raise ValueError('Unreviewed source')
        body,timing=compile_body(candidate,parent['stage'])
        (out/'result.md').write_text(body,encoding='utf-8');save(out/'timing.json',timing)
        from scripts.audit_cohort_pacing import audit
        pacing=audit(body,parent['stage']);save(out/'pacing.json',pacing)
        if not pacing['passed']:raise ValueError('Declared pacing audit failed')
        for name in ('request.json','prompt.md','response.json','candidate.json','result.md','timing.json','pacing.json'):run['artifacts'][name]=identity(out/name)
        run['status']='candidate_pending_review'
    except Exception as exc:run.update(status='failed',error=str(exc));raise
    finally:run['finished_at_bjt']=now();save(out/'run.json',run)
    print(out)

if __name__=='__main__':main()
