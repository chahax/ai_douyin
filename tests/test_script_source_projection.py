"""Bounded network context must retain exact source meaning and full local audit."""
import copy
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.trend_intelligence.script_pair as module
from script_pair_fixture import FixtureClient, pair_payload, enrich_review_report
from test_pre_video_script import NOW
from test_script_pair import service_for
from src.trend_intelligence.pre_video_script import PreVideoScriptRequest, PreVideoScriptService


@pytest.fixture(autouse=True)
def source_projection_uses_isolated_output_root(monkeypatch):
    monkeypatch.setattr(PreVideoScriptService, '_resolve_output_dir',
                        staticmethod(lambda request: Path(request.output_dir).resolve()))


@pytest.mark.parametrize('selection', [('labor-0', 'labor-0'), 'labor-0', None, ('',), (' labor-0',)])
def test_reference_focus_rejects_malformed_or_duplicate_selection(selection):
    with pytest.raises(ValueError, match='script_reference_source_ids'):
        PreVideoScriptRequest(account_key='account01', recent_video_types=('mixed',),
                              script_reference_source_ids=selection)


def test_reference_focus_unknown_source_fails_before_api(tmp_path):
    client = FixtureClient()
    with pytest.raises(ValueError, match='不存在的来源ID'):
        service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path),
            script_reference_source_ids=('not-in-this-batch',)), now=NOW)
    assert not client.calls


def test_focused_author_retains_twenty_overviews_full_audit_and_review_reads_actual_citations(tmp_path):
    data = pair_payload()
    for kind in ('short', 'long'):
        data[kind]['reference_usage'][0]['evidence_ids'] = ['visual-3']
    client = FixtureClient([json.dumps(data, ensure_ascii=False)])
    result = service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
        recent_video_types=('mixed',), output_dir=str(tmp_path),
        script_reference_source_ids=('marriage-1', 'labor-0')), now=NOW)
    author = json.loads(client.calls[0][0][1]['content'])
    reviewed = json.loads(client.calls[1][0][1]['content'])['evidence']
    generation = result.short.script.generation
    trace = Path(generation['trace_dir'])
    complete = json.loads((trace/'source_evidence.full.json').read_text(encoding='utf-8'))
    assert len(complete) == len(author['source_overview']) == len(reviewed['source_overview']) == 20
    assert author['source_overview'] == reviewed['source_overview'] == module._source_overview(complete)
    assert all('evidence' not in overview and 'expression_analysis' not in overview for overview in author['source_overview'])
    selection = author['script_reference_selection']
    assert selection['requested_source_ids'] == ['marriage-1', 'labor-0']
    assert selection['full_source_evidence_sha256'] == hashlib.sha256(module._source_json(complete).encode('utf-8')).hexdigest()
    focused = [source for source in complete if source['source_id'] in selection['requested_source_ids']]
    assert author['source_evidence'] == module.project_source_evidence(focused)
    assert len(author['source_evidence']) == 2
    full = next(row for row in complete if row['source_id'] == 'labor-0')
    assert len(full['expression_analysis']['evidence']) == 5 and 'evidence_projection' not in full
    assert [row['source_id'] for row in reviewed['source_evidence']] == ['labor-0']
    records = reviewed['source_evidence'][0]['expression_analysis']['evidence']
    actual = next(row for row in records if row['id'] == 'visual-3')
    assert actual == next(row for row in full['expression_analysis']['evidence'] if row['id'] == 'visual-3')
    assert generation['reference_usage_validation']['references'][0]['source_evidence'] == [actual]
    assert generation['script_reference_selection'] == selection
    assert generation['author_request_summary']['detailed_source_count'] == 2
    assert generation['author_request_summary']['user_payload_sha256'] == hashlib.sha256(client.calls[0][0][1]['content'].encode('utf-8')).hexdigest()
    saved_scope = json.loads((trace/'reference_selection.json').read_text(encoding='utf-8'))
    assert saved_scope['selection'] == selection
    assert saved_scope['author_request'] == generation['author_request_summary']
    audit = json.loads(Path(result.short.audit_path).read_text(encoding='utf-8'))
    assert audit['selection']['cohort_video_count'] == 20
    assert author['expression_patterns'] == reviewed['expression_patterns'] == audit['expression_patterns']
    revision = json.loads(module._revision_messages(client.calls[0][0], data, '修订动作')[1]['content'])
    assert revision['source_overview'] == author['source_overview']
    assert revision['source_evidence'] == author['source_evidence']
    assert revision['script_reference_selection'] == selection


