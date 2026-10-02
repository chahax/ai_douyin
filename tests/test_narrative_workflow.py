"""Narrative workflow regression tests using synthetic stories, never media or models."""
import copy
import json
from pathlib import Path

import pytest

from src.trend_intelligence import narrative_workflow as nw
from scripts import run_narrative_workflow as cli


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding='utf-8')
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return nw.identity(path)


def story_fixture():
    context = {'short_seconds': 45, 'long_seconds': 180,
        'source_evidence': [{'source_id': 'douyin:source', 'expression_analysis': {
            'evidence': [{'id': 'V1', 'channel': 'visual', 'text': 'Synthetic source observation'}]}}],
        'reference': {'source_id': 'local:reference', 'insights': [{'id': 'R1'}]},
        'brief': '原创事件和可见代价，禁止沿用合同对话模板。',
        'account_positioning': {'domain': 'legal_services'}, 'expression_patterns': {},
        'constraints': {'narration': False, 'native_audio': True,
            'style_reference_counts_toward_cohort': False,
            'video_generation_unit_is_not_edit_shot': True, 'no_automatic_media_submission': True}}
    outline = {'core': '被看见的实际行动比一句承诺更有力量',
        'characters': [{'id': 'C1', 'name': '小林', 'wants': '拿回物品', 'hidden_or_known': '尚未知道物品被移动', 'stakes': '无法开始当天工作'},
                       {'id': 'C2', 'name': '店主', 'wants': '尽快结束争执', 'hidden_or_known': '知道物品位置', 'stakes': '当面的信任'}],
        'reference_usage': [{'source_id': 'local:reference', 'evidence_ids': ['R1'],
                             'borrowed_mechanism': '合成测试：前后景反差', 'original_change': '原创物件归还冲突'}]}
    for kind, duration in [('short', 15), ('long', 60)]:
        outline[kind] = {'title': kind + '原创新故事', 'opening_question': '东西在哪里', 'payoff': '物品被交还',
            'aftertaste': '前后言行反差留下不信任', 'events': [
                {'event_id': f'E{i:02}', 'duration_seconds': duration, 'visible_action': f'原创可拍动作{i}',
                 'new_information': f'新事实{i}', 'consequence': f'选择造成代价{i}',
                 'character_emotion': '人物表现逐步改变', 'audience_effect': '预期观众想知道下一步；未经实测',
                 'mechanism': '动作先于口头解释'} for i in range(1, 4)]}
    script = {}
    for kind, duration in [('short', 15), ('long', 60)]:
        v = script[kind] = {'event_spine': copy.deepcopy(outline[kind]['events']),
            'scenes': [{'id': 'L1', 'location': '店铺柜台', 'time_context': '同一下午连续发生'}],
            'props': [{'id': 'P1', 'name': '唯一物品盒'}], 'shots': []}
        previous = {'characters': {'C1': '柜台外，面向店主', 'C2': '柜台内，面向小林'},
                    'props': {'P1': '柜台内，尚未移动'}}
        # An editorial one-second insert is valid; it is not a one-second API call.
        pieces = [('E01', duration - 1), ('E01', 1), ('E02', duration), ('E03', duration)]
        for index, (event, seconds) in enumerate(pieces, 1):
            after = copy.deepcopy(previous);after['props']['P1'] = f'第{index}镜动作完成后明确位置'
            v['shots'].append({'shot_id': f'S{index:02}', 'event_id': event, 'scene_id': 'L1',
                'duration_seconds': seconds, 'participants': ['C1', 'C2'], 'action': '执行本镜已声明物件变化',
                'result': '这一步实际完成', 'state_before': copy.deepcopy(previous), 'state_after': after,
                'dialogue': [] if seconds == 1 or index == 4 else [
                    {'speaker': 'C1', 'text': '东西在哪？', 'start': .2, 'end': 2,
                     'delivery': '发现东西不见后追问，短促但完整，重音在东西'}]})
            previous = after
    production = {kind: [{'shot_id': shot['shot_id'], 'camera': '物品盒特写，固定机位，揭示此前遮住的信息' if shot['shot_id'] == 'S02' else '双方可见的中景',
        'lighting': '窗侧自然光，柜台内较暗', 'performance': '遵循已审动作，表情从困惑变为警觉',
        'sound_design': '原生现场对白与柜台物品摩擦声，插入镜无对白', 'cut_reason': '向观众揭示新的物品状态',
        'continuity_mode': 'planned_cut_requires_adapter' if shot['shot_id'] == 'S02' else 'raw_tail_continuation',
        'execution_requirement': '先审核新的剪辑执行适配，禁止直接付费提交'} for shot in script[kind]['shots']]
        for kind in ('short', 'long')}
    return context, outline, script, production


