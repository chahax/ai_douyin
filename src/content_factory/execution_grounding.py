"""Source-bound textual grounding of a failed S01, never a model visual review."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from .ark_opening_frame import _bytes, _inside, _read, _sha
from .script_video_review import REVIEW_CHECKS
from .video_campaign import (_run_series, _failed_count, failure_limit,
                             RESOLVED_ATTEMPT_STATUSES)
from src.trend_intelligence.production_revision import parse_unique_json

SCHEMA = 'execution_grounding_plan/v1'
RUN_SCHEMA = 'execution_grounding_revision/v1'
MODEL = 'MiniMax-M3'
OUTPUT_KEYS = frozenset({'visual_bindings', 'action_constraints'})
GUIDE_PATH = Path(__file__).resolve().parents[2] / 'docs/reference/seedance/2026-09-07/seedance_2_0_prompt.md'
GUIDE_INSTRUCTION = (
    '用户保存的 Seedance 2.0 指南建议：多主体先用图片1及两三个稳定外观特征绑定名字或标签，'
    '人物和道具均可定义，后文持续使用同一名字，减少复杂空间长文。'
    '仅将人工已审文字记录支持的近远位置映射到原剧本道具自然名；这些名字只用于提示，不打印在画面。'
    '不添加精确时间指令。'
)
SYSTEM_PROMPT = (
    '你是本项目的视频动作定位编辑。你只接收锁定剧本、已审首图的人工文字记录和上一失败视频的人工文字记录，'
    '没有接收或看过图片、视频、音频，不得声称你已看图、听声音或审核通过。'
    '只输出JSON，恰好两个键visual_bindings与action_constraints，每个值为简短中文字符串数组。'
    'visual_bindings只澄清原画面中人物与其本人合同、对方合同的对应、画面左右和手的接触范围；'
    'action_constraints只针对已观察失败澄清原动作的持续接触、不可换纸等限制。'
    '必须服从frozen_shot中的原动作、首态和尾态，不能重写动作、改变左右手或增加动作步骤，不能改变并行关系。'
    '不新增人物、物品、金额、数字、台词、时间、停顿、镜头或光线，不重复原对白；不让角色报出P1等内部代号。'
    '不修改结局、情绪、声音和语速，不把问题历史写成待生成动作。'
    '动作仍将按原文独立附在这些说明之后。你的输出只是候选定位说明，必须经过独立文本审核才可用于生成。'
)
REVISION_GUIDANCE = (
    '本次只修订被独立审核拒绝的定位说明，不修改冻结剧本。'
    '每句不超过七十个字符，短句分项。visual_bindings先用图片1及稳定外观定义人物，'
    '然后只写人物与本人纸的静态对应；不得夹带动作、视线、情绪、语速或表演。'
    'action_constraints只澄清原有左手持续接触本人纸、不换纸的限制，不重复或改写原动作段，'
    '不增加右手动作、视线锁定、节奏、停顿或手从开始即精确按某纸角的要求。'
    '原动作与表演会在说明后按原文附加。不要复制它们，也不要另写新的动作时间表。'
    '只能依据实际独立拒绝反馈修订；模型仍仅接收文本，不曾看图或视频。'
)
FOCUS_NAME = 'terminal-attention'
FOCUS_SCHEMA = 'execution_grounding_focus/v1'
TERMINAL_GUIDANCE = (
    '本次只澄清冻结剧本已有的注意力与尾态，不修改动作、对白、原末态或表演。'
    '分别读取每个角色的源视线与源尾态；不能让两人全段看纸，也不能为澄清末态新增抬头、转头、注视步骤。'
    '视线目标以各自源文本指定的具体人或纸为准，不能将原本指向纸张的目标解释为看人。'
    '保留上一实际执行中经人工反馈确认改善的人物与纸张对应；visual_bindings必须逐条原样复用previous_actual_execution.visual_bindings。'
    'action_constraints可以简短澄清原有持续接触和源视线，不能复制整个动作段、增加新动作顺序、精确时点或停顿。'
    '每条不超过七十字符。定位说明与最终完整执行提示仍须独立审核，模型仅接收文字证据。'
)
TERMINAL_SYSTEM_PROMPT = (
    '你是本项目的视频终态定位编辑。你只接收锁定剧本、人工首图文字审核、上一实际执行提示词和失败视频的人工文字审核，'
    '没有接收或看过图片、视频、音频，不得声称你已看图、听声音或审核通过。'
    '只输出JSON，恰好两个键visual_bindings与action_constraints，值均为简短中文字符串数组，每条不超过七十字符。'
    'visual_bindings必须逐条原样复用previous_actual_execution.visual_bindings，不再发明识别关系。'
    'action_constraints仅澄清原有持续接触和frozen_shot中各角色已有的注意力与尾态。'
    '分别保持各自源末态，不将两人都写成全程看纸；不添加抬头、转头、注视、对视等动作步骤，'
    '不新增动作、人物、道具、金额、数字、台词、时点、停顿、镜头或光线，不改左右手、动作并行关系、情绪或语速。'
    '不要复制动作或表演段，原文会独立附在说明之后。候选仍须最终独立文本审核，不能输出通过。'
)


def _identity(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': _sha(path.read_bytes())}


def validate_model_value(value, source_text=None, *, concise=False):
    if not isinstance(value, dict) or set(value) != OUTPUT_KEYS:
        raise ValueError('Grounding output must contain only visual_bindings and action_constraints')
    for key, items in value.items():
        if (not isinstance(items, list) or not 1 <= len(items) <= 6
                or any(not isinstance(item, str) or not item.strip() or len(item) > (70 if concise else 500) for item in items)):
            raise ValueError('Grounding requires short nonempty string arrays: ' + key)
        for item in items:
            # Internal Pn IDs are rendered from the real source; new numerical
            # timing/amount instructions cannot slip into this narrow profile.
            without_ids = re.sub(r'(?<![A-Za-z0-9_])P[1-9][0-9]*(?![A-Za-z0-9_])', '', item)
            without_ids = re.sub(r'图片\s*1(?![0-9])', '', without_ids)
            if isinstance(source_text, str) and re.search(r'(?<![A-Za-z0-9])A4(?![A-Za-z0-9])', source_text):
                without_ids = re.sub(r'(?<![A-Za-z0-9])A4(?![A-Za-z0-9])', '', without_ids)
            if re.search(r'[0-9]', without_ids) or '\n' in item or '\r' in item:
                raise ValueError('Grounding cannot introduce numerical instructions or additional prompt sections')
    return value


def validate_grounding_value(value, source):
    focus = source.get('focus')
    value = validate_model_value(value, _bytes(source['frozen_shot']).decode('utf-8'),
                                 concise=bool(source.get('parent_revision') or focus))
    if focus is not None:
        if (focus != {'schema': FOCUS_SCHEMA, 'name': FOCUS_NAME, 'guidance': TERMINAL_GUIDANCE}
                or value['visual_bindings'] != source['previous_actual_execution']['visual_bindings']):
            raise ValueError('Terminal attention must retain the exact previously executed visual bindings')
    return value


def _ledger_bound_review(folder, attempt, review_path, review):
    """Bind original submitted bytes plus the campaign's serialized copies.

    video_campaign.review hashes the submitted file. Current releases preserve
    its bytes in quality_review and history; older runs may have reserialized
    copies, so their bytes need not share that hash.
    The original exact SHA must still exist; semantic equality alone is not a
    substitute for those original bytes.
    """
    digest = attempt.get('review_sha256', '')
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise ValueError('The campaign has no exact submitted review SHA')
    history = folder / 'quality_review_history' / 'S01' / f'{digest}.json'
    if _sha(review_path.read_bytes()) == digest:
        original = review_path
    else:
        candidates = [path for path in folder.glob('*.json')
                      if path != review_path and _sha(path.read_bytes()) == digest]
        if len(candidates) != 1:
            raise ValueError('Locate the unique original submitted review matching the recorded SHA')
        original = candidates[0]
    if _read(original) != review or _read(history) != review:
        raise ValueError('Submitted review, quality review and SHA-named history disagree')
    return _identity(original), _identity(history)


def collect_grounding_source(run_dir, image, failed_run, config, *, previous_grounding_run=None, feedback_file=None, focus=None):
    """Recheck actual source/first-frame review and the latest recorded failure."""
    if bool(previous_grounding_run) != bool(feedback_file):
        raise ValueError('Provide both previous-grounding-run and its independent feedback-file')
    if focus not in (None, FOCUS_NAME):
        raise ValueError('Unsupported execution grounding focus')
    from .compact_execution import _build
    base = _build(run_dir, image, config)  # v1 projection only; no grounding recursion.
    folder = Path(run_dir).resolve()
    manifest = _read(folder / 'production.json')
    campaign_path = Path(manifest.get('campaign_path', '')).resolve()
    campaign = _read(campaign_path)
    series_id = _run_series(campaign, manifest, folder)
    if (campaign.get('holds') or _failed_count(campaign) >= failure_limit(campaign)
            or campaign.get('status') == 'paused_for_human_review'):
        raise ValueError('Grounding cannot clear campaign holds or the accumulated failure limit')
    if any(row.get('status') not in RESOLVED_ATTEMPT_STATUSES for row in campaign.get('attempts', [])):
        raise ValueError('Reconcile outstanding generation or review before grounding another execution')
    previous_folder = _inside(failed_run, campaign_path.parent)
    if previous_folder == folder:
        raise ValueError('Grounding must target a fresh run and preserve the previous failed run')
    previous_manifest = _read(previous_folder / 'production.json')
    if (Path(previous_manifest.get('campaign_path', '')).resolve() != campaign_path
            or _run_series(campaign, previous_manifest, previous_folder) != series_id
            or any(previous_manifest.get(key) != manifest.get(key) for key in (
                'script_sha256', 'direction_sha256', 'provider', 'api_model', 'api_base_url'))):
        raise ValueError('Grounding needs the same script, direction, model and current campaign series')
    failed = [row for row in campaign.get('attempts', [])
              if row.get('status') == 'failed' and row.get('shot') == 'S01'
              and row.get('series_id', 'legacy') == series_id]
    if not failed or Path(failed[-1]['run_dir']).resolve() != previous_folder:
        raise ValueError('Grounding must use the latest actual failed S01 in this series')
    attempt = failed[-1]
    record_path = previous_folder / 'S01.json'
    record = _read(record_path)
    review_path = previous_folder / 'S01.quality_review.json'
    review = _read(review_path)
    video = _inside(record.get('local_video', ''), previous_folder)
    if (record.get('status') != 'downloaded' or record.get('campaign_attempt_id') != attempt['id']
            or record.get('shot') != 'S01' or record.get('script_sha256') != manifest['script_sha256']
            or record.get('direction_sha256') != manifest['direction_sha256']
            or record.get('first_frame_sha256') != base['source']['first_frame']['sha256']
            or _sha(video.read_bytes()) != record.get('video_sha256')
            or record.get('video_sha256') != attempt.get('video_sha256')
            or (record.get('latest_response') is not None and record['latest_response'].get('status') != 'succeeded')
            or Path(attempt.get('review_path', '')).resolve() != review_path
            or review.get('decision') != 'failed' or review.get('delivery_preview')
            or review.get('source_sha256') != record['video_sha256']
            or review.get('script_sha256') != manifest['script_sha256']):
        raise ValueError('Grounding failure must be the exact recorded, downloaded original and immutable review')
    original_review, history_review = _ledger_bound_review(previous_folder, attempt, review_path, review)
    checks = review.get('checks', {})
    observations = review.get('observations', [])
    if (set(checks) != set(REVIEW_CHECKS) or not any(value is False for value in checks.values())
            or any(value is not None and type(value) is not bool for value in checks.values())
            or not isinstance(observations, list)
            or {item.get('check') for item in observations} != {key for key, value in checks.items() if value is not None}):
        raise ValueError('Actual failed review needs observations for its inspected checks only')
    packet_path = _inside(record['review_packet'], previous_folder)
    packet = _read(packet_path)
    if (packet.get('source_sha256') != record['video_sha256']
            or not isinstance(packet.get('evidence'), list) or not packet['evidence']):
        raise ValueError('Failure packet belongs to another source video')
    evidence = []
    for item in packet['evidence']:
        path = _inside(packet_path.parent / item['file'], packet_path.parent)
        identity = _identity(path)
        if identity['sha256'] != item['sha256']:
            raise ValueError('Failure packet evidence changed')
        evidence.append(identity)
    observed_evidence = []
    for observation in observations:
        t = observation.get('time_seconds')
        if (type(t) not in (int, float) or not 0 <= t <= record['actual_duration_seconds']
                or not str(observation.get('notes', '')).strip() or not observation.get('evidence')):
            raise ValueError('Failed observations require actual seconds, notes and local evidence')
        for name in observation['evidence']:
            observed_evidence.append(_identity(_inside(previous_folder / name, previous_folder)))
    frame_review = _read(base['source']['first_frame_review']['path'])
    script = _read(folder / 'locked_script.json')
    shot = script['shots'][0]
    source = {'run_dir': str(folder), 'script': base['source']['script'],
        'direction': base['source']['direction'], 'first_frame': base['source']['first_frame'],
        'first_frame_review': base['source']['first_frame_review'],
        'first_frame_binding_sha256': base['source']['first_frame_binding_sha256'],
        'first_frame_original_proof_sha256': base['source']['original_ark_image_proof_sha256'],
        'campaign': {'path': str(campaign_path), 'series_id': series_id},
        'frozen_shot': {key: shot[key] for key in ('shot_id', 'participants', 'start_frame', 'action',
            'emotion_and_performance', 'audio', 'dialogue', 'end_frame')},
        'frozen_characters': [{key: character[key] for key in ('name', 'appearance', 'wardrobe') if key in character}
                              for character in script['characters']],
        'model_guide': {**_identity(GUIDE_PATH), 'instruction': GUIDE_INSTRUCTION},
        'frame_review_text': {key: frame_review[key] for key in ('shot_id', 'camera_id', 'checks', 'notes')},
        'failure': {'run_dir': str(previous_folder), 'attempt_id': attempt['id'],
            'record': _identity(record_path), 'video': _identity(video),
            'review': _identity(review_path), 'ledger_bound_review': original_review,
            'review_history': history_review, 'packet': _identity(packet_path),
            'packet_evidence': evidence, 'observation_evidence': observed_evidence,
            'review_text': review}, 'model_input_scope': 'text_only; no_image_video_or_audio_uploaded'}
    if focus is not None:
        source['focus'] = {'schema': FOCUS_SCHEMA, 'name': focus, 'guidance': TERMINAL_GUIDANCE}
        source['previous_actual_execution'] = _recorded_execution(previous_folder, record, attempt, config, source)
    if previous_grounding_run is not None:
        source['parent_revision'] = _parent_revision(folder, source, previous_grounding_run, feedback_file)
    return source


def _verify_identity_tree(value, allowed_root, *, verified=None):
    """Verify saved historical bytes without applying today's latest-failure gate."""
    verified = set() if verified is None else verified
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            path = Path(value['path']).resolve()
            if not path.is_relative_to(allowed_root) and path != GUIDE_PATH.resolve():
                raise ValueError('Historical grounding source path is outside its campaign or saved model guide')
            key = (str(path), value['sha256'])
            if key not in verified:
                if _sha(path.read_bytes()) != value['sha256']:
                    raise ValueError('Historical execution source bytes changed')
                verified.add(key)
        for child in value.values():
            _verify_identity_tree(child, allowed_root, verified=verified)
    elif isinstance(value, list):
        for child in value:
            _verify_identity_tree(child, allowed_root, verified=verified)