def test_focus_cannot_skip_unselected_source_media_gate(tmp_path):
    from src.trend_intelligence.media_evidence import SourceMediaGateError
    client = FixtureClient()
    service = service_for(client)
    service.repository.analyses[-1].media_evidence = {}
    with pytest.raises(SourceMediaGateError):
        service.generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path),
            script_reference_source_ids=('labor-0',)), now=NOW)
    assert not client.calls


def test_focused_semantic_rejection_stops_delivery_after_real_evidence_review(tmp_path):
    from test_script_pair import _semantic_failure
    class RejectingReviewer(FixtureClient):
        def chat_completion_tracked(self, messages, **kwargs):
            result = super().chat_completion_tracked(messages, **kwargs)
            if kwargs.get('caller') == 'pre_video_script_review':
                evidence = json.loads(messages[-1]['content'])['evidence']
                assert len(evidence['source_overview']) == 20
                assert [source['source_id'] for source in evidence['source_evidence']] == ['labor-0']
                item = evidence['source_evidence'][0]['expression_analysis']['evidence'][0]
                return json.dumps(enrich_review_report(
                    _semantic_failure('labor-0', item['id'], item['text']),
                    json.loads(messages[1]['content'])))
            return result
    client = RejectingReviewer()
    with pytest.raises(module.SourceSemanticReviewError, match='来源语义复核未通过'):
        service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path),
            script_reference_source_ids=('labor-0',)), now=NOW)
    assert [kwargs['caller'] for _, kwargs in client.calls] == ['pre_video_script_pair', 'pre_video_script_review']
    assert not list(tmp_path.glob('*.json'))
    assert len(list(tmp_path.glob('_runs/*/reference_selection.json'))) == 1


@pytest.mark.parametrize('defect', ['unselected_source', 'fake_evidence'])
def test_focus_still_validates_actual_reference_content_and_rejects_overview_as_evidence(defect):
    from script_pair_fixture import fixture_source_evidence
    from test_pre_video_script import _Profiles
    sources = fixture_source_evidence()
    sources.append({**copy.deepcopy(sources[0]), 'source_id': 'overview-only'})
    data = pair_payload()
    if defect == 'unselected_source':
        data['short']['reference_usage'][0]['source_id'] = 'overview-only'
    else:
        data['short']['reference_usage'][0]['evidence_ids'] = ['fabricated']
    with pytest.raises(ValueError, match='概览|实际音画证据'):
        module.parse_pair(json.dumps(data, ensure_ascii=False), profile=_Profiles().get('account01'),
            created_at=NOW.isoformat(), short_seconds=60, long_seconds=180,
            generation={'script_reference_selection': {'requested_source_ids': ['labor-0']}},
            source_evidence=sources)


def test_focused_projection_filters_before_budget_check_and_empty_selection_keeps_default(monkeypatch):
    sources = [long_source(f'source-{i}') for i in range(20)]
    monkeypatch.setattr(module, '_full_source_evidence', lambda cohort: copy.deepcopy(sources))
    from src.trend_intelligence import media_evidence
    monkeypatch.setattr(media_evidence, 'build_expression_patterns', lambda cohort: {'source_count': len(cohort)})
    profile = SimpleNamespace(domain_strategy_id='legal_services', service_scope=[], target_audiences=[], domain_config={})
    overlap = SimpleNamespace(focus='核对材料', traits=[])
    options = dict(short_seconds=45, long_seconds=180)
    default = module.build_messages(profile, sources, overlap, **options)
    assert default == module.build_messages(profile, sources, overlap, script_reference_source_ids=(), **options)
    assert 'source_overview' not in json.loads(default[1]['content'])
    monkeypatch.setattr(module, 'SOURCE_PROJECTION_TOTAL_MAX_CHARS', 6000)
    with pytest.raises(module.SourceSemanticReviewError, match='预算'):
        module.build_messages(profile, sources, overlap, **options)
    focused = json.loads(module.build_messages(profile, sources, overlap,
        script_reference_source_ids=('source-2',), **options)[1]['content'])
    assert focused['source_evidence'] == module.project_source_evidence([sources[2]])
    assert len(focused['source_overview']) == 20 and focused['expression_patterns']['source_count'] == 20