def build_partial_script(folder, workflow, kind, script, context, parent_dir):
    build_run(folder, workflow, 'script', {kind: script[kind]}, context, parent_dir)
    run = nw.read(folder / 'run.json');run['kind'] = kind
    request = nw.read(folder / 'request.json')
    request[1]['content'] = json.dumps(cli.author_payload(context, 'script',
        nw.read(parent_dir / 'candidate.json'), requested_kind=kind), ensure_ascii=False)
    run['artifacts']['request.json'] = write(folder / 'request.json', request)
    write(folder / 'run.json', run)


@pytest.mark.parametrize('kind', ['short', 'long'])
def test_single_version_keeps_original_event_and_state_checks(kind):
    context, outline, script, _ = story_fixture()
    partial = {kind: script[kind]}
    nw.validate_candidate(partial, 'script', context, outline, kind=kind)
    partial[kind]['shots'][1]['state_before']['props']['P1'] = 'unexplained jump'
    with pytest.raises(ValueError, match='discontinuity'):
        nw.validate_candidate(partial, 'script', context, outline, kind=kind)


def test_assemble_model_versions_preserves_parent_and_rejects_forged_pair(tmp_path, monkeypatch):
    from types import SimpleNamespace
    context, outline, script, _ = story_fixture()
    workflow = tmp_path / 'workflow.json';write(workflow, {'test': 'bound workflow'})
    parent = tmp_path / 'outline';build_run(parent, workflow, 'outline', outline, context)
    short = tmp_path / 'short';long = tmp_path / 'long'
    build_partial_script(short, workflow, 'short', script, context, parent)
    build_partial_script(long, workflow, 'long', script, context, parent)
    monkeypatch.setattr(cli, 'verify_workflow', lambda path: ({}, context, {}))
    def new_output(path):
        path = Path(path);path.mkdir();return path
    monkeypatch.setattr(cli, 'new_output', new_output)
    pair = tmp_path / 'pair'
    run = cli.assemble_script(SimpleNamespace(workflow=workflow, short_run=short, long_run=long, output_dir=pair))
    assert run['model_calls'] == 0
    assert cli.read_candidate(pair, workflow, 'script', context) == script
    assert nw.read(pair / 'review.template.json')['decision'] == 'pending'
    changed = copy.deepcopy(script);changed['short']['shots'][0]['action'] = 'not written by either model'
    run['artifacts']['candidate.json'] = write(pair / 'candidate.json', changed);write(pair / 'run.json', run)
    with pytest.raises(ValueError, match='differs'):
        cli.read_candidate(pair, workflow, 'script', context)


def test_assemble_refuses_different_reviewed_outlines(tmp_path, monkeypatch):
    from types import SimpleNamespace
    context, outline, script, _ = story_fixture()
    workflow = tmp_path / 'workflow.json';write(workflow, {'test': 'bound workflow'})
    first = tmp_path / 'first';second = tmp_path / 'second'
    build_run(first, workflow, 'outline', outline, context)
    other = copy.deepcopy(outline);other['core'] = 'different approved core'
    build_run(second, workflow, 'outline', other, context)
    short = tmp_path / 'short';long = tmp_path / 'long'
    build_partial_script(short, workflow, 'short', script, context, first)
    build_partial_script(long, workflow, 'long', script, context, second)
    monkeypatch.setattr(cli, 'verify_workflow', lambda path: ({}, context, {}))
    with pytest.raises(ValueError, match='different approved outlines'):
        cli.assemble_script(SimpleNamespace(workflow=workflow, short_run=short, long_run=long, output_dir=tmp_path / 'pair'))