def _recorded_execution(folder, record, attempt, config, current_source):
    """Replay the exact plan actually submitted, without approving its failed media."""
    from .compact_execution import (_build, render_compact_prompt, GROUNDED_PROFILE,
        GROUNDED_PLAN_SCHEMA, REVIEW_SCHEMA, REVIEW_CHECKS as TEXT_CHECKS)
    from .seedance_client import SeedanceClient
    from .seedance_frames import reviewed_frame_reference
    proof = record.get('execution_prompt', {})
    if (proof.get('schema') != 'compact_execution_binding/v1' or proof.get('profile') != GROUNDED_PROFILE
            or record.get('prompt_sha256') != attempt.get('prompt_sha256')
            or record.get('script_sha256') != attempt.get('script_sha256')
            or _sha(record.get('prompt', '').encode('utf-8')) != record.get('prompt_sha256')):
        raise ValueError('Terminal attention needs the exact previously submitted grounded execution')
    plan_path, review_path = (_inside(proof.get(key, ''), folder) for key in ('plan_path', 'review_path'))
    if _identity(plan_path)['sha256'] != proof.get('plan_sha256') or _identity(review_path)['sha256'] != proof.get('review_sha256'):
        raise ValueError('Previously executed plan or independent text review bytes changed')
    plan, review = _read(plan_path), _read(review_path)
    grounding_proof = plan.get('grounding')
    if not isinstance(grounding_proof, dict) or grounding_proof != proof.get('grounding'):
        raise ValueError('Recorded execution does not bind its original grounding proof')
    ground_path = _inside(grounding_proof.get('plan_path', ''), folder)
    if _identity(ground_path)['sha256'] != grounding_proof.get('plan_sha256'):
        raise ValueError('Previously executed grounding candidate bytes changed')
    ground = _read(ground_path)
    if grounding_proof.get('focus') != ground.get('source', {}).get('focus'):
        raise ValueError('Recorded grounding focus differs from its actual model source')
    campaign_root = Path(current_source['campaign']['path']).parent
    _verify_identity_tree(grounding_proof, campaign_root)
    _verify_identity_tree(ground, campaign_root)
    source_path = ground_path.parent / 'source.json'
    run = _read(ground_path.parent / 'run.json')
    if (ground.get('schema') != SCHEMA or ground.get('model') != MODEL or ground.get('model_calls') != 1
            or _read(source_path) != ground.get('source')
            or _sha(source_path.read_bytes()) != grounding_proof.get('source_sha256')
            or run.get('source_sha256') != grounding_proof.get('source_sha256')
            or run.get('candidate_sha256') != grounding_proof['plan_sha256']
            or run.get('status') != 'candidate_pending_independent_review' or run.get('model_calls') != 1
            or _read(ground['request']['path']) != build_messages(ground['source'])
            or any(run.get(key + '_sha256') != ground[field]['sha256'] for key, field in (
                ('request', 'request'), ('output', 'model_output'), ('metadata', 'response_metadata')))):
        raise ValueError('Historical grounding model trace does not reproduce its actual submitted candidate')
    value = validate_grounding_value(parse_unique_json(_read(ground['model_output']['path'])), ground['source'])
    if value != {key: ground[key] for key in OUTPUT_KEYS} or value != plan.get('grounding_text'):
        raise ValueError('Previously executed bindings are not the original model output')
    prior_image = _inside(record['first_frame'], folder)
    base = _build(folder, prior_image, config)  # Current script/image proof, no live grounding recursion.
    script = _read(folder / 'locked_script.json')
    shot = script['shots'][0]
    if (ground['source']['frozen_shot'] != {key: shot[key] for key in ground['source']['frozen_shot']}
            or base['source']['script_sha256'] != current_source['script']['sha256']
            or base['source']['direction_sha256'] != current_source['direction']['sha256']
            or base['source']['first_frame']['sha256'] != current_source['first_frame']['sha256']):
        raise ValueError('Previously executed grounding belongs to another script, direction or opening image')
    prompt, recipe = render_compact_prompt(shot, script['aspect_ratio'], value,
                                         focus=grounding_proof.get('focus', {}).get('name'))
    expected_plan = {**base, 'schema': GROUNDED_PLAN_SCHEMA, 'profile': GROUNDED_PROFILE,
        'prompt': prompt, 'prompt_sha256': _sha(prompt.encode('utf-8')), 'render_recipe': recipe,
        'grounding': grounding_proof, 'grounding_text': value, 'created_at': plan.get('created_at')}
    if expected_plan != plan or prompt != record['prompt']:
        raise ValueError('Previously submitted execution cannot be reproduced from unchanged source fields')
    required = {'plan_path': str(plan_path), 'plan_sha256': _identity(plan_path)['sha256'],
        'prompt_sha256': plan['prompt_sha256'], 'script_sha256': plan['source']['script_sha256'],
        'direction_sha256': plan['source']['direction_sha256'],
        'first_frame_sha256': plan['source']['first_frame']['sha256']}
    if (review.get('schema') != REVIEW_SCHEMA or review.get('decision') != 'passed'
            or any(review.get(key) != val for key, val in required.items())
            or set(review.get('checks', {})) != TEXT_CHECKS or any(v is not True for v in review['checks'].values())
            or not isinstance(review.get('notes'), str) or not review['notes'].strip()
            or datetime.fromisoformat(review.get('reviewed_at', '')).utcoffset() is None):
        raise ValueError('Previously executed prompt has no exact-bound complete independent text review')
    expected_proof = {'schema': 'compact_execution_binding/v1', 'profile': GROUNDED_PROFILE,
        **required, 'review_path': str(review_path), 'review_sha256': _identity(review_path)['sha256'],
        'original_prompt_sha256': plan['original_prompt_sha256'],
        'first_frame_review': plan['source']['first_frame_review'],
        'original_ark_image_proof_sha256': plan['source']['original_ark_image_proof_sha256'],
        'subtitle_source': plan['subtitle_source'], 'scope': 'execution_text_projection_only; no_media_approval',
        'grounding': grounding_proof}
    if proof != expected_proof:
        raise ValueError('Submitted execution proof changed')
    manifest = _read(folder / 'production.json')
    direction = _read(folder / 'direction_plan.json')
    reference, _ = reviewed_frame_reference(folder, 'S01', prior_image, manifest, direction, config=config)
    with SeedanceClient(config) as client:
        request = client.build_task_payload(prompt, duration=int(shot['end_seconds'] - shot['start_seconds']),
            ratio='adaptive', resolution='480p', generate_audio=True, references=[reference],
            task_type='first_frame', return_last_frame=True)
    if request != record.get('request'):
        raise ValueError('Previous actual request differs from its reviewed prompt, image or generation settings')
    return {'schema': 'previous_actual_execution/v1', 'record': _identity(folder / 'S01.json'),
        'plan': _identity(plan_path), 'review': _identity(review_path),
        'profile': GROUNDED_PROFILE, 'prompt': prompt, 'prompt_sha256': record['prompt_sha256'],
        'request_sha256': _sha(_bytes(request)), 'grounding': grounding_proof,
        'visual_bindings': value['visual_bindings'], 'media_status': 'failed',
        'scope': 'historical_execution_text_and_source_proof_only; no_new_media_approval'}


