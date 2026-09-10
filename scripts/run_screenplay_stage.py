"""Run one real project model stage; retain evidence and never generate media."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.revise_script_candidate import _source_input
from src.shared.config import settings
from src.shared.llm_client import LLMClient
from src.trend_intelligence.script_outline import build_outline_messages
from src.trend_intelligence.production_revision import (
    parse_unique_json, validate_production_revision_fields, apply_production_revision,
)

MAX_PRODUCTION_LINEAGE = 64


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_artifact(value):
    path = Path(value).resolve()
    path.relative_to(ROOT / 'data')
    raw = path.read_bytes()
    return path, raw, parse_unique_json(raw)


# Re-export the shared protocol for existing callers and tests.
from src.trend_intelligence.script_screenplay import verify_story_review


def read_related_story(value, kind, duration, *, workflow_sha, source_sha, sources):
    """Use only a completed candidate from this workflow; this is not story approval."""
    path, raw, data = read_artifact(value)
    run_path, run_raw, run = read_artifact(path.with_name('run.json'))
    if (not isinstance(run, dict) or run.get('schema') != 'script_screenplay_stage_run/v1'
            or (run.get('stage') != 'story' and not (
                run.get('stage') in ('state', 'state-revise') and run.get('pipeline') == 'drama_then_state/v1'
                and (run.get('frozen_drama_preserved') is True if run.get('stage') == 'state'
                     else run.get('non_state_fields_preserved') is True))) or run.get('kind') != kind
            or run.get('status') != 'candidate_pending_independent_review'
            or run.get('candidate_sha256') != sha(raw)
            or run.get('workflow_request_sha256') != workflow_sha
            or run.get('source_evidence_sha256') != source_sha):
        raise ValueError('关联稿须来自同一原工作流和来源批次、对应版本的已完成故事候选；不能沿用旧SHA或摄影产物')
    from src.trend_intelligence.script_screenplay import validate_screenplay
    validate_screenplay(data, kind, duration, sources)
    return data, {'path': str(path), 'sha256': sha(raw),
                  'run_path': str(run_path), 'run_sha256': sha(run_raw)}


def read_previous_production(value, kind, *, story, screenplay_identity, review_identity,
                             workflow_sha, source_sha, reference_source_ids,
                             expected_run_sha='', _lineage=()):
    """Reopen/replay exact production ancestors bound to the current story review."""
    from src.trend_intelligence.script_screenplay import compile_screenplay
    candidate = Path(value).resolve()
    if candidate in _lineage:
        raise ValueError('production revision lineage cycle detected')
    if len(_lineage) >= MAX_PRODUCTION_LINEAGE:
        raise ValueError('production revision lineage exceeds bounded depth')
    def load(value):
        path, raw, _ = read_artifact(value)
        return path, raw, parse_unique_json(raw)
    path, raw, production = load(value)
    run_path, run_raw, run = load(path.with_name('run.json'))
    if (path.name != 'production.json' or not isinstance(run, dict)
            or run.get('schema') != 'script_screenplay_stage_run/v1'
            or run.get('stage') not in ('production', 'production-revise') or run.get('kind') != kind
            or run.get('status') != 'candidate_pending_independent_review' or run.get('model_calls') != 1
            or run.get('production_sha256') != sha(raw)
            or run.get('workflow_request_sha256') != workflow_sha
            or run.get('source_evidence_sha256') != source_sha
            or (expected_run_sha and sha(run_raw) != expected_run_sha)
            or not isinstance(run.get('inputs'), dict)
            or run['inputs'].get('screenplay') != screenplay_identity
            or run['inputs'].get('story_review') != review_identity):
        raise ValueError('production must match its completed run and current story/review/source bindings')
    _, request_raw, request = load(path.with_name('request.json'))
    if run.get('request_sha256') != sha(request_raw) or not isinstance(request, list) or len(request) != 2:
        raise ValueError('production request bytes or shape changed')
    payload = parse_unique_json(request[1]['content'])
    scope = payload.get('planning_evidence_scope', {})
    if (not isinstance(scope, dict) or scope.get('reference_source_ids', []) != list(reference_source_ids)
            or payload.get('screenplay') != story):
        raise ValueError('production request differs from current reference selection or frozen story')
    _, model_raw, model = load(path.with_name('model_output.json'))
    if run.get('model_output_sha256') != sha(model_raw):
        raise ValueError('production model output bytes changed')
    if run['stage'] == 'production-revise':
        previous = run['inputs'].get('previous_production')
        if (not isinstance(previous, dict) or set(previous) != {'path', 'sha256', 'run_path', 'run_sha256'}
                or any(not isinstance(previous.get(k), str) or not previous[k] for k in previous)
                or any(len(previous[k]) != 64 or any(c not in '0123456789abcdef' for c in previous[k])
                       for k in ('sha256', 'run_sha256'))
                or run.get('production_revision_before_sha256') != previous['sha256']
                or run.get('production_revision_after_sha256') != sha(raw)
                or run.get('unchanged_production_fields_preserved') is not True):
            raise ValueError('production revision parent provenance is invalid')
        parent, identity = read_previous_production(previous['path'], kind, story=story,
            screenplay_identity=screenplay_identity, review_identity=review_identity,
            workflow_sha=workflow_sha, source_sha=source_sha, reference_source_ids=reference_source_ids,
            expected_run_sha=previous['run_sha256'], _lineage=(*_lineage, path))
        if identity != previous or payload.get('previous_production') != parent:
            raise ValueError('production revision parent bytes or request changed')
        _, revision_raw, revision = load(path.with_name('production_revision.json'))
        if (run.get('production_revision_output_sha256') != sha(revision_raw) or model != revision
                or payload.get('allowed_revision_fields') != run.get('allowed_revision_fields')):
            raise ValueError('production revision output or allowed-field request changed')
        replay = apply_production_revision(story, parent, revision, run.get('allowed_revision_fields'), kind)
        if replay != production:
            raise ValueError('production revision replay differs; unauthorized fields changed')
    elif model != production:
        raise ValueError('original production differs from actual model output')
    _, compiled_raw, compiled = load(path.with_name('compiled_version.json'))
    if run.get('candidate_sha256') != sha(compiled_raw) or compile_screenplay(story, production, kind) != compiled:
        raise ValueError('production compiled artifact differs from frozen-story compilation')
    return production, {'path': str(path), 'sha256': sha(raw),
                        'run_path': str(run_path), 'run_sha256': sha(run_raw)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workflow-request', required=True)
    p.add_argument('--editor-feedback-file', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--kind', choices=('short', 'long'), required=True)
    p.add_argument('--stage', choices=('story', 'production', 'production-revise'), default='story')
    p.add_argument('--reference-source-id', action='append', default=[])
    p.add_argument('--previous-screenplay', default='')
    p.add_argument('--companion-screenplay', default='')
    p.add_argument('--screenplay', default='')
    p.add_argument('--story-review', default='')
    p.add_argument('--previous-production', default='')
    p.add_argument('--revise-field', action='append', default=[])
    args = p.parse_args()
    output = Path(args.output_dir).resolve()
    output.relative_to(ROOT / 'data')
    output.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        raw = value if isinstance(value, bytes) else (value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)).encode('utf-8')
        (output/name).write_bytes(raw)
        return sha(raw)
    state = {'schema':'script_screenplay_stage_run/v1','stage':args.stage,'kind':args.kind,'status':'preflight',
             'started_at_bjt':now(),'workflow_request_path':str(Path(args.workflow_request).resolve()),
             'inputs':{},'model_calls':0,'media_generation':False}
    try:
        save('run.json',state)
        if ((args.stage == 'production-revise') != bool(args.previous_production)
                or (args.stage == 'production-revise') != bool(args.revise_field)):
            raise ValueError('production-revise requires previous-production and revise-field; other stages cannot use them')
        workflow_path, workflow_raw, workflow = read_artifact(args.workflow_request)
        workflow_path.relative_to(ROOT / 'data/pre_video_scripts/_runs')
        if workflow_path.name != 'request.json':
            raise ValueError('须使用原项目工作流request.json')
        state['workflow_request_sha256'] = save('workflow_request.original.json',workflow_raw)
        workflow, full_text = _source_input(workflow, workflow_path.with_name('source_evidence.full.json'))
        full_sources = json.loads(workflow[1]['content'])['source_evidence']
        if full_text is None:
            full_text = json.dumps(full_sources, ensure_ascii=False, indent=2)
        full_raw = full_text.encode('utf-8')
        state['source_evidence_sha256'] = save('source_evidence.full.json',full_raw)
        feedback = Path(args.editor_feedback_file).read_text(encoding='utf-8')
        state['feedback_sha256'] = save('feedback.md',feedback)
        evidence_messages = build_outline_messages(workflow, feedback, reference_source_ids=args.reference_source_id)
        evidence = json.loads(evidence_messages[1]['content'])
        evidence['kind'] = args.kind
        evidence['duration_seconds'] = evidence[f'{args.kind}_seconds']
        from src.trend_intelligence.script_screenplay import validate_screenplay, compile_screenplay
        if args.stage in ('production', 'production-revise'):
            if not args.screenplay or not args.story_review or args.previous_screenplay or args.companion_screenplay:
                raise ValueError('摄影展开须提供screenplay和story-review，不能混用previous/companion故事参数')
            story_path, story_raw, story = read_artifact(args.screenplay)
            review_path, review_raw, review = read_artifact(args.story_review)
            state['inputs'].update(screenplay={'path':str(story_path), 'sha256':sha(story_raw)},
                                   story_review={'path':str(review_path), 'sha256':sha(review_raw)})
            verify_story_review(story_raw, review, workflow_sha=sha(workflow_raw), source_sha=sha(full_raw))
            validate_screenplay(story, args.kind, evidence['duration_seconds'], full_sources,
                                reference_source_ids=args.reference_source_id)
            evidence['screenplay'] = story
            prompt_name = 'script_screenplay_production.md'
            if args.stage == 'production-revise':
                previous_production, identity = read_previous_production(args.previous_production, args.kind,
                    story=story, screenplay_identity=state['inputs']['screenplay'],
                    review_identity=state['inputs']['story_review'], workflow_sha=sha(workflow_raw),
                    source_sha=sha(full_raw), reference_source_ids=args.reference_source_id)
                fields = validate_production_revision_fields(previous_production, args.revise_field)
                state['inputs']['previous_production'] = identity
                state['allowed_revision_fields'] = list(fields)
                state['production_revision_before_sha256'] = identity['sha256']
                evidence['previous_production'] = previous_production
                evidence['allowed_revision_fields'] = list(fields)
                prompt_name = 'script_screenplay_production_revision.md'
        else:
            if args.screenplay or args.story_review:
                raise ValueError('故事阶段不能混用摄影输入')
            opposite = 'long' if args.kind == 'short' else 'short'
            for arg, key, kind in ((args.previous_screenplay, 'previous_screenplay', args.kind),
                                   (args.companion_screenplay, 'companion_screenplay', opposite)):
                if arg:
                    data, identity = read_related_story(arg, kind, evidence[f'{kind}_seconds'],
                        workflow_sha=sha(workflow_raw), source_sha=sha(full_raw), sources=full_sources)
                    evidence[key], state['inputs'][key] = data, identity
            prompt_name = 'script_screenplay.md'
        # Editing requirements are last and apply to the actual requested stage.
        evidence['current_editor_feedback'] = evidence.pop('current_editor_feedback')
        messages = [{'role':'system','content':(ROOT / 'src/trend_intelligence/prompts' / prompt_name).read_text(encoding='utf-8')},
                    {'role':'user','content':json.dumps(evidence,ensure_ascii=False)}]
        state['request_sha256'] = save('request.json',messages)
        state['prompt_sha256'] = sha(messages[0]['content'].encode('utf-8'))
        model = settings.SCRIPT_LLM_MODEL or settings.LLM_MODEL
        extra = None
        if settings.SCRIPT_LLM_THINKING:
            if model.lower() != 'minimax-m3' or settings.SCRIPT_LLM_THINKING not in ('adaptive','disabled'):
                raise ValueError('当前thinking只允许M3 disabled/adaptive')
            extra = {'thinking':{'type':settings.SCRIPT_LLM_THINKING},'reasoning_split':True}
        limit = settings.SCRIPT_LLM_MAX_TOKENS
        client=LLMClient(model=model,extra_body=extra,timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                         max_retries=0,max_tokens=limit,preserve_invalid_json=True)
        if client.provider_name == 'mock':
            raise ValueError('不允许模拟模型')
        state.update(model=model,thinking=settings.SCRIPT_LLM_THINKING,max_output_tokens=limit,
                     timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS,temperature=0.4,provider=client.provider_name)
        state.update(status='running',model_calls=1)
        save('run.json',state)
        raw=client.chat_completion_tracked(messages,caller=f'pre_video_screenplay_{args.stage}',
                                            temperature=0.4,json_mode=True,use_cache=False)
        save('response.json',getattr(client.provider,'last_response_metadata',{}))
        state['model_output_sha256']=save('model_output.json',raw or 'null')
        if not raw:
            raise RuntimeError('模型未返回可用内容；没有候选，不自动重试')
        result=parse_unique_json(raw)
        if args.stage == 'story':
            validate_screenplay(result,args.kind,evidence['duration_seconds'],full_sources,
                                reference_source_ids=args.reference_source_id)
            if args.companion_screenplay:
                companion=evidence['companion_screenplay']
                if (result['core_message'] != companion['core_message']
                        or [(c['name'],c['identity']) for c in result['characters']] != [(c['name'],c['identity']) for c in companion['characters']]):
                    raise ValueError('两版须保留相同核心、人物姓名和身份')
                if args.kind == 'long' and len(result['version']['shots']) < len(companion['version']['shots'])+3:
                    raise ValueError('长版须至少比短版多3镜')
            state['candidate_sha256']=save('screenplay.json',result)
        else:
            if args.stage == 'production-revise':
                state['production_revision_output_sha256'] = save('production_revision.json',result)
                result = apply_production_revision(story,previous_production,result,fields,args.kind)
            compiled=compile_screenplay(story,result,args.kind)
            state['production_sha256']=save('production.json',result)
            state['candidate_sha256']=save('compiled_version.json',compiled)
            if args.stage == 'production-revise':
                state['production_revision_after_sha256'] = state['production_sha256']
                state['unchanged_production_fields_preserved'] = True
        state['status']='candidate_pending_independent_review'
    except Exception as exc:
        state.update(status='failed' if state['model_calls'] else 'preflight_rejected',
                     error_type=type(exc).__name__,error=str(exc))
        raise
    finally:
        state['finished_at_bjt']=now()
        save('run.json',state)
    print(json.dumps(state,ensure_ascii=False))


if __name__ == '__main__':
    main()
