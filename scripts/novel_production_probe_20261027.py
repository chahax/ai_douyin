"""Fresh real-novel two-episode production probe, bounded scene repair."""
from novel_span_patch_20261027 import *
PROD=ROOT/'data/corpus_production_trials/20261027_production_probe'
class Person(Strict):
    id:str
    name:str
    identity:str
    source_ids:list[str]=Field(min_length=1)
    visual_design:str
class Place(Strict):
    id:str
    source_grounded_description:str
    source_ids:list[str]=Field(min_length=1)
    artistic_design:str
class Arc(Strict):
    episode:int
    source_chapters:list[int]
    opening:str
    events:list[str]
    ending:str
    source_ids:list[str]=Field(min_length=1)
class Foundation(Strict):
    world_facts:list[Fact]
    people:list[Person]
    places:list[Place]
    visual_style:str
    episodes:list[Arc]
class Action(Strict):
    actor_id:str
    action:str
class Speech(Strict):
    speaker_id:str
    kind:Literal['dialogue','inner_voice','narration']
    text:str
    source_ids:list[str]=Field(min_length=1)
class Shot(Strict):
    id:str
    duration_seconds:int=Field(ge=4,le=15)
    location_id:str
    timeline:Literal['current','original_novel_future','memory']
    cast:list[str]=Field(min_length=1)
    opening_positions:str
    actions:list[Action]=Field(min_length=1)
    speech:list[Speech]
    camera:str
    ending_state:str
    source_ids:list[str]=Field(min_length=1)
class Episode(Strict):
    episode:int
    title:str
    shots:list[Shot]=Field(min_length=1)
class Issue(Strict):
    shot_id:str
    category:Literal['factual','continuity','timing','expression']
    severity:Literal['must_fix','suggestion']
    reason:str
    source_ids:list[str]=Field(min_length=1)
class EpisodeReview(Strict):
    checked_shot_ids:list[str]
    issues:list[Issue]
class ShotRepairs(Strict):shots:list[Shot]
FOUNDATION_PROMPT='''完整阅读原小说第1—3章，为连续两集各90秒短剧设计基础。不是把全书压成两集，只适配这三章中的连续开篇情节，未覆盖的后续仍留给后续集。先世界事实、人物身份关系、地点，再分集事件与承接。所有事实绑定原段ID，人物视觉与美术补足明确放design，不假装小说明示。六个孩子称谓与哥哥自称正确，原主与穿书者心理区分，原书未来不当已发生。不推定亲人死亡或病情。source_chapters和source_ids必须支持所选事件。episodes恰好1、2。视觉风格清楚统一，家庭贫困但不能为温暖美化抹去原文处境。'''
WRITE_PROMPT='''基于完整原文和基础，写指定集90秒中文短剧文本，剧情从源材料连续推进，不编新结局。本集独立总时长恰好90秒，每镜头4—15秒，片段合计由程序计时。人物动作、神情、进出、位置、持物与对白都明确，对话尽快推进信息，避免无信息停留。原文事实可忠实转述或压缩，演出所需的小动作允许合理补足，不能改变谁做谁说或事件结果。画风地点身份沿基础，美术补足不变小说事实。原书未来若呈现必须显式独立时间线，不能作为当前伤情/死亡。每镜头cast包含实际出现全部人物，dialogue说话人需在场，内心旁白明确；旁白speaker_id可NARRATOR。每镜头对白总中文字符不超过duration*4，留动作时间；不以语速赶场。id使用E1S01或E2S01等。本集前后状态承接；不要让未知角色瞬间入场，不要给未明确的对白随意指派说话人。每镜头均绑定来源ID。'''
REVIEW_PROMPT='''独立按完整原文检查当前剧本，不给旧意见。逐镜头检查谁说谁做、身份和哥哥自称、穿书与原书未来、条件/猜测/计划、场景进出/持物/状态、前后集承接和时长。不因为句子看起来合理就认可原文没支持的剧情；合理表演小动作和明确美术设计允许。说话人的上下文连续指代要理解，不能要求每句都重写名字；人物“沉默”不代表稍后永远不说话。只报确凿或明确需消除歧义的must_fix，不把风格建议作硬错。source_ids必须是原文证据。checked_shot_ids覆盖全部，本稿不是已通过稿。'''
def verify_refs(obj,source):
    known={x['id'] for x in source}
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if k=='source_ids' and (not v or not set(v)<=known):raise ValueError('unknown_or_empty_reference')
                walk(v)
        elif isinstance(x,list):
            for y in x:walk(y)
    walk(obj)
def validate_episode(raw,foundation,source,n):
    v=Episode.model_validate(raw).model_dump();verify_refs(v,source)
    if v['episode']!=n:raise ValueError('episode_id')
    if sum(s['duration_seconds'] for s in v['shots'])!=90:raise ValueError('duration_total')
    people={p['id'] for p in foundation['people']};places={p['id'] for p in foundation['places']};seen=set()
    for s in v['shots']:
        if s['id'] in seen:raise ValueError('duplicate_shot')
        seen.add(s['id'])
        if s['location_id'] not in places or not set(s['cast'])<=people:raise ValueError('unknown_location_or_cast')
        if any(a['actor_id'] not in s['cast'] for a in s['actions']):raise ValueError('actor_not_in_cast')
        for line in s['speech']:
            if line['speaker_id'] not in people|{'NARRATOR'}:raise ValueError('unknown_speaker')
            if line['kind']=='dialogue' and line['speaker_id'] not in s['cast']:raise ValueError('speaker_not_in_cast')
        chars=sum(len(x['text']) for x in s['speech'])
        if chars>4*s['duration_seconds']:raise ValueError('speech_over_duration:'+s['id'])
    return v