def _parent_revision(folder, source, previous_dir, feedback_path, *, depth=0):
    if depth > 8:
        raise ValueError('Grounding revision ancestry is cyclic or too deep')
    previous = _inside(previous_dir, folder)
    feedback = _inside(feedback_path, previous)
    if previous == folder or not feedback.is_file():
        raise ValueError('Use the actual prior grounding directory and its independent feedback')
    paths = {key: previous / name for key, name in (
        ('run', 'run.json'), ('source', 'source.json'), ('request', 'request.json'),
        ('model_output', 'model_output.json'), ('response_metadata', 'response_metadata.json'),
        ('rejection', 'independent_rejection.json'))}
    run, parent_source = _read(paths['run']), _read(paths['source'])
    if (run.get('schema') != RUN_SCHEMA or run.get('model') != MODEL or run.get('model_calls') != 1
            or run.get('status') not in {'failed_model_output', 'candidate_pending_independent_review'}):
        raise ValueError('Only a known completed grounding output can be independently rejected and revised; unknown is not retryable')
    identities = {key: _identity(path) for key, path in paths.items()}
    if any(run.get(key + '_sha256') != identities[field]['sha256'] for key, field in (
            ('source', 'source'), ('request', 'request'), ('output', 'model_output'), ('metadata', 'response_metadata'))):
        raise ValueError('The previous grounding source/request/response does not match its actual model run')
    start, finish = (datetime.fromisoformat(run[key]) for key in ('started_at', 'finished_at'))
    if start.utcoffset() is None or finish.utcoffset() is None or finish < start:
        raise ValueError('Previous grounding has no valid completed timestamps')
    parent_base = {key: value for key, value in parent_source.items() if key != 'parent_revision'}
    if parent_base != source:
        raise ValueError('Grounding revisions must retain the same frozen source, reviewed image and failed video')
    if 'parent_revision' in parent_source:
        ancestor = parent_source['parent_revision']
        expected = _parent_revision(folder, parent_base, ancestor['run_dir'], ancestor['feedback']['path'], depth=depth + 1)
        if ancestor != expected:
            raise ValueError('Previous grounding revision ancestry changed')
    if _read(paths['request']) != build_messages(parent_source):
        raise ValueError('Previous grounding request does not reproduce from its bound source')
    reservation = _inside(run['reservation_path'], Path(source['campaign']['path']).parent / 'execution_grounding_reservations')
    if _read(reservation) != {'schema': RUN_SCHEMA, 'output_dir': str(previous),
            'request_sha256': run['request_sha256'], 'source_sha256': run['source_sha256'],
            'model': MODEL, 'model_calls': 1}:
        raise ValueError('Previous grounding actual single-call reservation changed')
    if run['status'] == 'candidate_pending_independent_review' and (
            _identity(previous / 'grounding_plan.json')['sha256'] != run.get('candidate_sha256')):
        raise ValueError('Previous grounding candidate bytes changed')
    rejection = _read(paths['rejection'])
    if (rejection.get('schema') != 'execution_grounding_rejection/v1' or rejection.get('decision') != 'failed'
            or rejection.get('model_output_sha256') != run['output_sha256']
            or rejection.get('request_sha256') != run['request_sha256']
            or not isinstance(rejection.get('notes'), str) or not rejection['notes'].strip()
            or ('run_sha256' in rejection and rejection['run_sha256'] != identities['run']['sha256'])):
        raise ValueError('Previous output requires an exact-bound independent failed rejection')
    if datetime.fromisoformat(rejection.get('reviewed_at', '')).utcoffset() is None:
        raise ValueError('Independent rejection needs an actual timezone-aware review time')
    feedback_raw = feedback.read_bytes()
    feedback_text = feedback_raw.decode('utf-8')
    if not feedback_text.strip():
        raise ValueError('Independent revision feedback is empty')
    return {'run_dir': str(previous), **identities,
        'feedback': {'path': str(feedback), 'sha256': _sha(feedback_raw)},
        'feedback_text': feedback_text, 'prior_request': _read(paths['request']),
        'prior_model_output': _read(paths['model_output']), 'rejection_text': rejection,
        'revision_guidance': TERMINAL_GUIDANCE if source.get('focus') else REVISION_GUIDANCE}


