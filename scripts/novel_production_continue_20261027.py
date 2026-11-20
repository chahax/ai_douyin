"""Known foundation format failure, one model protocol repair then production."""
from novel_production_probe_20261027 import *
def main():
    run=PROD.with_name(PROD.name+'_continued')
    if run.exists():raise ValueError('no_replay')
    parent=read(PROD/'RESULT.json')
    if parent['pending'] is not None or parent['calls']!=1:raise ValueError('unexpected_parent')
    native=read(PROD/'FOUNDATION/RESPONSE_1.json');source=read(PROD/'SOURCE.json');prior=json.loads(native['native']['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    run.mkdir();dump(run/'PLAN.json',{'prior_calls':1,'remaining_calls':10,'total_limit_unchanged':11,'source_sha256':sha(source),'failed_native_sha256':sha(native),'policy':'原生已知结构失败，模型修结构，不人工重排为成功；旧失败不改','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();status='needs_attention';error=None;episodes=[]
    def call(*args):
        if session.calls>=10:raise ValueError('cumulative_limit')
        return session.call(*args)
    try:
        prompt=FOUNDATION_PROMPT+' 本次修复前一版结构错误：顶层必须同时有world_facts、people、places、visual_style、episodes五个字段，数组直接用JSON数组，不能item包装，episode和source_chapters用整数。每集90秒只选3—5个可连续演出的事件，不必覆盖三章，后续留给后续集；不要将整章所有段编号当作每件事实的证据。不要新增开头清晨等原文未写的具体时间。'
        foundation=Foundation.model_validate(call('FOUNDATION_PROTOCOL',prompt,{'complete_source':source,'previous_native_arguments':prior,'errors':parent['error']},Foundation)).model_dump();verify_refs(foundation,source)
        if [e['episode'] for e in foundation['episodes']]!=[1,2]:raise ValueError('episode_plan')
        if len({p['id'] for p in foundation['people']})!=len(foundation['people']) or len({p['id'] for p in foundation['places']})!=len(foundation['places']):raise ValueError('duplicate_registry')
        dump(run/'FOUNDATION.json',foundation)
        for n in (1,2):
            payload={'complete_source':source,'foundation':foundation,'episode':n,'previous_episode':episodes[-1] if episodes else {},'target_seconds':90}
            raw=call(f'E{n}_WRITE',WRITE_PROMPT,payload,Episode);dump(run/f'E{n}_RAW.json',raw);episode=validate_episode(raw,foundation,source,n);dump(run/f'E{n}_CANDIDATE_0.json',episode)
            review=check_review(call(f'E{n}_REVIEW',REVIEW_PROMPT,{**payload,'candidate':episode,'candidate_sha256':sha(episode)},EpisodeReview),episode,source);dump(run/f'E{n}_REVIEW_0.json',review)
            hard=[x for x in review['issues'] if x['severity']=='must_fix']
            if hard:
                wanted={x['shot_id'] for x in hard};raw=call(f'E{n}_REPAIR','只修指定镜头，输出完整镜头；其他镜头程序原样保留。保持该镜头时长不变。意见须以原文核实，不能新增无据剧情。'+WRITE_PROMPT,{**payload,'candidate':episode,'issues':hard,'allowed_shot_ids':sorted(wanted)},ShotRepairs)
                episode=replace_shots(episode,raw,wanted,foundation,source);dump(run/f'E{n}_CANDIDATE_1.json',episode)
                review=check_review(call(f'E{n}_REVIEW_FINAL',REVIEW_PROMPT,{**payload,'candidate':episode,'candidate_sha256':sha(episode)},EpisodeReview),episode,source);dump(run/f'E{n}_REVIEW_1.json',review)
            episodes.append(episode);dump(run/f'E{n}_FINAL.json',episode)
            if any(x['severity']=='must_fix' for x in review['issues']):status='needs_revision';break
        else:status='machine_pass_pending_primary'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':1,'pending':session.pending,'error':error,'episodes_completed':len(episodes),'primary_acceptance':'pending'});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