def check_review(raw,episode,source):
    v=EpisodeReview.model_validate(raw).model_dump();ids={s['id'] for s in episode['shots']}
    if len(v['checked_shot_ids'])!=len(ids) or set(v['checked_shot_ids'])!=ids:raise ValueError('review_coverage')
    if any(x['shot_id'] not in ids for x in v['issues']):raise ValueError('review_unknown_shot')
    verify_refs(v,source);return v
def replace_shots(current,raw,wanted,foundation,source):
    edits=ShotRepairs.model_validate(raw).model_dump()['shots']
    if len(edits)!=len(wanted) or {s['id'] for s in edits}!=wanted:raise ValueError('repair_scope')
    by={s['id']:s for s in edits};new={**current,'shots':[by.get(s['id'],s) for s in current['shots']]}
    # Fixed durations avoid silently changing the schedule of untouched shots.
    before={s['id']:s for s in current['shots']}
    if any(s['duration_seconds']!=before[s['id']]['duration_seconds'] for s in edits):raise ValueError('repair_duration_changed')
    return validate_episode(new,foundation,source,current['episode'])
def main():
    if PROD.exists():raise ValueError('no_replay')
    source=[]
    for n in (1,2,3):
        chapter=read(ROOT/f'data/fanqie_account_control/books/7302660145530539062/chapters/{n:05}.json')
        source.extend({'id':f'CH{n}-P{i:03}','chapter':n,'text':s} for i,s in enumerate(chapter['text'].splitlines(),1) if s.strip())
    PROD.mkdir();dump(PROD/'SOURCE.json',source);dump(PROD/'PLAN.json',{'authorization':'持续修复直到方向无意义或生产测试无问题；沿既有小说MiniMax文本范围','source_chapters':[1,2,3],'scope':'实际开篇两集90秒文本生产探针，不等于全69章连载归并验收','max_calls':11,'max_semantic_repairs_per_episode':1,'source_sha256':sha(source),'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(PROD);session.save();error=None;status='needs_attention';episodes=[]
    try:
        foundation=Foundation.model_validate(session.call('FOUNDATION',FOUNDATION_PROMPT,{'complete_source':source},Foundation)).model_dump();verify_refs(foundation,source)
        if [e['episode'] for e in foundation['episodes']]!=[1,2]:raise ValueError('episode_plan')
        if len({p['id'] for p in foundation['people']})!=len(foundation['people']) or len({p['id'] for p in foundation['places']})!=len(foundation['places']):raise ValueError('duplicate_registry')
        dump(PROD/'FOUNDATION.json',foundation)
        for n in (1,2):
            payload={'complete_source':source,'foundation':foundation,'episode':n,'previous_episode':episodes[-1] if episodes else {},'target_seconds':90}
            raw=session.call(f'E{n}_WRITE',WRITE_PROMPT,payload,Episode);dump(PROD/f'E{n}_RAW.json',raw)
            episode=validate_episode(raw,foundation,source,n);dump(PROD/f'E{n}_CANDIDATE_0.json',episode)
            review=check_review(session.call(f'E{n}_REVIEW',REVIEW_PROMPT,{**payload,'candidate':episode,'candidate_sha256':sha(episode)},EpisodeReview),episode,source);dump(PROD/f'E{n}_REVIEW_0.json',review)
            hard=[x for x in review['issues'] if x['severity']=='must_fix']
            if hard:
                wanted={x['shot_id'] for x in hard};raw=session.call(f'E{n}_REPAIR','只修指定镜头，输出完整镜头；其他镜头由程序原样保留。保持本镜头时长不变。意见不是权威，核对完整原文，不能新增无据剧情。'+WRITE_PROMPT,{**payload,'candidate':episode,'issues':hard,'allowed_shot_ids':sorted(wanted)},ShotRepairs)
                episode=replace_shots(episode,raw,wanted,foundation,source);dump(PROD/f'E{n}_CANDIDATE_1.json',episode)
                review=check_review(session.call(f'E{n}_REVIEW_FINAL',REVIEW_PROMPT,{**payload,'candidate':episode,'candidate_sha256':sha(episode)},EpisodeReview),episode,source);dump(PROD/f'E{n}_REVIEW_1.json',review)
            episodes.append(episode);dump(PROD/f'E{n}_FINAL.json',episode)
            if any(x['severity']=='must_fix' for x in review['issues']):status='needs_revision';break
        else:status='machine_pass_pending_primary'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(PROD/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'pending':session.pending,'error':error,'episodes_completed':len(episodes),'primary_acceptance':'pending'});print(json.dumps(read(PROD/'RESULT.json')),flush=True)
if __name__=='__main__':main()
