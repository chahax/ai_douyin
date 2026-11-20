"""Accept echoed untouched shots only when they are byte-equivalent data."""
from novel_production_repair_20261027 import *
REPAIR_PROMPT='''只输出allowed_shot_ids中的镜头，每个一次。完整原稿供上下文参考，未选镜头不要输出或修改。每个选中镜头保持原duration_seconds不变；无需让本次修订列表合计90秒，完整剧本合计由程序保留原镜头后校验。核对原文和问题，观点不等于事实，拒绝错误意见。保留正确主体、动作、道具与时间，不新增无据事件或角色。动作演员必须在cast，NARRATOR仅用于音轨。对白字符数不超过本镜duration_seconds*4。'''
def extract_changed_only(original,raw,wanted):
    shots=ShotRepairs.model_validate(raw).model_dump()['shots'];old={s['id']:s for s in original['shots']}
    ids=[s['id'] for s in shots]
    if len(ids)!=len(set(ids)) or not wanted<=set(ids) or not set(ids)<=set(old):raise ValueError('invalid_patch_ids')
    for s in shots:
        if s['id'] not in wanted and s!=old[s['id']]:raise ValueError('unrequested_shot_changed')
    return {'shots':[s for s in shots if s['id'] in wanted]}
def main():
    parent=PROD.with_name(PROD.name+'_repair');run=PROD.with_name(PROD.name+'_echo_continued')
    if run.exists():raise ValueError('no_replay')
    prev=[read(p/'RESULT.json') for p in [PROD,PROD.with_name(PROD.name+'_continued'),parent]];used=sum(x['calls'] for x in prev)
    if used!=6 or any(x['pending'] is not None for x in prev):raise ValueError('budget_or_unknown')
    source=read(PROD/'SOURCE.json');foundation=read(parent/'FOUNDATION.json');old=read(parent/'E1_RAW.json');native=read(parent/'E1_REPAIR/RESPONSE_1.json')
    req=read(parent/'E1_REPAIR/REQUEST_1.json');payload=json.loads(req['messages'][2]['content']);wanted=set(payload['allowed_shot_ids'])
    choice=native['native']['choices'][0];tc=choice['message']['tool_calls']
    if choice['finish_reason']!='tool_calls' or len(tc)!=1 or tc[0]['function']['name']!='submit_result':raise ValueError('native_protocol')
    patch=extract_changed_only(old,json.loads(tc[0]['function']['arguments']),wanted);first=replace_shots(old,patch,wanted,foundation,source)
    run.mkdir();dump(run/'ADOPTION.json',{'prior_calls':used,'remaining_calls':5,'total_limit_unchanged':11,'native_sha256':sha(native),'old_candidate_sha256':sha(old),'canonical_candidate_sha256':sha(first),'policy':'模型返回整集但未选镜头逐字段完全相同，显式协议接收只抽取选中原生镜头；不修改原生内容、旧错误仍保留','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()});dump(run/'E1_ADOPTED.json',first)
    session=Session(run);session.save();status='needs_attention';error=None;episodes=[]
    def call(*args):
        if session.calls>=5:raise ValueError('cumulative_limit')
        return session.call(*args)
    try:
        review=check_review(call('E1_REVIEW_FINAL',REVIEW_PROMPT,{'complete_source':source,'foundation':foundation,'candidate':first,'candidate_sha256':sha(first),'previous_episode':{}},EpisodeReview),first,source);dump(run/'E1_REVIEW.json',review);dump(run/'E1_FINAL.json',first);episodes.append(first)
        if any(x['severity']=='must_fix' for x in review['issues']):status='needs_revision'
        else:
            payload={'complete_source':source,'foundation':foundation,'episode':2,'previous_episode':first,'target_seconds':90}
            raw=call('E2_WRITE',WRITE_PROMPT,payload,Episode);dump(run/'E2_RAW.json',raw)
            program=diagnostics(raw,foundation);dump(run/'E2_PROGRAM.json',program)
            review=check_review(call('E2_REVIEW',REVIEW_PROMPT,{**payload,'candidate':raw,'candidate_sha256':sha(raw)},EpisodeReview),raw,source);dump(run/'E2_REVIEW_0.json',review)
            hard=[x for x in review['issues'] if x['severity']=='must_fix'];wanted={x['shot_id'] for x in hard+program}
            if wanted:
                patch=call('E2_REPAIR',REPAIR_PROMPT,{**payload,'candidate':raw,'issues':hard,'program_issues':program,'allowed_shot_ids':sorted(wanted)},ShotRepairs);patch=extract_changed_only(raw,patch,wanted);episode=replace_shots(raw,patch,wanted,foundation,source);dump(run/'E2_CANDIDATE_1.json',episode)
                review=check_review(call('E2_REVIEW_FINAL',REVIEW_PROMPT,{**payload,'candidate':episode,'candidate_sha256':sha(episode)},EpisodeReview),episode,source);dump(run/'E2_REVIEW_1.json',review)
            else:episode=validate_episode(raw,foundation,source,2)
            dump(run/'E2_FINAL.json',episode);episodes.append(episode);status='needs_revision' if any(x['severity']=='must_fix' for x in review['issues']) else 'machine_pass_pending_primary'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':used,'pending':session.pending,'error':error,'episodes_completed':len(episodes),'primary_acceptance':'pending'});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