def passed_review(stage, candidate_path, workflow_path):
    review = nw.review_template(stage, candidate_path, workflow_path)
    review.update(decision='passed', reviewed_at_bjt='2026-09-12T20:00:00+08:00')
    for name, check in review['checks'].items():
        check.update(passed=True, evidence=['short: E01 / S01', 'long: E03 / S04'],
                     finding='合成测试的独立检查记录：' + name)
    return review


@pytest.mark.parametrize('tamper', [False, True])
@pytest.mark.parametrize('version', ['source_digest_v2', 'source_digest_v3', 'source_digest_v4', 'source_overview_v5'])
def test_projected_author_request_replays_with_frozen_parent_rules(tmp_path, tamper, version):
    context, outline, _, _ = story_fixture()
    workflow_path = tmp_path / 'workflow.json'
    write(workflow_path, {'synthetic': 'workflow'})
    folder = tmp_path / 'outline'
    build_run(folder, workflow_path, 'outline', outline, context)
    run = nw.read(folder / 'run.json')
    run['source_projection'] = version
    request = nw.read(folder / 'request.json')
    payload = cli.author_payload(context, 'outline', None, projection_version=version)
    if tamper:payload['source_evidence'][0]['source_id'] = 'swapped'
    request[1]['content'] = json.dumps(payload, ensure_ascii=False)
    run['artifacts']['request.json'] = write(folder / 'request.json', request)
    write(folder / 'run.json', run)
    if tamper:
        with pytest.raises(ValueError, match='replay'):
            cli.read_candidate(folder, workflow_path, 'outline', context)
    else:
        assert cli.read_candidate(folder, workflow_path, 'outline', context) == outline


def test_complete_pair_supports_silent_ending_and_short_information_insert():
    context, outline, script, production = story_fixture()
    assert nw.validate_candidate(outline, 'outline', context) == outline
    assert nw.validate_candidate(script, 'script', context, outline) == script
    assert script['short']['shots'][-1]['dialogue'] == []
    assert nw.validate_candidate(production, 'production', context, script) == production
    handoff = nw.media_handoff_report(production)
    assert handoff['status'] == 'blocked_until_reviewed_execution_adapter'
    assert handoff['automatic_submit'] is False
    assert handoff['planned_cut_shots'] == {'short': ['S02'], 'long': ['S02']}


@pytest.mark.parametrize('source,evidence', [('invented', ['R1']), ('local:reference', ['fake']),
                                           ('douyin:source', ['R1'])])
def test_fabricated_or_cross_source_reference_rejected(source, evidence):
    context, outline, _, _ = story_fixture()
    outline['reference_usage'][0].update(source_id=source, evidence_ids=evidence)
    with pytest.raises(ValueError, match='Unknown reference'):
        nw.validate_candidate(outline, 'outline', context)


def test_outline_cannot_change_target_runtime():
    context, outline, _, _ = story_fixture()
    outline['short']['events'][0]['duration_seconds'] += 1
    with pytest.raises(ValueError, match='duration total'):
        nw.validate_candidate(outline, 'outline', context)


@pytest.mark.parametrize('change', ['spine_action', 'spine_order', 'shot_order', 'event_duration', 'state_jump'])
def test_script_cannot_change_approved_event_or_continuity(change):
    context, outline, script, _ = story_fixture()
    v = script['short']
    if change == 'spine_action':v['event_spine'][0]['visible_action'] = '偷偷换回催签合同'
    elif change == 'spine_order':v['event_spine'].reverse()
    elif change == 'shot_order':
        v['shots'][0]['event_id'], v['shots'][2]['event_id'] = v['shots'][2]['event_id'], v['shots'][0]['event_id']
    elif change == 'event_duration':
        v['shots'][0]['duration_seconds'] -= 1;v['shots'][2]['duration_seconds'] += 1
    else:v['shots'][1]['state_before']['props']['P1'] = '没有发生拿取动作却已经在另一人手上'
    with pytest.raises(ValueError, match='spine|Event order|discontinuity'):
        nw.validate_candidate(script, 'script', context, outline)