def build_messages(source):
    import json
    # Receipts, signed URLs, image/audio data and model credentials are not sent.
    value = {'frozen_shot': source['frozen_shot'], 'frozen_characters': source['frozen_characters'],
        'reviewed_first_frame_text': source['frame_review_text'], 'model_guide': source['model_guide'],
        'actual_failed_video_review_text': source['failure']['review_text'],
        'source_sha256': {key: source[key]['sha256'] for key in ('script', 'direction', 'first_frame')},
        'model_input_scope': source['model_input_scope']}
    if 'parent_revision' in source:
        parent = source['parent_revision']
        value['previous_grounding_revision'] = {key: parent[key] for key in (
            'prior_request', 'prior_model_output', 'rejection_text', 'feedback_text', 'revision_guidance')}
        value['previous_grounding_revision']['source_artifact_sha256'] = {
            key: parent[key]['sha256'] for key in ('source', 'run', 'request', 'model_output',
                                                  'response_metadata', 'rejection', 'feedback')}
    if source.get('focus'):
        value['focus'] = source['focus']
        previous = source['previous_actual_execution']
        value['previous_actual_execution'] = {key: previous[key] for key in (
            'profile', 'prompt', 'prompt_sha256', 'visual_bindings', 'plan', 'review', 'record', 'scope')}
    return [{'role': 'system', 'content': TERMINAL_SYSTEM_PROMPT if source.get('focus') else SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps(value, ensure_ascii=False)}]


