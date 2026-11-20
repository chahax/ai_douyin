"""Continue known failed probe with precise world/shot diagnostics, no blind replay."""
from novel_production_probe_20261027 import *
class WorldEdit(Strict):
    index:int
    fact:Fact
class WorldEdits(Strict):edits:list[WorldEdit]
def diagnostics(episode,foundation):
    errors=[];people={p['id'] for p in foundation['people']};places={p['id'] for p in foundation['places']}
    for s in episode['shots']:
        if s['location_id'] not in places:errors.append({'shot_id':s['id'],'error':'unknown_location'})
        if not set(s['cast'])<=people:errors.append({'shot_id':s['id'],'error':'cast must be visible registered people; NARRATOR is audio only','actual':s['cast']})
        for a in s['actions']:
            if a['actor_id'] not in people:errors.append({'shot_id':s['id'],'error':'action actor must be registered physical character'})
        chars=sum(len(x['text']) for x in s['speech'])
        if chars>4*s['duration_seconds']:errors.append({'shot_id':s['id'],'error':'speech_char_budget','actual':chars,'maximum':4*s['duration_seconds']})
    return errors
def main():
    parent=PROD.with_name(PROD.name+'_continued');run=PROD.with_name(PROD.name+'_repair')
    if run.exists():raise ValueError('no_replay')
    states=[read(p/'RESULT.json') for p in [PROD,parent]];used=sum(x['calls'] for x in states)
    if used!=3 or any(x['pending'] is not None for x in states):raise ValueError('budget_or_unknown')
    source=read(PROD/'SOURCE.json');foundation=read(parent/'FOUNDATION.json');raw_episode=read(parent/'E1_RAW.json')
    run.mkdir();dump(run/'PLAN.json',{'prior_calls':used,'remaining_calls':8,'total_limit_unchanged':11,'foundation_sha256':sha(foundation),'episode1_sha256':sha(raw_episode),'source_sha256':sha(source),'policy':'已知程序失败后精确诊断；重用原生剧本，世界事实限定索引、镜头限定ID修复，非手改稿','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();error=None;status='needs_attention';episodes=[]
    def call(*args):
        if session.calls>=8:raise ValueError('cumulative_limit')
        return session.call(*args)
    try:
        issues=[{'index':4,'problem':'同条混合原主教唆偷窃的现实过往与原书未来伤眼；不能把未来伤眼标成已经发生。'}, {'index':6,'problem':'原文米不到月底吃空会被打，不证明米袋常空；去掉未支持的频率。'}, {'index':7,'problem':'带着孩子出国与留下六个孩子矛盾；按原文明确老婆独自去向和孩子留下，别新增信息。'}, {'index':14,'problem':'曾联系黑煤窑卖孩子未成、形成现在心理阴影，是先前已发生而非原书未来；核对标签。'}]
        edits=WorldEdits.model_validate(call('WORLD_REPAIR','只修列出的world_facts索引，每个输出完整Fact。依据完整原文，分清原书未来/当前与过往，不扩人物和结局。其他基础条目程序保持。',{'complete_source':source,'foundation':foundation,'issues':issues},WorldEdits)).model_dump()
        if len(edits['edits'])!=4 or {e['index'] for e in edits['edits']}!={4,6,7,14}:raise ValueError('world_edit_scope')
        verify_refs(edits,source);updated=json.loads(json.dumps(foundation))
        for e in edits['edits']:updated['world_facts'][e['index']]=e['fact']
        foundation=updated;dump(run/'WORLD_EDITS.json',edits);dump(run/'FOUNDATION.json',foundation)
        for n in (1,2):
            payload={'complete_source':source,'foundation':foundation,'episode':n,'previous_episode':episodes[-1] if episodes else {},'target_seconds':90}
            raw=raw_episode if n==1 else call('E2_WRITE',WRITE_PROMPT,payload,Episode)
            dump(run/f'E{n}_RAW.json',raw)
            # Review all content even when program diagnostics block admission.
            program=diagnostics(raw,foundation);dump(run/f'E{n}_PROGRAM_DIAGNOSTICS.json',program)
            review=check_review(call(f'E{n}_REVIEW',REVIEW_PROMPT,{**payload,'candidate':raw,'candidate_sha256':sha(raw)},EpisodeReview),raw,source);dump(run/f'E{n}_REVIEW_0.json',review)
            primary=[]
            if n==1:primary=[{'shot_id':'E1S04','reason':'结尾已接面包，但下一镜还在老六手里并再次被拿走。交接只能发生一次，原文先观察再恐惧再拿走。'},{'shot_id':'E1S05','reason':'开头苏墨持面包与老六仍捧面包、再次拿走矛盾；内心音轨“他闭紧眼睛”不是本人第一人称思维。'},{'shot_id':'E1S06','reason':'开头已经跪坐又立刻跪倒；ending_state把误解者写成苏墨，实际小六误解苏墨不要再偷东西。'},{'shot_id':'E1S03','reason':'原书未来地下室画面不能用当前卧室location；旁白不是在场人物。可用当前苏墨画面配明确原书结局内心音轨，不必新增资产。'}]
            hard=[x for x in review['issues'] if x['severity']=='must_fix'];wanted={x['shot_id'] for x in hard+program+primary}
            if wanted:
                repairs=call(f'E{n}_REPAIR','只修allowed_shot_ids内镜头，输出完整镜头；其他程序原样保留。每镜头时长维持。动作主体必须是物理人物，旁白只在speech中；所有事实核对原文。'+WRITE_PROMPT,{**payload,'candidate':raw,'review_issues':hard,'program_issues':program,'primary_issues':primary,'allowed_shot_ids':sorted(wanted)},ShotRepairs)
                episode=replace_shots(raw,repairs,wanted,foundation,source);dump(run/f'E{n}_CANDIDATE_1.json',episode)
                review=check_review(call(f'E{n}_REVIEW_FINAL',REVIEW_PROMPT,{**payload,'candidate':episode,'candidate_sha256':sha(episode)},EpisodeReview),episode,source);dump(run/f'E{n}_REVIEW_1.json',review)
            else:episode=validate_episode(raw,foundation,source,n)
            episodes.append(episode);dump(run/f'E{n}_FINAL.json',episode)
            if any(x['severity']=='must_fix' for x in review['issues']):status='needs_revision';break
        else:status='machine_pass_pending_primary'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':used,'pending':session.pending,'error':error,'episodes_completed':len(episodes),'primary_acceptance':'pending'});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