def long_source(source_id='source-long'):
    visual = [{'id': f'V{i:04}', 'channel': 'visual', 'start_seconds': i*2,
               'end_seconds': i*2, 'text': f'原始帧观察 {i}：人物将材料移到桌边。'} for i in range(900)]
    asr = [{'id': f'A{i:04}', 'channel': 'asr', 'start_seconds': i*4,
            'end_seconds': i*4+3, 'text': f'原始转写 {i}：如果条件不成立，就不能这样说。'} for i in range(450)]
    claim = lambda text, ids: {'text': text, 'evidence_ids': ids}
    return {'source_id': source_id, 'analysis_id': 'analysis-long', 'metric_kind': 'likes',
        'metric_value': 90000, 'content_summary': '测试候选摘要，不是已核实的剧情。',
        'expression_analysis': {'schema': 'video_expression_analysis/v1',
            'core_message': claim('候选核心保留条件', ['A0200']),
            'expression_modes': [{'mode': 'prop_demonstration', 'evidence_ids': ['V0400']}],
            'visual_expression': [claim('候选实物表达', ['V0400'])],
            'audio_expression': [claim('条件式表达', ['A0200'])],
            'conflict': {'status': 'not_observed'}, 'uncertainties': ['说话人未经确认'],
            'evidence': visual+asr},
        'media_evidence': {'duration_seconds': 1800, 'source_video_sha256': 'a'*64,
            'visual': {'sample_times_seconds': list(range(0, 1800, 2)),
                'total_sampled_frame_count': 900, 'analyzed_frame_count': 900,
                'coverage_start_seconds': 0, 'coverage_end_seconds': 1798}}}


def test_large_source_projection_retains_every_claim_and_exact_citations_with_asr_neighbors():
    original = long_source()
    snapshot = copy.deepcopy(original)
    result = module.project_source_evidence([original])[0]
    assert original == snapshot
    for key in ('core_message', 'expression_modes', 'visual_expression', 'audio_expression', 'conflict', 'uncertainties'):
        assert result['expression_analysis'][key] == original['expression_analysis'][key]
    records = result['expression_analysis']['evidence']
    assert {item['id'] for item in records} == {'V0400', 'A0199', 'A0200', 'A0201'}
    original_by_id = {item['id']: item for item in original['expression_analysis']['evidence']}
    assert all(item == original_by_id[item['id']] for item in records)
    disclosure = result['evidence_projection']
    assert disclosure['total_evidence_count'] == 1350
    assert disclosure['included_evidence_count'] == 4
    assert disclosure['omitted_evidence_count'] == 1346
    assert len(disclosure['full_source_sha256']) == 64
    assert disclosure['omitted_visual_sample_time_count'] == 900
    assert result['media_evidence']['visual']['analyzed_frame_count'] == 900
    assert 'sample_times_seconds' not in result['media_evidence']['visual']


def test_projection_keeps_all_twenty_sources_and_never_uses_only_high_likes():
    sources = [long_source(f'source-{i}') for i in range(20)]
    result = module.project_source_evidence(sources)
    assert [row['source_id'] for row in result] == [row['source_id'] for row in sources]
    assert all(row['evidence_projection']['included_evidence_count'] == 4 for row in result)
    assert len(json.dumps(result, ensure_ascii=False)) < 65000


def test_review_projection_adds_actual_script_citations_and_their_context():
    source = long_source()
    result = module.project_source_evidence([source], reference_usage=[{
        'source_id': source['source_id'], 'evidence_ids': ['V0600']}])[0]
    ids = {item['id'] for item in result['expression_analysis']['evidence']}
    assert {'V0600', 'A0299', 'A0300', 'A0301', 'V0400', 'A0200'}.issubset(ids)
    assert result['evidence_projection']['script_cited_evidence_ids'] == ['V0600']


def test_neighbor_context_does_not_jump_a_large_audio_gap():
    source = long_source()
    source['expression_analysis']['evidence'] = [item for item in source['expression_analysis']['evidence']
        if item['id'] in ('V0400', 'A0100', 'A0200', 'A0300')]
    result = module.project_source_evidence([source])[0]
    assert {item['id'] for item in result['expression_analysis']['evidence']} == {'V0400', 'A0200'}


