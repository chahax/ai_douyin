"""Revise an actual cohort-authored script using the project model; no media."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_narrative_workflow import new_output,now,save
from src.trend_intelligence.narrative_workflow import identity,read,verify_file,digest

def verify_candidate(folder,depth=0):
    if depth>8:raise ValueError('Review chain too deep')
    folder=Path(folder).resolve();run=read(folder/'run.json')
    if run['status']!='candidate_pending_review' or run['media_calls']!=0:raise ValueError('Completed text candidate required')
    for binding in run['artifacts'].values():verify_file(binding)
    if verify_file(run['artifacts']['result.md'])!=folder/'result.md':raise ValueError('Wrong candidate path')
    if run['schema'] in ('cohort_screenplay_revision/v1','cohort_compiled_screenplay/v1'):
        parent_path=verify_file(run['parent']);prior,_=verify_candidate(parent_path.parent,depth+1)
        if run['stage']!=prior['stage'] or run['summary']!=prior['summary']:raise ValueError('Revision ancestry changed')
        verify_file(run['feedback'])
        if run['schema']=='cohort_compiled_screenplay/v1':
            from scripts.compile_cohort_screenplay import compile_body
            compiled,_=compile_body(read(verify_file(run['artifacts']['candidate.json'])),run['stage'])
            if compiled!=(folder/'result.md').read_text(encoding='utf-8'):raise ValueError('Compiled script differs from model events')
    elif run['schema']!='cohort_expression_author/v1' or run['stage'] not in ('short','long'):
        raise ValueError('Actual cohort screenplay required')
    return run,(folder/'result.md').read_text(encoding='utf-8')

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser()
    for key in ('parent-run','feedback-file','output-dir'):p.add_argument('--'+key,required=True)
    a=p.parse_args();parent,body=verify_candidate(a.parent_run);out=new_output(a.output_dir)
    review=read(verify_file(parent['summary']['review']))
    prompt='''你是本项目编剧编辑。输入是经过批量来源分析后由项目模型写的真实原稿，现在按实际审核修订。保留选题核心，只修反馈涉及的矛盾及受影响段落；必须同步更新人物/道具表、每镜状态、结局说明和参考表，不留旧版冲突。不要以法律讲解代替人物争执。输出修复后的完整中文Markdown剧本，不输出建议或自评。45秒短版或180秒长版由kind决定；逐镜起止与每句实际说话起止都要具体数字，连续覆盖总时长。每句含标点最多6字每秒，通常4.5—5.5，压短句子为动作留时间，不把20字塞两秒。严格保持付款人/收款人、道具实际持有、手机屏幕用途和真实动作结果。来源研究不重写，引用仅保留原稿且实际审核允许的表达借鉴，去掉虚构的动作借鉴。台词/动作/分镜均由你写，不能声称通过。'''
    payload={'kind':parent['stage'],'screenplay':body,'actual_review_feedback':Path(a.feedback_file).read_text(encoding='utf-8-sig'),
        'approved_direction':review['accepted_model_excerpts'],'prior_author_constraints':review['author_constraints']}
    prompt+='\n所有实际对白必须各占一行，严格格式：- 租客【0.0-3.0秒】：实际台词。角色名可换，时间均全片累计，语气和动作另行写在该镜说明，不混入台词行。不重复抄对白到别的表格。短版实际对白总计约170—200字，长版约650—800字；所有金额用汉字口语。至少8字的一句通常4.5—5.5字每秒，不能低于3.5或高于6。单句说话区间不得与下一句重叠，真正无对白的瞬间用于有意义的动作，不加沉默凑时。长版要有足够事件承载三分钟，不能四个40秒镜头每镜仅几十字。'
    messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    save(out/'request.json',messages);(out/'prompt.md').write_text(prompt,encoding='utf-8')
    run={'schema':'cohort_screenplay_revision/v1','status':'running','stage':parent['stage'],
        'parent':identity(Path(a.parent_run)/'run.json'),'summary':parent['summary'],'feedback':identity(a.feedback_file),
        'started_at_bjt':now(),'model_calls':1,'media_calls':0,'model':'MiniMax-M3','thinking':'disabled','artifacts':{}}
    save(out/'run.json',run)
    reservation=Path(parent['summary']['run']['path']).parent.parent/'author_reservations'/(digest(out/'request.json')+'.json')
    with reservation.open('x',encoding='utf-8') as stream:json.dump({'output':str(out),'reserved_at_bjt':now()},stream)
    from src.shared.llm_client import LLMClient
    client=LLMClient(model='MiniMax-M3',extra_body={'thinking':{'type':'disabled'},'reasoning_split':True},max_tokens=12000,max_retries=0,timeout_seconds=600)
    try:
        if client.provider_name=='mock':raise ValueError('Real project model required')
        try:body=client.chat_completion_tracked(messages,caller='cohort_screenplay_revision',temperature=.2,json_mode=False,use_cache=False)
        finally:save(out/'response.json',getattr(client.provider,'last_response_metadata',{}))
        (out/'result.md').write_text(body or '',encoding='utf-8')
        if not body or read(out/'response.json').get('finish_reason')=='length':raise ValueError('Missing/truncated revision')
        from scripts.audit_cohort_pacing import audit
        save(out/'pacing.json',audit(body,parent['stage']))
        for name in ('request.json','prompt.md','response.json','result.md','pacing.json'):run['artifacts'][name]=identity(out/name)
        run['status']='candidate_pending_review'
    except Exception as exc:run.update(status='failed',error=str(exc));raise
    finally:run['finished_at_bjt']=now();save(out/'run.json',run)
    print(out)

if __name__=='__main__':main()
