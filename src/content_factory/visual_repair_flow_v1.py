"""Version-bound content repair planning. Pure control plane; never submits media."""
from copy import deepcopy
import hashlib
import json


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


ROUTES = {
    'asset_identity': ('repair_asset', ('first_frame', 'video', 'delivery')),
    'asset_layout': ('repair_asset', ('first_frame', 'video', 'delivery')),
    'composition': ('compose_first_frame', ('first_frame', 'video', 'delivery')),
    'staging': ('repair_shot_mapping', ('first_frame', 'video', 'delivery')),
    'video_motion': ('generate_video', ('video', 'delivery')),
    'video_deformation': ('generate_video', ('video', 'delivery')),
    'audio': ('repair_audio', ('audio', 'delivery')),
    'subtitle': ('repair_subtitle', ('subtitle', 'delivery')),
    'baked_text': ('generate_video', ('video', 'delivery')),
}
STAGE_ORDER = {'repair_asset':0, 'repair_shot_mapping':1, 'compose_first_frame':2,
               'repair_audio':3, 'repair_audio_and_sync_video':3,
               'generate_video':4, 'repair_subtitle':5}


def validate(project):
    if project.get('schema') != 'visual_repair_v1':
        raise ValueError('unsupported schema')
    if type(project.get('revision')) is not int or project['revision'] < 0:
        raise ValueError('invalid revision')
    assets, shots = project['assets'], project['shots']
    if len({s['id'] for s in shots}) != len(shots):
        raise ValueError('duplicate shot')
    for key, asset in assets.items():
        if not asset.get('version') or asset.get('kind') not in ('person', 'place'):
            raise ValueError('invalid asset '+key)
    for shot in shots:
        if not shot.get('asset_versions'):
            raise ValueError('missing shot assets')
        for key, version in shot['asset_versions'].items():
            if key not in assets or version != assets[key]['version']:
                raise ValueError('stale asset binding')


def plan(project, review):
    validate(project)
    if review.get('target') != sha(project) or not review.get('reviewer'):
        raise ValueError('stale or unidentified review')
    issues = review.get('issues')
    if not isinstance(issues, list):
        raise ValueError('missing issue list')
    by_id = {s['id']: s for s in project['shots']}
    actions = []
    for issue in issues:
        kind, sid = issue['kind'], issue['shot']
        if kind not in ROUTES or sid not in by_id or not issue.get('evidence'):
            raise ValueError('unknown issue or missing evidence')
        stage, invalid = ROUTES[kind]
        affected = [sid]
        asset = issue.get('asset')
        if stage == 'repair_asset':
            if asset not in by_id[sid]['asset_versions']:
                raise ValueError('asset not used by reviewed shot')
            if project['assets'][asset]['kind'] != ('place' if kind == 'asset_layout' else 'person'):
                raise ValueError('asset issue kind mismatch')
            affected = [s['id'] for s in project['shots'] if asset in s['asset_versions']]
        if kind == 'audio' and issue.get('lip_sync') is not False:
            # Unknown or synchronized speech cannot promise that silent picture is reusable.
            invalid = (*invalid, 'video')
            stage = 'repair_audio_and_sync_video'
        for target in affected:
            actions.append(dict(shot=target, stage=stage, issue=kind, asset=asset,
                                invalidate=list(invalid), evidence=issue['evidence']))
    # Multiple defects are prerequisites, never competing "next step" suggestions.
    positions = {s['id']:i for i,s in enumerate(project['shots'])}
    actions.sort(key=lambda a:(STAGE_ORDER[a['stage']],positions[a['shot']],a['issue']))
    payload = dict(schema='visual_repair_plan_v1', target=sha(project),
                   revision=project['revision'], actions=actions,
                   disposition='repair' if actions else 'review_passed',
                   dispatch='blocked_manual_pause' if project.get('paused') else 'explicit_executor_required')
    return dict(payload, plan_sha256=sha(payload))


def apply(project, proposed):
    """Register required work and invalidate eligibility, retaining original artifacts."""
    validate(project)
    payload = {k:v for k,v in proposed.items() if k != 'plan_sha256'}
    if proposed.get('plan_sha256') != sha(payload) or proposed.get('target') != sha(project):
        raise ValueError('plan changed or stale project')
    if proposed.get('revision') != project['revision']:
        raise ValueError('revision mismatch')
    # Recompute allowed actions from evidence instead of trusting a mutable stage name.
    review_issues = []
    seen = set()
    for a in proposed['actions']:
        key = (a['issue'], a.get('asset'), a['shot'])
        if key in seen:
            continue
        seen.add(key)
        issue = dict(kind=a['issue'], shot=a['shot'], asset=a.get('asset'), evidence=a['evidence'])
        if a['issue']=='audio':
            issue['lip_sync'] = 'video' in a['invalidate']
        review_issues.append(issue)
    allowed = plan(project, dict(target=sha(project),reviewer='bound-plan-revalidation',issues=review_issues))
    def action_set(items):
        return {json.dumps(a,sort_keys=True,ensure_ascii=False) for a in items}
    if action_set(allowed['actions']) != action_set(proposed['actions']):
        raise ValueError('unauthorized repair route')
    result = deepcopy(project)
    for a in allowed['actions']:
        shot = next(s for s in result['shots'] if s['id']==a['shot'])
        shot.setdefault('required_work',[])
        if a['stage'] not in shot['required_work']:
            shot['required_work'].append(a['stage'])
        for field in a['invalidate']:
            if field in shot.get('artifacts',{}):
                shot['artifacts'][field]['eligible'] = False
        if a['stage']=='repair_asset':
            result['assets'][a['asset']]['status']='repair_required'
    result['revision'] += 1
    result.setdefault('audit',[]).append(dict(plan=proposed['plan_sha256'], previous=sha(project)))
    return result