@pytest.mark.parametrize('defect', ['claim_id', 'script_id', 'duplicate_id', 'fake_source', 'already_projected'])
def test_projection_rejects_invalid_or_incomplete_provenance(defect):
    source, refs = long_source(), []
    if defect == 'claim_id': source['expression_analysis']['core_message']['evidence_ids'] = ['invented-id']
    if defect == 'script_id': refs = [{'source_id': source['source_id'], 'evidence_ids': ['invented-id']}]
    if defect == 'duplicate_id': source['expression_analysis']['evidence'].append(source['expression_analysis']['evidence'][0])
    if defect == 'fake_source': refs = [{'source_id': 'not-a-source', 'evidence_ids': ['V0400']}]
    if defect == 'already_projected': source = module.project_source_evidence([source])[0]
    with pytest.raises(ValueError):
        module.project_source_evidence([source], reference_usage=refs)


@pytest.mark.parametrize('limit', ['records', 'per_source_chars', 'total_chars'])
def test_required_evidence_overflow_is_explicit_not_silent_truncation(monkeypatch, limit):
    field = {'records': 'SOURCE_PROJECTION_MAX_RECORDS',
             'per_source_chars': 'SOURCE_PROJECTION_MAX_CHARS',
             'total_chars': 'SOURCE_PROJECTION_TOTAL_MAX_CHARS'}[limit]
    monkeypatch.setattr(module, field, 1)
    source = long_source()
    snapshot = copy.deepcopy(source)
    with pytest.raises(module.SourceSemanticReviewError, match='预算'):
        module.project_source_evidence([source])
    assert source == snapshot


def test_writer_budget_failure_happens_before_any_model_request(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'SOURCE_PROJECTION_MAX_RECORDS', 1)
    client = FixtureClient()
    with pytest.raises(module.SourceSemanticReviewError, match='预算'):
        service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    assert client.calls == []


def test_full_audit_and_validation_survive_projection_and_reviewer_gets_real_extra_reference(tmp_path):
    data = pair_payload()
    # This real fixture record is outside the candidate claims; full-cohort
    # validation must still verify it, and the reviewer must receive its text.
    for kind in ('short', 'long'):
        data[kind]['reference_usage'][0]['evidence_ids'] = ['visual-3']
    client = FixtureClient([json.dumps(data, ensure_ascii=False)])
    result = service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
        recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    author = json.loads(client.calls[0][0][1]['content'])
    reviewed = json.loads(client.calls[1][0][1]['content'])['evidence']
    first_author = next(row for row in author['source_evidence'] if row['source_id'] == 'labor-0')
    first_review = next(row for row in reviewed['source_evidence'] if row['source_id'] == 'labor-0')
    assert 'visual-3' not in {item['id'] for item in first_author['expression_analysis']['evidence']}
    assert 'visual-3' in {item['id'] for item in first_review['expression_analysis']['evidence']}
    trace = Path(result.short.script.generation['trace_dir'])
    complete = json.loads((trace/'source_evidence.full.json').read_text(encoding='utf-8'))
    full = next(row for row in complete if row['source_id'] == 'labor-0')
    assert len(full['expression_analysis']['evidence']) == 5
    assert len(first_author['expression_analysis']['evidence']) == 2
    assert 'evidence_projection' not in full
    validated = result.short.script.generation['reference_usage_validation']['references'][0]
    assert validated['source_evidence'][0]['id'] == 'visual-3'
    assert validated['source_evidence'][0] == next(item for item in full['expression_analysis']['evidence'] if item['id'] == 'visual-3')


