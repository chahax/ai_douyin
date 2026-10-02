"""Reference-bound authoring; semantic approval is explicit and separate from validation."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_director_pipeline import author_stage
from src.content_factory.director_json import authored_value, repair_failed_output
from src.content_factory.emotional_focus import validate_emotional_focus

STAGES = ('story', 'emotion', 'visual', 'performance')
REFERENCE = ROOT / 'data/reference_reviews/loneliness_20260919/ANALYSIS.md'
PROMPT = ROOT / 'src/content_factory/prompts/reference_director_v3.md'
STORY_PROMPT = ROOT / 'src/content_factory/prompts/reference_story_v4.md'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def check(ok, why):
    if not ok:
        raise ValueError(why)

def nonempty(row, keys):
    check(all(isinstance(row.get(k), str) and row[k].strip() for k in keys), 'Missing descriptive fields: '+str(keys))

def stage_prompt(stage):
    if stage == 'story':
        return STORY_PROMPT.read_text(encoding='utf-8')
    source = PROMPT.read_text(encoding='utf-8')
    shared = source.split('stage=emotion：', 1)[0].strip()
    marker = 'stage='+stage+'：'
    section = source.split(marker,1)[1]
    later = STAGES[STAGES.index(stage)+1:]
    if later:
        section = section.split('stage='+later[0]+'：',1)[0]
    return ('你是短片导演。只输出当前阶段 '+stage+' 的合法JSON对象，不用代码围栏。'
            '字段值中引用别人说的话时使用中文「」符号，不得嵌入未转义的英文双引号。'
            '已审上游材料只提供上下文，不要返回上游格式，不增删剧情和对白。'
            '空间与行为因果必须成立。共同创作规则：\n'+shared+
            '\n当前唯一输出合同：\n'+marker+section)

def validate(stage, value, previous):
    if stage == 'story':
        nonempty(value, ['title','initial','ending'])
        check(set(value['characters']) == {'A','B'}, 'Two characters required')
        for c in value['characters'].values():
            nonempty(c,['name','want','fear'])
        check([b['id'] for b in value['beats']] == ['B01','B02','B03','B04'], 'Four ordered story beats')
        check(all(type(b['duration']) is int and 4 <= b['duration'] <= 10 for b in value['beats']), 'Story durations')
        check(26 <= sum(b['duration'] for b in value['beats']) <= 34, 'Story length')
        count = 0
        for b in value['beats']:
            nonempty(b,['event','change'])
            check(len(b['dialogue']) <= 2, 'Too many lines')
            for l in b['dialogue']:
                check(l['speaker'] in ('A','B'), 'Unknown speaker')
                nonempty(l,['text'])
                count += len(l['text'])
        check(count <= 110, 'Dialogue density including punctuation')
    elif stage == 'emotion':
        nonempty(value, ['title','premise','relationship_before','relationship_after'])
        check(set(value['characters']) == {'A','B'}, 'Two named characters required')
        for c in value['characters'].values():
            nonempty(c, ['name','want','fear','concealed_feeling'])
        beats = value['beats']
        if 'story' in previous:
            check([(b['id'],b['duration'],b['dialogue']) for b in beats] ==
                  [(b['id'],b['duration'],b['dialogue']) for b in previous['story']['beats']], 'Locked story changed')
        check(4 <= len(beats) <= 6, '4–6 emotional beats required')
        check([b['id'] for b in beats] == [f'B{i+1:02}' for i in range(len(beats))], 'Beat ordering')
        check(all(type(b['duration']) is int and 4 <= b['duration'] <= 10 for b in beats), 'Beat duration')
        check(24 <= sum(b['duration'] for b in beats) <= 45, 'Total duration')
        for b in beats:
            nonempty(b, ['trigger','before','after','intended_action','interruption','choice','visible_consequence','audience_discovers'])
            check(b['actor'] in value['characters'], 'Unknown actor')
            check(all(type(b[k]) is int and 0 <= b[k] <= 5 for k in ('intensity_before','intensity_after')), 'Intensity scale')
            check(b['reference_ids'] and set(b['reference_ids']) <= {'R01','R02','R03','R04'}, 'Unknown reference evidence')
            for line in b['dialogue']:
                check(line['speaker'] in value['characters'], 'Unknown speaker')
                nonempty(line, ['text'])
    elif stage == 'visual':
        check(value['space']['entrance_count'] == 1, 'Ambiguous entry count')
        nonempty(value['space'], ['layout','door_hinge','door_opening','axis'])
        check(set(value['space']['opening_positions']) == {'A','B'}, 'Opening positions')
        shots = value['shots']
        check(len({s['id'] for s in shots}) == len(shots), 'Duplicate shot')
        beats = previous['emotion']['beats']
        check(set(s['beat_id'] for s in shots) == set(b['id'] for b in beats), 'Unknown/missing beat')
        check([s['beat_id'] for s in shots] == sorted(s['beat_id'] for s in shots), 'Shot order')
        for b in beats:
            group = [s for s in shots if s['beat_id'] == b['id']]
            check(1 <= len(group) <= 3, 'Shot count per beat')
            cursor = 0
            for s in group:
                check(s['start'] == cursor and s['end'] > cursor, 'Shot gap/overlap')
                check(s['size'] in ('wide','medium','close','detail'), 'Unknown size')
                check(s['subject'] in ('A','B','both','environment'), 'Unknown subject')
                nonempty(s, ['camera_side','composition','visible_evidence','cut_reason','continuity_anchor'])
                cursor = s['end']
            check(cursor == b['duration'], 'Shot coverage')
        check(any(s['size'] == 'wide' for s in shots), 'Establish space')
        check(any(s['size'] == 'close' and s['subject'] in ('A','B') for s in shots), 'Readable reaction required')
    else:
        beats = previous['emotion']['beats']
        check([b['id'] for b in value['beats']] == [b['id'] for b in beats], 'Performance beat order')
        shots = {s['id']:s for s in previous['visual']['shots']}
        for b, authored in zip(beats, value['beats']):
            check([{'speaker':l['speaker'],'text':l['text']} for l in authored['lines']] == b['dialogue'], 'Dialogue changed')
            cursor = 0
            for l in authored['lines']:
                check(cursor <= l['start'] < l['end'] <= b['duration'], 'Speech overlap/outside beat')
                check(len(l['text'])/(l['end']-l['start']) <= 7, 'Speech too fast including punctuation')
                cursor = l['end']
            ends = {'A':0,'B':0}
            check(authored['actions'], 'Missing action')
            for a in authored['actions']:
                check(a['actor'] in ends, 'Unknown actor')
                check(ends[a['actor']] <= a['start'] < a['end'] <= b['duration'], 'Action overlap/outside beat')
                ends[a['actor']] = a['end']
                nonempty(a, ['trigger','description','body_before','body_after','face_change','gaze_target'])
                s = shots[a['readable_in_shot']]
                check(s['beat_id'] == b['id'] and max(s['start'],a['start']) < min(s['end'],a['end']), 'Action invisible in cited shot')
                check(type(a['intensity']) is int and 0 <= a['intensity'] <= 5, 'Performance intensity')
            check(set(authored['end_positions']) == {'A','B'}, 'Missing final blocking')
    validate_emotional_focus(stage, value, previous)

def approved(folder):
    review = read(folder/'review.json')
    check(review.get('decision') == 'passed' and review.get('unresolved') == [], 'Actual semantic review required')
    check(review.get('candidate_sha256') == digest(folder/'candidate.json'), 'Stale review')
    check(review.get('findings') and all(f.get('evidence') and f.get('finding') for f in review['findings']), 'Review evidence required')
    check(read(folder/'validation.json')['status'] == 'structure_valid_semantics_pending', 'Structure failed')
    if (folder/'assembly.json').exists():
        # Only this explicit, lossless beat assembly is accepted; each source
        # still needs its own raw-provenance and actual semantic approval.
        assembly = read(folder/'assembly.json')
        check(assembly.get('recipe') == 'approved_performance_beats/v1', 'Unknown assembly recipe')
        values = []
        for source in assembly['sources']:
            origin = Path(source['folder'])
            check(not (origin/'assembly.json').exists(), 'Nested assemblies are not allowed')
            check(source['candidate_sha256'] == digest(origin/'candidate.json') and
                  source['review_sha256'] == digest(origin/'review.json'), 'Stale beat assembly')
            values.append(approved(origin))
        check([v['id'] for v in values] == ['B01', 'B02', 'B03', 'B04'], 'Assembly needs four ordered beats')
        expected = {'beats': [{k: v for k, v in row.items() if k != 'risks'} for row in values],
                    'risks': [risk for row in values for risk in row['risks']]}
    else:
        expected = authored_value(folder)
    check(read(folder/'candidate.json') == expected, 'Candidate must preserve model output or replayed derivation')
    return read(folder/'candidate.json')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--stage', choices=STAGES, required=True)
    parser.add_argument('--revision', help='Previous rejected candidate, retained as revision input')
    parser.add_argument('--feedback', help='Specific review findings to address')
    parser.add_argument('--feedback-file', help='UTF-8 file containing specific review findings; exclusive with --feedback')
    parser.add_argument('--adopt-story', help='Previously reviewed story folder; copied with provenance and revalidated')
    parser.add_argument('--attempt', default='first', help='Unique attempt name; previous attempts are retained')
    parser.add_argument('--adopt-run', help='Revalidate and copy approved upstream stages from another run')
    parser.add_argument('--thinking',choices=['adaptive','disabled'],default='adaptive')
    parser.add_argument('--temperature',type=float,default=1.0)
    parser.add_argument('--max-tokens',type=int,default=32768)
    parser.add_argument('--model',choices=['MiniMax-M3','MiniMax-M2.7'],default='MiniMax-M3')
    args = parser.parse_args()
    if args.feedback_file:
        check(not args.feedback, 'Use either --feedback or --feedback-file')
        args.feedback = Path(args.feedback_file).read_text(encoding='utf-8-sig').strip()
        check(bool(args.feedback), 'Feedback file is empty')
    run = Path(args.run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    binding = {'prompt_sha256':digest(PROMPT),'story_prompt_sha256':digest(STORY_PROMPT),'reference_sha256':digest(REFERENCE),'runner_sha256':digest(Path(__file__)),'author_sha256':digest(ROOT/'scripts/test_director_pipeline.py'),'syntax_sha256':digest(ROOT/'src/content_factory/director_json.py'),'thinking':args.thinking if args.model=='MiniMax-M3' else 'provider_default','temperature':args.temperature,'max_tokens':args.max_tokens,'model':args.model}
    manifest = run/'protocol.json'
    if manifest.exists():
        check(read(manifest) == binding, 'Protocol changed; start separate run')
    else:
        manifest.write_text(json.dumps(binding,indent=2),encoding='utf-8')
    if args.adopt_run:
        source_run = Path(args.adopt_run).resolve()
        old_selection = read(source_run/'stage_selection.json')
        adopted = {}
        for stage in STAGES[:STAGES.index(args.stage)]:
            origin = source_run/old_selection.get(stage,stage)
            value = approved(origin)
            validate(stage,value,adopted)
            check(not (run/stage).exists(), 'Adoption cannot overwrite upstream')
            shutil.copytree(origin,run/stage)
            (run/stage/'origin.json').write_text(json.dumps({'path':str(origin),'candidate_sha256':digest(origin/'candidate.json'),'review_sha256':digest(origin/'review.json'),'new_model_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
            adopted[stage]=value
    if args.adopt_story:
        origin = Path(args.adopt_story).resolve()
        value = approved(origin)
        validate('story', value, {})
        check(not (run/'story').exists(), 'Adoption cannot overwrite story')
        shutil.copytree(origin,run/'story')
        (run/'story/origin.json').write_text(json.dumps({'path':str(origin),'candidate_sha256':digest(origin/'candidate.json'),'review_sha256':digest(origin/'review.json'),'new_model_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
    selection_file = run/'stage_selection.json'
    selection = read(selection_file) if selection_file.exists() else {}
    previous = {s:approved(run/selection.get(s,s)) for s in STAGES[:STAGES.index(args.stage)]}
    evidence = {
        'R01':'20–31秒：前景回复手机与后景吃东西形成反差，人物有目的地行动。',
        'R02':'33.5–39秒：独坐老人、手机、面部反应让关心落到具体人物身上。',
        'R03':'50.5–58秒：叫醒、递泡面、催拍，动作有因果且推动事件。',
        'R04':'93.5–103.5秒：老人看新闻时愤怒，接到关心后逐渐微笑，刺激导致可见反应转变。'}
    payload = {'stage':args.stage,'brief':'重写《玄关一步》父女归家冲突。旧稿的问题是门口不清、固定全身站桩、台词解释过多。目标是有情感代价的动作和可见转变。','reference_evidence':evidence,'reference_analysis_sha256':digest(REFERENCE),**previous}
    if args.feedback:
        payload['review_feedback']=args.feedback
    if args.revision:
        check(bool(args.feedback), 'Revision needs explicit feedback')
        source = Path(args.revision).resolve()
        payload['revision'] = {'source_path':str(source),'source_sha256':digest(source),'candidate':read(source),'feedback':args.feedback}
    check(args.attempt.replace('_','').isalnum(), 'Invalid attempt name')
    folder_name = args.stage if args.attempt == 'first' else args.stage+'_'+args.attempt
    folder = run/folder_name
    check(not folder.exists(), 'Attempt already exists; inspect its state before retrying')
    selection[args.stage] = folder_name
    selection_file.write_text(json.dumps(selection,indent=2),encoding='utf-8')
    if args.stage == 'emotion':
        payload['lock'] = 'story 已审核，事件、时长、对白全部保留。只扩展情绪因果，不新增背景或物件。'
    try:
        value = author_stage(folder,stage_prompt(args.stage),payload,args.stage,temperature=args.temperature,thinking=args.thinking,max_tokens=args.max_tokens,model=args.model)
    except Exception:
        # The failed author record and raw response remain intact. A repair is
        # disclosed separately and can never substitute for stage/semantic review.
        if not (folder/'raw.txt').exists() or not (folder/'response.json').exists():
            raise
        value = repair_failed_output(folder)
    try:
        validate(args.stage,value,previous)
        if args.stage == 'story':
            check(bool(value.get('emotional_focus')), 'New story requires emotional focus budget')
        status = {'status':'structure_valid_semantics_pending','media_approved':False}
    except Exception as exc:
        status = {'status':'structure_failed','error':str(exc),'media_approved':False}
    (folder/'validation.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))

if __name__ == '__main__':
    main()