@pytest.mark.parametrize('change', ['offscreen', 'overlap', 'out_of_bounds'])
def test_dialogue_must_have_visible_speaker_and_valid_timing(change):
    context, outline, script, _ = story_fixture()
    shot = script['short']['shots'][0]
    if change == 'offscreen':shot['participants'] = ['C2']
    elif change == 'out_of_bounds':shot['dialogue'][0]['end'] = 99
    else:shot['dialogue'].append(copy.deepcopy(shot['dialogue'][0]))
    with pytest.raises(ValueError, match='dialogue'):
        nw.validate_candidate(script, 'script', context, outline)


@pytest.mark.parametrize('change', ['reorder', 'omit', 'rewrite_story'])
def test_photography_cannot_drop_reorder_or_rewrite_story(change):
    context, _, script, production = story_fixture()
    if change == 'reorder':production['short'].reverse()
    elif change == 'omit':production['short'].pop()
    else:production['short'][0]['dialogue'] = '摄影阶段偷偷改台词'
    with pytest.raises(ValueError, match='Photography|fields'):
        nw.validate_candidate(production, 'production', context, script)


@pytest.mark.parametrize('change', ['pending', 'unchecked', 'missing_evidence', 'unresolved',
                                  'wrong_sha', 'changed_candidate', 'wrong_timezone'])
def test_review_does_not_pass_unchecked_or_stale_artifacts(tmp_path, change):
    candidate, workflow_path = tmp_path / 'candidate.json', tmp_path / 'workflow.json'
    write(candidate, {'synthetic': 'candidate'});write(workflow_path, {'synthetic': 'workflow'})
    review = passed_review('outline', candidate, workflow_path)
    nw.require_review(review, 'outline', candidate, workflow_path)
    if change == 'pending':review['decision'] = 'pending'
    elif change == 'unchecked':review['checks']['hook']['passed'] = None
    elif change == 'missing_evidence':review['checks']['hook']['evidence'] = []
    elif change == 'unresolved':review['unresolved'] = ['未确认声音']
    elif change == 'wrong_sha':review['candidate']['sha256'] = 'f' * 64
    elif change == 'changed_candidate':write(candidate, {'synthetic': 'changed'})
    else:review['reviewed_at_bjt'] = '2026-09-12T12:00:00+00:00'
    with pytest.raises(ValueError):nw.require_review(review, 'outline', candidate, workflow_path)


def build_run(folder, workflow_path, stage, candidate, context, parent_dir=None):
    parent = None
    run = {'schema': 'narrative_author_run/v1', 'stage': stage, 'model_calls': 1,
           'status': 'candidate_pending_independent_review', 'workflow': nw.identity(workflow_path), 'artifacts': {}}
    if parent_dir:
        parent = nw.read(parent_dir / 'candidate.json')
        review_path = parent_dir / 'completed_review.json'
        write(review_path, passed_review(nw.STAGES[nw.STAGES.index(stage) - 1], parent_dir / 'candidate.json', workflow_path))
        run['parent'] = {'run': nw.identity(parent_dir / 'run.json'), 'review': nw.identity(review_path)}
    prompt = Path(cli.ROOT / 'src/trend_intelligence/prompts/narrative_impact_workflow.md').read_text(encoding='utf-8')
    public_reference = {key: value for key, value in context['reference'].items() if key not in ('source', 'evidence_files')}
    payload = {**context, 'reference': public_reference, 'stage': stage, 'approved_parent': parent}
    request = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    artifacts = {'candidate.json': candidate, 'model_output.json': candidate,
                 'response.json': {'synthetic_test': True}, 'prompt.md': prompt, 'request.json': request}
    for name, value in artifacts.items():run['artifacts'][name] = write(folder / name, value)
    write(folder / 'run.json', run)
    return run