def bound_review_source(tmp_path):
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'local original source bytes')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    expression = long_source()['expression_analysis']
    artifact = tmp_path / 'qwen.json'
    artifact.write_text(json.dumps({'schema': 'local_qwen_frame_analysis/v2',
        'source_video_sha256': source_hash, 'semantic_status': 'model_candidate_unreviewed',
        'answer': {'expression_analysis': expression}}, ensure_ascii=False), encoding='utf-8')
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    review_path = tmp_path / 'semantic_review.json'
    review = {'schema': 'source_expression_semantic_review/v1',
        'artifact_path': str(artifact), 'artifact_sha256': artifact_hash,
        'source_video_sha256': source_hash, 'decision': 'passed_with_limits',
        'blocked_for_script_generation': False, 'reviewed_at': '2026-09-09T14:00:00+00:00',
        'limitations': ['只查看抽样帧，未连续看听原片'], 'nonblocking_notes': ['作者身份未核验'],
        'acoustic_review': {'status': 'not_reviewed'},
        'visual_scope': {'viewed_count': 12, 'manifest_total_count': 900, 'unviewed_count': 888},
        'viewed_frames': [{'large_unused_detail': 'x' * 1000}] * 900}
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding='utf-8')
    candidate = SimpleNamespace(
        observation=SimpleNamespace(item_id='source-long', title='原片', hashtags=['合同'],
            metric_kind='likes', metric_value=90000, collected_at='2026-09-09T12:00:00+08:00', published_at=None),
        analysis=SimpleNamespace(analysis_id='analysis-long', content_summary='原模型候选',
            media_access_mode='local_video', expression_analysis=expression,
            media_evidence={'schema': 'local_media_evidence/v1', 'source_video_path': str(source),
                'source_video_sha256': source_hash, 'visual': {'status': 'completed',
                    'artifact_path': str(artifact), 'artifact_sha256': artifact_hash}}))
    return candidate, artifact, source, review_path, review


def test_independent_review_is_exact_bound_readonly_bounded_and_preserved_in_projection(tmp_path):
    candidate, artifact, source, review_path, _ = bound_review_source(tmp_path)
    originals = {path: path.read_bytes() for path in (artifact, source, review_path)}
    expression = copy.deepcopy(candidate.analysis.expression_analysis)
    full = module._full_source_evidence([candidate])[0]
    review = full['independent_review']
    assert review['decision'] == 'passed_with_limits'
    assert review['reviewed_at'] == '2026-09-09T22:00:00+08:00'
    assert review['review_sha256'] == hashlib.sha256(originals[review_path]).hexdigest()
    assert review['acoustic_status'] == 'not_reviewed'
    assert review['limits'] == ['只查看抽样帧，未连续看听原片']
    assert review['notes'] == ['作者身份未核验']
    assert review['visual_scope']['viewed_count'] == 12
    assert len(json.dumps(review, ensure_ascii=False)) < 1500
    assert 'viewed_frames' not in review and 'artifact_path' not in review
    assert 'LLM审稿' in review['notice']
    assert module.project_source_evidence([full])[0]['independent_review'] == review
    assert candidate.analysis.expression_analysis == expression
    assert full['expression_analysis'] == expression
    assert all(path.read_bytes() == before for path, before in originals.items())
    assert json.loads(artifact.read_text(encoding='utf-8'))['semantic_status'] == 'model_candidate_unreviewed'


@pytest.mark.parametrize('defect', [
    'missing_review', 'review_schema', 'artifact_sha', 'source_sha', 'artifact_path',
    'failed', 'blocked', 'missing_blocked', 'naive_time', 'invalid_time',
    'changed_artifact', 'changed_source', 'stale_expression', 'visual_sha', 'qwen_schema',
    'qwen_source', 'malformed_review',
])
def test_independent_review_never_transfers_approval_to_unbound_or_invalid_source(tmp_path, defect):
    candidate, artifact, source, review_path, review = bound_review_source(tmp_path)
    if defect == 'missing_review': review_path.unlink()
    elif defect == 'review_schema': review['schema'] = 'unknown'
    elif defect == 'artifact_sha': review['artifact_sha256'] = 'b' * 64
    elif defect == 'source_sha': review['source_video_sha256'] = 'c' * 64
    elif defect == 'artifact_path': review['artifact_path'] = str(tmp_path / 'historical-qwen.json')
    elif defect == 'failed': review['decision'] = 'failed'
    elif defect == 'blocked': review['blocked_for_script_generation'] = True
    elif defect == 'missing_blocked': review.pop('blocked_for_script_generation')
    elif defect == 'naive_time': review['reviewed_at'] = '2026-09-09T22:00:00'
    elif defect == 'invalid_time': review['reviewed_at'] = 'not a timestamp'
    elif defect == 'changed_artifact': artifact.write_bytes(artifact.read_bytes() + b' ')
    elif defect == 'changed_source': source.write_bytes(b'different original bytes')
    elif defect == 'stale_expression': candidate.analysis.expression_analysis['core_message']['text'] = '新内容未经审核'
    elif defect == 'visual_sha': candidate.analysis.media_evidence['visual']['artifact_sha256'] = 'd' * 64
    elif defect in ('qwen_schema', 'qwen_source'):
        payload = json.loads(artifact.read_text(encoding='utf-8'))
        payload['schema' if defect == 'qwen_schema' else 'source_video_sha256'] = 'incorrect'
        artifact.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        review['artifact_sha256'] = candidate.analysis.media_evidence['visual']['artifact_sha256'] = digest
    if defect != 'missing_review':
        review_path.write_text('{broken' if defect == 'malformed_review' else json.dumps(review, ensure_ascii=False), encoding='utf-8')
    review = module._full_source_evidence([candidate])[0]['independent_review']
    assert review['decision'] == 'not_reviewed'
    assert review['reviewed_at'] is None and review['review_sha256'] is None


