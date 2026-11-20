"""Fixed staging and model-authored action timing for a two-person conversation."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

PROMPT = Path(__file__).with_name('prompts')/'conversation_direction.md'
CHECKS = ('spatial_layout', 'identity', 'action_pace', 'speaker_visibility')


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stage_for(script, north, south):
    if {north, south} != {c['name'] for c in script['characters']} or north == south:
        raise ValueError('Choose the two existing characters for the two fixed seats')
    return {
        'north_person': north, 'south_person': south,
        'seats': {north: [0, 1], south: [0, -1]},
        'table_bounds': [-1, -0.45, 1, 0.45],
        'camera_side': 'west',
        'cameras': {
            'master': {'position': [-3, 0], 'target': [0, 0]},
            'north_close': {'position': [-2.5, -1.4], 'target': [0, 1]},
            'south_close': {'position': [-2.5, 1.4], 'target': [0, -1]},
        },
    }


def camera_for(shot, stage):
    actors = set(shot['participants'])
    if actors == {stage['north_person'], stage['south_person']}:
        return 'master'
    if actors == {stage['north_person']}:
        return 'north_close'
    if actors == {stage['south_person']}:
        return 'south_close'
    raise ValueError('Unsupported visibility group for this conversation staging')


def validate_plan(plan, script, script_hash):
    if plan.get('schema') != 'conversation_direction/v1' or plan.get('script_sha256') != script_hash:
        raise ValueError('Direction plan does not match the locked script')
    stage = plan['stage']
    if stage != stage_for(script, stage['north_person'], stage['south_person']):
        raise ValueError('Fixed seats, table and camera axis cannot change between shots')
    rows = plan['shots']
    if [r['shot_id'] for r in rows] != [s['shot_id'] for s in script['shots']]:
        raise ValueError('Direction plan must cover every shot exactly once')
    for row, shot in zip(rows, script['shots']):
        if row['camera_id'] != camera_for(shot, stage):
            raise ValueError('Camera must match the locked visible participants')
        onset = row['dialogue_start_seconds']
        if type(onset) not in (int, float) or not math.isfinite(onset) or not 0 <= onset <= 0.5:
            raise ValueError('Dialogue must start within the first 0.5 seconds')
        for field in ['start_frame', 'end_frame', 'performance', 'transition']:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f'Missing direction field: {field}')
        beats = row['action_beats']
        if not beats or beats[0]['start'] != 0:
            raise ValueError('Visible action must begin on the first frame')
        cursor = 0
        duration = shot['end_seconds'] - shot['start_seconds']
        for beat in beats:
            a, b = beat['start'], beat['end']
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in [a, b]):
                raise ValueError('Action timing must contain finite numbers')
            if a < cursor or a-cursor > 0.4 + 1e-9 or not a < b <= duration or not beat.get('action'):
                raise ValueError(f"{shot['shot_id']}: Invalid action timing or an unmotivated idle gap")
            if re.search(r'说出|说话|说完|开口|话音|嘴|字音|对白|台词|发音|结论',beat['action']):
                raise ValueError(f"{shot['shot_id']}: 动作时间表只写可见动作，说话起点由dialogue_start_seconds单独控制；不能安排结论几秒内说完")
            cursor = b
        if duration-cursor > 0.4 + 1e-9:
            raise ValueError(f"{shot['shot_id']}: Action plan leaves an unmotivated trailing hold")


def compile_prompt(script, shot, plan, *, timing_mode='precise', use_input_first_frame=False):
    stage = plan['stage']
    row = next(r for r in plan['shots'] if r['shot_id'] == shot['shot_id'])
    north, south = stage['north_person'], stage['south_person']
    geometry = (f'空间锁定：{north}始终坐在办公桌北侧朝南，{south}始终坐在桌南侧朝北；'
                '二人隔着整张桌子面对面，桌面横隔在两人之间，不是相邻座位、同侧或并排。'
                '椅子、桌子和窗户全片不移动。切镜只改变摄影机，不改变人物座位。'
                '摄影机全程在南北对话轴线西侧，不越轴、不镜像翻转。')
    view = {
        'master': (f'西侧平视固定双人中景，摄影机正对桌子中央，从对话轴线的侧面拍摄。'
                   f'{north}在画面左侧朝右，{south}在画面右侧朝左，只呈现两人朝内的侧脸。'
                   '两张椅子位于桌子相对两边，胸口和膝盖朝向对方；完整桌面横在两具躯干之间，'
                   '桌子中央位于画面中央，人物身体分列桌子左右，摄影机位置和焦距保持不变。'),
        'north_close': f'西南机位朝北侧拍{north}中近景，{north}居画左、看画右的{south}；{south}及其肩膀不入画。',
        'south_close': f'西北机位朝南侧拍{south}中近景，{south}居画右、看画左的{north}；{north}及其肩膀不入画。',
    }[row['camera_id']]
    roles = '；'.join(f"{c['name']}：{c['appearance']}，{c['wardrobe']}" for c in script['characters'])
    if timing_mode not in {'precise','ordered'}:
        raise ValueError('Unsupported prompt timing mode')
    beats = ('；'.join(f"动作{i}：{b['action']}" for i,b in enumerate(row['action_beats'],1))
             if timing_mode=='ordered' else
             '；'.join(f"{b['start']:g}—{b['end']:g}秒：{b['action']}" for b in row['action_beats']))
    onset=('镜头开始就立即接话，不先等待完成手势，' if timing_mode=='ordered'
           else f"在第{row['dialogue_start_seconds']:g}秒以内立即接话，")
    opening = ('严格使用输入图片的现有姿态作为第一动作的准备状态，从该姿态立即执行动作1'
               if use_input_first_frame else row['start_frame'])
    composition = f"画面结构：{shot['composition']}。" if shot.get('composition') else ''
    if use_input_first_frame:
        # A reviewed real frame is the spatial authority. Repeating text-to-video
        # seat coordinates here can make the model restage the established scene.
        geometry = '空间锁定：保持输入首帧中人物、桌椅、窗户及道具的原有位置和朝向。'
        view = '沿用输入首帧的构图、景别、摄影机位置和焦距，人物始终在原座位完成后续动作。'
        composition = ''
    return (f"现实主义竖屏短片，真实皮肤与材质，9:16，时长{shot['end_seconds']-shot['start_seconds']:g}秒。"
            f"{geometry}固定机位：{view}{composition}人物：{roles}。光线：{shot['lighting']}。"
            f"首帧：{opening}。动作节拍：{beats}。表演：{row['performance']}。"
            f"{onset}动作与对白并行，短促利落但不夸张，"
            '不慢动作、不拖长抬眼、点头或翻页，不先沉默等待再开口；口语清晰自然，不靠拖腔填时长。'
            f"只有入画的{shot['dialogue_speaker']}向对面角色完整说出：“{shot['dialogue']}”。"
            '声音必须属于这位说话人并遵守现场声音中的角色声线设定，嘴部动作与该人对白同步；其他人倾听、嘴部静止，不代说。禁止旁白、解说、内心独白。'
            f"字幕内容严格为：“{shot['dialogue']}”。下方字幕安全区不遮手和道具。"
            f"现场声音：{shot['audio']}。尾帧：{row['end_frame']}。"
            f"镜外剪辑：{row['transition']}。对白结束后的无意义停留不超过0.3秒。"
            f"道具连续性：{('以输入首帧的实际手位、道具开合和位置为起点，连续执行上述动作直到所述尾帧；不得先复位或重演上一段已完成的动作' if use_input_first_frame else shot['continuity'])}。只生成一个固定连续镜头，无内部切镜或变焦。")


def generate_plan(script_path, output_dir, north, south, client, draft_path=None, review_feedback='', baseline_path=None):
    if draft_path and baseline_path:
        raise ValueError('Choose a same-script draft or a previous-script baseline, not both')
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError('Use a new output directory to preserve previous model requests and reviews')
    output_dir.mkdir(parents=True, exist_ok=True)
    source = Path(script_path)
    script = json.loads(source.read_text(encoding='utf-8'))
    stage = stage_for(script, north, south)
    prompt = PROMPT.read_text(encoding='utf-8')
    # Omit superseded camera prose and long generation traces. The original
    # script remains hash-locked; only its action/prop continuity is revised.
    context = {k: script[k] for k in ('title', 'target_duration_seconds', 'characters',
                'premise', 'core_message', 'resolution', 'global_continuity') if k in script}
    fields = ('shot_id', 'participants', 'blocking', 'composition', 'dialogue_speaker',
              'dialogue', 'action', 'start_frame', 'end_frame', 'continuity')
    # Each API task starts at zero; showing the global edit timeline caused
    # otherwise valid directions to copy absolute times into local action beats.
    context['shots'] = [dict({k: shot[k] for k in fields if k in shot},
                             duration_seconds=shot['end_seconds']-shot['start_seconds'])
                        for shot in script['shots']]
    messages = [{'role':'system', 'content':prompt}, {'role':'user','content':json.dumps({
        'fixed_stage':stage, 'script':context,
        'feedback':'人物必须始终隔桌对坐，不能一会在旁边一会在对面；动作更利落，有急于确认问题的劲头，去掉开口前长时间等待。台词及45秒时间线不改。'},ensure_ascii=False)}]
    prior_path = draft_path or baseline_path
    if prior_path:
        draft = json.loads(Path(prior_path).read_text(encoding='utf-8'))
        if draft_path and draft.get('script_sha256') != file_hash(source):
            raise ValueError('Revision draft belongs to a different script')
        if not review_feedback.strip():
            raise ValueError('A revision requires concrete review feedback')
        rows = [{k:v for k,v in row.items() if k != 'camera_id'} for row in draft['shots']]
        prefix = ('以下是上一版剧本的真实执行计划，当前剧本已定点修订。请对照当前输入只修改不再匹配的动作与首尾状态，不将其当作同一剧本续审。\n'
                  if baseline_path else '执行审阅未通过。')
        messages.extend([{'role':'assistant','content':json.dumps({'shots':rows},ensure_ascii=False)},
                         {'role':'user','content':prefix+'请按以下问题逐项修正，保留正确内容并返回完整 shots：\n'+review_feedback}])
    plan = None
    for attempt in range(1, 3):
        (output_dir/f'request_{attempt}.json').write_text(json.dumps(messages,ensure_ascii=False,indent=2),encoding='utf-8')
        raw = client.chat_completion_tracked(messages, caller='conversation_direction', temperature=0.2,
                                             json_mode=True, use_cache=False)
        (output_dir/f'response_{attempt}.txt').write_text(raw or '',encoding='utf-8')
        if not raw:
            raise RuntimeError('Direction model returned no result')
        try:
            data = json.loads(raw)
            if set(data) != {'shots'}:
                raise ValueError('Return only shots')
            for row, shot in zip(data['shots'], script['shots']):
                row['camera_id'] = camera_for(shot, stage)
            plan = dict(schema='conversation_direction/v1', script_sha256=file_hash(source), stage=stage,
                        shots=data['shots'], created_at=datetime.now(timezone.utc).isoformat(),
                        generation={'method':'project_llm_direction','model':getattr(client,'model_name',''),
                                    'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                                    'draft_sha256':file_hash(draft_path) if draft_path else None,
                                    'baseline_sha256':file_hash(baseline_path) if baseline_path else None,
                                    'baseline_script_sha256':draft.get('script_sha256') if baseline_path else None,
                                    'feedback_sha256':hashlib.sha256(review_feedback.encode()).hexdigest(),
                                    'attempt':attempt}, video_generation_submitted=False)
            validate_plan(plan,script,file_hash(source))
            break
        except (ValueError,KeyError,TypeError) as exc:
            if attempt==2:
                raise
            messages.extend([{'role':'assistant','content':raw},{'role':'user','content':str(exc)+'。请保留正确内容，只修正计划，重新返回完整shots。'}])
    (output_dir/'direction_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    for shot in script['shots']:
        (output_dir/f"{shot['shot_id']}.prompt.txt").write_text(compile_prompt(script,shot,plan),encoding='utf-8')
    return plan


def require_reviewed_reference(folder, path, plan_hash):
    review_path = folder/'reference_reviews'/f'{file_hash(path)}.json'
    if not review_path.exists():
        raise ValueError('参考视频未经空间、身份、节奏和说话人入画检查，不能继续传播到后续镜头')
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if review.get('decision') == 'accepted_by_user':
        acceptance_path=(folder/review.get('acceptance_file','')).resolve()
        if not acceptance_path.is_relative_to(folder.resolve()) or not acceptance_path.is_file():
            raise ValueError('User acceptance evidence is missing')
        acceptance=json.loads(acceptance_path.read_text(encoding='utf-8'))
        if (acceptance.get('status')=='accepted' and acceptance.get('video_sha256')==file_hash(path)
                and acceptance.get('user_statement') and acceptance.get('recorded_at')
                and review.get('asset_sha256')==file_hash(path)
                and review.get('direction_sha256')==plan_hash):
            return
        raise ValueError('User acceptance does not match this reference')
    if (review.get('asset_sha256') != file_hash(path) or review.get('direction_sha256') != plan_hash
            or set(review.get('checks',{})) != set(CHECKS)
            or not all(review['checks'][c] is True for c in CHECKS)
            or not review.get('evidence') or not review.get('reviewed_at')):
        raise ValueError('参考镜头未通过当前空间和节奏约束，禁止继续使用')
    for evidence in review['evidence']:
        local = (folder/evidence).resolve()
        if not local.is_relative_to(folder) or not local.is_file():
            raise ValueError('参考镜头审核证据缺失')