def test_saved_parent_chain_reopens_actual_reviewed_model_candidates(tmp_path):
    context, outline, script, production = story_fixture()
    workflow_path = tmp_path / 'workflow.json';write(workflow_path, {'test': 'workflow'})
    previous = None
    for stage, candidate in [('outline', outline), ('script', script), ('production', production)]:
        folder = tmp_path / stage
        build_run(folder, workflow_path, stage, candidate, context, previous)
        assert cli.read_candidate(folder, workflow_path, stage, context) == candidate
        previous = folder


@pytest.mark.parametrize('change', ['parent', 'context', 'stage', 'prompt'])
def test_recorded_request_must_match_actual_parent_context_stage_and_prompt(tmp_path, change):
    context, outline, script, _ = story_fixture()
    workflow_path = tmp_path / 'workflow.json';write(workflow_path, {'test': 'workflow'})
    outline_dir, script_dir = tmp_path / 'outline', tmp_path / 'script'
    build_run(outline_dir, workflow_path, 'outline', outline, context)
    run = build_run(script_dir, workflow_path, 'script', script, context, outline_dir)
    request_path = script_dir / 'request.json';request = nw.read(request_path)
    payload = json.loads(request[1]['content'])
    if change == 'parent':payload['approved_parent']['short']['events'][0]['visible_action'] = '来自另一个父稿'
    elif change == 'context':payload['brief'] = '来自另一个工作流的合同模板'
    elif change == 'stage':payload['stage'] = 'outline'
    else:request[0]['content'] = '与保存prompt不同的另一个系统提示词'
    request[1]['content'] = json.dumps(payload, ensure_ascii=False)
    # Simulate a validly hashed but accidentally mixed request; self hashes alone
    # cannot prove that this model was given the parent the run claims to use.
    run['artifacts']['request.json'] = write(request_path, request)
    write(script_dir / 'run.json', run)
    with pytest.raises(ValueError):cli.read_candidate(script_dir, workflow_path, 'script', context)


def test_directed_reference_cannot_shadow_a_cohort_source_identity():
    context, outline, _, _ = story_fixture()
    context['reference']['source_id'] = 'douyin:source'
    original = [{'role': 'system', 'content': 'Synthetic project prompt'},
                {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}]
    with pytest.raises(ValueError, match='cannot replace a cohort source'):
        cli.build_context(original, context['reference'], context['brief'])
    outline['reference_usage'][0]['source_id'] = 'douyin:source'
    with pytest.raises(ValueError):nw.validate_candidate(outline, 'outline', context)


@pytest.fixture
def prepared_workflow(tmp_path, monkeypatch):
    context, _, _, _ = story_fixture()
    source = write(tmp_path / 'synthetic-reference.mp4', 'Synthetic bytes: no video decoding in this test')
    evidence = write(tmp_path / 'observed-evidence.json', {'synthetic_observation': 'not an actual video review'})
    reference = {'schema': 'reference_impact_blueprint/v1', 'source': source,
        'source_id': 'local-reference:' + source['sha256'], 'duration_seconds': 104,
        'evidence_files': [evidence], 'review_status': 'reviewed_with_limits', 'limitations': ['Synthetic test only'],
        'insights': [{'id': 'R1', 'start': 0, 'end': 5,
            **{key: 'Synthetic test record' for key in ('observed', 'character_expression',
                'audience_effect_hypothesis', 'mechanism', 'transferable', 'do_not_copy', 'uncertainty')}}]}
    original = [{'role': 'system', 'content': 'Original project prompt'}, {'role': 'user', 'content': json.dumps({
        key: context[key] for key in ('source_evidence', 'expression_patterns', 'account_positioning')}, ensure_ascii=False)}]
    request_path = tmp_path / 'request.json';full_path = tmp_path / 'source_evidence.full.json'
    reference_path = tmp_path / 'reference.json';brief_path = tmp_path / 'brief.md'
    request_binding = write(request_path, original)
    full_binding = write(full_path, context['source_evidence'])
    reference_binding = write(reference_path, reference);brief_binding = write(brief_path, context['brief'])
    context['reference'] = reference
    context_path = tmp_path / 'context.json'
    workflow = {'schema': 'narrative_impact_workflow/v1', 'inputs': {
        'workflow_request': request_binding, 'full_sources': full_binding,
        'reference': reference_binding, 'brief': brief_binding}, 'context': write(context_path, context)}
    workflow_path = tmp_path / 'workflow.json';write(workflow_path, workflow)
    monkeypatch.setattr(cli, 'verify_workflow_sources', lambda _: {'source_count': 20, 'status': 'synthetic_gate'})
    return workflow_path, workflow, context_path, context