def test_independent_review_cannot_override_permanent_rejection_and_never_writes_registry(tmp_path, monkeypatch):
    candidate, _, _, _, _ = bound_review_source(tmp_path)
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'src/trend_intelligence/script_pair.py'))
    digest = candidate.analysis.media_evidence['visual']['artifact_sha256']
    marker = tmp_path / 'data/video_analysis/semantic_rejections' / f'{digest}.json'
    marker.parent.mkdir(parents=True)
    marker.write_text('{"decision":"failed"}', encoding='utf-8')
    before = marker.read_bytes()
    review = module._full_source_evidence([candidate])[0]['independent_review']
    assert review['decision'] == 'not_reviewed' and '永久拒绝' in review['reason']
    assert marker.read_bytes() == before
    assert list(marker.parent.iterdir()) == [marker]


def test_independent_review_discloses_summary_omissions_and_never_certifies_audio(tmp_path):
    candidate, _, _, review_path, review = bound_review_source(tmp_path)
    review['limitations'] = ['限制' * 300] * 20
    review['nonblocking_notes'] = [{'finding': '备注' * 300}] * 20
    review['acoustic_review']['status'] = 'passed'
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding='utf-8')
    result = module._full_source_evidence([candidate])[0]['independent_review']
    assert result['decision'] == 'passed_with_limits'
    assert result['summary_is_partial'] is True
    assert len(result['limits']) == 4 and len(result['notes']) == 2
    assert all(len(item) <= 221 for item in result['limits'] + result['notes'])
    assert result['acoustic_status'] == 'not_verified'


@pytest.mark.parametrize('acoustic,scope,expected_acoustic', [
    ('not_performed', '完整ASR及部分抽样帧，未连续听看', 'not_reviewed'),
    ('not_performed', None, 'not_reviewed'),
    (None, '完整ASR及部分抽样帧，未连续听看', 'not_verified'),
    (None, None, 'not_verified'),
    ({'status': 'not_performed'}, '文字形式的审核范围', 'not_reviewed'),
    ('passed', '文字形式的审核范围', 'not_verified'),
])
def test_bound_review_survives_optional_string_or_null_scope_and_acoustic_records(
        tmp_path, acoustic, scope, expected_acoustic):
    candidate, artifact, source, review_path, review = bound_review_source(tmp_path)
    # Historical real reviews store these optional fields as prose/status
    # strings; they do not weaken the required artifact/source/review binding.
    review['visual_scope'] = None
    review['review_scope'] = scope
    review['acoustic_review'] = acoustic
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding='utf-8')
    before = {path: path.read_bytes() for path in (artifact, source, review_path)}
    original_expression = copy.deepcopy(candidate.analysis.expression_analysis)

    full = module._full_source_evidence([candidate])[0]
    result = full['independent_review']
    assert result['decision'] == 'passed_with_limits'
    assert result['review_sha256'] == hashlib.sha256(before[review_path]).hexdigest()
    assert result['artifact_sha256'] == hashlib.sha256(before[artifact]).hexdigest()
    assert result['source_video_sha256'] == hashlib.sha256(before[source]).hexdigest()
    assert result['reviewed_at'] == '2026-09-09T22:00:00+08:00'
    assert result['acoustic_status'] == expected_acoustic
    assert result['limits'] == review['limitations']
    assert result['notes'] == review['nonblocking_notes']
    assert 'visual_scope' not in result  # Prose/None does not invent frame counts.
    assert 'LLM审稿' in result['notice']
    assert module.project_source_evidence([full])[0]['independent_review'] == result
    assert full['expression_analysis'] == candidate.analysis.expression_analysis == original_expression
    assert all(path.read_bytes() == content for path, content in before.items())