def require_grounding(run_dir, image, plan_path, config):
    plan_path = _inside(plan_path, run_dir)
    plan_raw = plan_path.read_bytes()
    plan = _read(plan_path)
    if (set(plan) != {'schema', 'run_dir', 'model', 'model_calls', 'source', 'visual_bindings',
                     'action_constraints', 'request', 'model_output', 'response_metadata', 'text_review', 'media_review'}
            or plan.get('schema') != SCHEMA or plan.get('run_dir') != str(Path(run_dir).resolve())
            or plan.get('model') != MODEL or plan.get('model_calls') != 1
            or plan.get('text_review') != 'pending' or plan.get('media_review') != 'pending'):
        raise ValueError('Grounding must be a real source-bound pending model candidate')
    parent = plan['source'].get('parent_revision')
    source = collect_grounding_source(run_dir, image, plan['source']['failure']['run_dir'], config,
        previous_grounding_run=parent['run_dir'] if parent else None,
        feedback_file=parent['feedback']['path'] if parent else None,
        focus=plan['source'].get('focus', {}).get('name'))
    value = validate_grounding_value({key: plan.get(key) for key in OUTPUT_KEYS}, source)
    if source != plan['source']:
        raise ValueError('Grounding source, frame review or failed-video evidence changed')
    source_path = plan_path.parent / 'source.json'
    if _read(source_path) != source or _sha(source_path.read_bytes()) != _sha(_bytes(source)):
        raise ValueError('Grounding original source snapshot changed')
    for key, name in (('request', 'request.json'), ('model_output', 'model_output.json'),
                      ('response_metadata', 'response_metadata.json')):
        expected_path = plan_path.parent / name
        if _identity(expected_path) != plan.get(key):
            raise ValueError('Grounding original model artifacts changed: ' + key)
    if _read(plan['request']['path']) != build_messages(source):
        raise ValueError('Grounding request does not reproduce from the actual frozen source and failure')
    original = parse_unique_json(_read(plan['model_output']['path']))
    if validate_grounding_value(original, source) != value:
        raise ValueError('Grounding text is not the exact original model output')
    run_path = plan_path.parent / 'run.json'
    run = _read(run_path)
    if (run.get('schema') != RUN_SCHEMA or run.get('model') != MODEL or run.get('model_calls') != 1
            or run.get('status') != 'candidate_pending_independent_review'
            or run.get('candidate_sha256') != _sha(plan_raw)
            or run.get('source_sha256') != _sha(_bytes(source))
            or run.get('request_sha256') != plan['request']['sha256']
            or run.get('output_sha256') != plan['model_output']['sha256']
            or run.get('metadata_sha256') != plan['response_metadata']['sha256']):
        raise ValueError('Grounding real model run does not bind this exact candidate')
    start, finish = (datetime.fromisoformat(run[key]) for key in ('started_at', 'finished_at'))
    if start.utcoffset() is None or finish.utcoffset() is None or finish < start:
        raise ValueError('Grounding run must retain actual timezone-aware timestamps')
    reservation = _inside(run['reservation_path'], Path(source['campaign']['path']).parent / 'execution_grounding_reservations')
    expected_reservation = {'schema': RUN_SCHEMA, 'output_dir': str(plan_path.parent),
        'request_sha256': run['request_sha256'], 'source_sha256': run['source_sha256'],
        'model': MODEL, 'model_calls': 1}
    if _read(reservation) != expected_reservation:
        raise ValueError('Grounding one-call reservation changed')
    if plan_path.read_bytes() != plan_raw:
        raise ValueError('Grounding plan changed during verification')
    proof = {'schema': 'execution_grounding_binding/v1', 'plan_path': str(plan_path),
        'plan_sha256': _sha(plan_raw), 'run': _identity(run_path),
        'request': plan['request'], 'model_output': plan['model_output'],
        'response_metadata': plan['response_metadata'], 'source_sha256': run['source_sha256'],
        'previous_failed_attempt_id': source['failure']['attempt_id'],
        'scope': 'model_text_grounding_only; independent_text_review_required; no_media_approval'}
    if source.get('focus'):
        proof['focus'] = source['focus']
    return value, proof