def test_prepared_context_is_reconstructed_from_bound_inputs(prepared_workflow):
    workflow_path, workflow, _, context = prepared_workflow
    actual_workflow, actual_context, _ = cli.verify_workflow(workflow_path)
    assert actual_workflow == workflow
    assert actual_context == context


@pytest.mark.parametrize('change', ['brief', 'account', 'patterns', 'duration', 'constraints'])
def test_context_cannot_drift_even_if_its_file_hash_is_updated(prepared_workflow, change):
    workflow_path, workflow, context_path, context = prepared_workflow
    if change == 'brief':context['brief'] = '来自另一任务的剧情要求'
    elif change == 'account':context['account_positioning']['domain'] = 'another-account'
    elif change == 'patterns':context['expression_patterns'] = {'invented_high_like_cause': True}
    elif change == 'duration':context['short_seconds'] = 50
    else:context['constraints']['narration'] = True
    workflow['context'] = write(context_path, context);write(workflow_path, workflow)
    with pytest.raises(ValueError, match='context changed'):cli.verify_workflow(workflow_path)


def test_delta_replay_rejects_rehashed_authored_text_change(tmp_path):
    context, outline, script, _ = story_fixture()
    wp = tmp_path / 'workflow.json';write(wp, {'test':'workflow'})
    od, sd = tmp_path/'outline', tmp_path/'script'
    build_run(od, wp, 'outline', outline, context)
    kind='short';v=script[kind]
    raw={kind:{'scenes':v['scenes'], 'props':v['props'], 'initial_state':v['shots'][0]['state_before'], 'shots':[]}}
    for shot in v['shots']:
        r={k:copy.deepcopy(val) for k,val in shot.items() if k not in ('state_before','state_after')}
        r['changes']=copy.deepcopy(shot['state_after']);raw[kind]['shots'].append(r)
    candidate=nw.expand_script_delta(raw,outline,kind)
    run=build_run(sd,wp,'script',candidate,context,od)
    run.update(kind=kind,script_format='delta_v1')
    request=nw.read(sd/'request.json');request[1]['content']=json.dumps(cli.author_payload(context,'script',outline,requested_kind=kind),ensure_ascii=False)
    run['artifacts']['request.json']=write(sd/'request.json',request)
    run['artifacts']['model_output.json']=write(sd/'model_output.json',raw)
    write(sd/'run.json',run)
    assert cli.read_candidate(sd,wp,'script',context)==candidate
    candidate[kind]['shots'][0]['action']='invented action'
    run['artifacts']['candidate.json']=write(sd/'candidate.json',candidate);write(sd/'run.json',run)
    with pytest.raises(ValueError,match='actual model output'):cli.read_candidate(sd,wp,'script',context)


def test_frozen_parent_projection_keeps_reviewed_story_without_source_reanalysis():
    context, outline, _, _=story_fixture()
    context['constraints']={'narration':False}
    payload=cli.author_payload(context,'script',outline,'repair','frozen_parent_v6','short')
    assert payload['approved_parent']==outline
    assert payload['source_evidence']==[]
    assert payload['requested_kind']=='short'
    assert payload['current_feedback']=='repair'
    assert 'reference' not in payload and 'expression_patterns' not in payload
    with pytest.raises(ValueError):cli.author_payload(context,'outline',None,projection_version='frozen_parent_v6')
