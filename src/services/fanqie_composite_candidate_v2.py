"""Pure evidence adapter for complete existing-media composite candidates.

Legacy inline scene inputs stay inline. They are never relabeled as an
authoritative screenplay or as verified chapter attribution. No business DB IO.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from .fanqie_h3_candidate_v1 import (CandidateBlocked, canonical, digest, read_ref,
                                    _required, _validate_pending_v1)

PROJECT = Path(__file__).resolve().parents[2]
HANDOFF = 'novel_promotion_local_candidate/v2'
PROVENANCE = 'fanqie_candidate_provenance/v2'
GENERATION = 'fanqie_composite_generation/v2'
CLOCK = dict(frames=2896, fps=24, width=736, height=1312, audio_rate=48000,
             audio_channels=2, audio_samples=5792000)


def require(ok, code):
    if not ok:raise CandidateBlocked(code)


def bind(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _media(ref):
    path = Path(ref['path'])
    path = path.resolve() if path.is_absolute() else (PROJECT / path).resolve()
    normalized = dict(path=str(path), sha256=ref['sha256'])
    read_ref(normalized, json_content=False)
    return normalized


def _same(a, b):
    return _media(a) == _media(b)


def _text(ref):
    return Path(read_ref(ref, json_content=False)).read_text(encoding='utf-8-sig')


def _frame_rows(ref):
    from src.content_factory.audio_gap_repair_v1 import _frame_rows as parse
    return parse(_text(ref))


def _assembly(result_ref):
    result = read_ref(result_ref); plan = read_ref(result['plan']); proof = read_ref(result['proof'])
    require(result.get('schema') == 'full_two_minutes_CPU_assembly/v1'
            and result.get('status') == 'assembled_complete_first_then_second'
            and result.get('clock') == plan.get('clock') == CLOCK
            and [r.get('id') for r in plan.get('sources', [])] == ['first', 'second']
            and proof.get('all_decoded_frame_hashes_and_PTS_match') is True
            and proof.get('packet_streamcopy') is True and proof.get('content_trimmed') is False
            and proof.get('fades_added') is False and result.get('originals_modified') is False
            and result.get('new_model_calls') == result.get('new_ASR_calls') == 0,
            'complete_existing_media_assembly_required')
    read_ref(result['file'], json_content=False)
    artifacts = result.get('artifacts')
    require(isinstance(artifacts, list) and artifacts and all(r in artifacts for r in
        (result['plan'], result['proof'], result['file'])), 'composite_assembly_artifacts_missing')
    for ref in artifacts:read_ref(ref, json_content=False)
    for ref in plan['code']:read_ref(ref, json_content=False)
    root = Path(result_ref['path']).parent
    source_rows = [_frame_rows(bind(root / (name + '_frames.txt'))) for name in ('first', 'second')]
    expected = []
    for part, rows in enumerate(source_rows):
        require(len(rows) == 1448 and all(Fraction(r['pts']) == Fraction(i, 24)
            and Fraction(r['duration']) == Fraction(1, 24) for i, r in enumerate(rows)), 'composite_source_frame_clock_changed')
        expected += [dict(row, pts=str(Fraction(part * 1448 + i, 24))) for i, row in enumerate(rows)]
    require(expected == _frame_rows(proof['final_frames']), 'composite_full_frame_pixels_or_PTS_changed')
    parts = [np.fromfile(read_ref(r['PCM'], json_content=False), dtype='<i2').reshape(-1, 2)
             for r in proof['input_audio_normalizations']]
    require([r['id'] for r in proof['input_audio_normalizations']] == ['first', 'second']
            and all(x.shape == (2896000, 2) for x in parts), 'composite_part_audio_clock_changed')
    expected_pcm = np.concatenate(parts)
    joined = np.fromfile(read_ref(proof['joined_PCM'], json_content=False), dtype='<i2').reshape(-1, 2)
    actual = np.fromfile(read_ref(proof['final_PCM'], json_content=False), dtype='<i2').reshape(-1, 2)
    require(np.array_equal(expected_pcm, joined) and actual.shape == (5792000, 2), 'composite_audio_order_or_clock_changed')
    for start, end in ((0, 5792000), (0, 2896000), (2896000, 5792000)):
        a = expected_pcm[start:end].astype(float).ravel(); b = actual[start:end].astype(float).ravel()
        rms = float(np.sqrt(np.mean((a - b) ** 2))); signal = float(np.sqrt(np.mean(a * a)))
        corr = float(np.corrcoef(a, b)[0, 1]) if np.std(a) and np.std(b) else (1. if np.array_equal(a, b) else 0.)
        require((signal <= 1 and rms <= 8) or (corr >= .98 and rms <= max(16, signal * .3)),
                'composite_final_AAC_content_changed')
    return result, plan, proof


def _scene(ref, shot_id):
    case = read_ref(ref)
    require(case.get('schema') == 'h3_continuity_input/v33' and len(case.get('shots', [])) == 1,
            'composite_real_scene_case_required')
    shot = case['shots'][0]
    require(shot.get('shot_id') == shot_id, 'composite_scene_id_mismatch')
    text = _text(shot['source']); scope = shot['source_scope']; spans = shot.get('source_spans')
    require(type(scope['start']) is int and type(scope['end']) is int
            and 0 <= scope['start'] < scope['end'] <= len(text) and spans
            and shot.get('audio') and shot.get('camera_beats'), 'composite_inline_scene_scope_required')
    for span in spans:
        require(type(span['start']) is int and type(span['end']) is int
                and scope['start'] <= span['start'] <= span['end'] <= scope['end']
                and text[span['start']:span['end']] == span['text']
                and hashlib.sha256(span['text'].encode()).hexdigest() == span['sha256'],
                'composite_inline_source_span_changed')
    return shot, text[scope['start']:scope['end']]


def _strings(value):
    if isinstance(value, str):yield value
    elif isinstance(value, dict):
        for child in value.values():yield from _strings(child)
    elif isinstance(value, list):
        for child in value:yield from _strings(child)


def _native(segment, book_id):
    native = read_ref(segment['native_result']); plan = read_ref(segment['native_plan'])
    request = read_ref(segment['native_request']); graph = read_ref(segment['native_graph'])
    history = read_ref(segment['native_history']); pid = native.get('prompt_id')
    require(native.get('technical_status') == 'technical_saved' and native.get('shot_id') == segment['shot_id']
            and pid == segment['native_id'] and request.get('prompt') == graph
            and digest(graph) == native.get('graph_sha256'), 'composite_native_identity_or_graph_changed')
    record = history.get(pid) or {}
    require(record.get('prompt', [None, None, None])[1:3] == [pid, graph]
            and record.get('status', {}).get('status_str') == 'success'
            and record.get('status', {}).get('completed') is True, 'composite_native_history_not_success')
    require(len(plan.get('shots', [])) == 1 and plan['shots'][0]['id'] == segment['shot_id']
            and plan['shots'][0]['graph_sha256'] == native['graph_sha256'], 'composite_native_plan_graph_mismatch')
    input_ref = plan.get('input') or plan.get('live_manifest')
    require(input_ref == segment['input_manifest'], 'composite_native_input_binding_changed')
    packet = read_ref(input_ref)
    require(packet.get('source_case') == segment['source_case']
            and isinstance(packet.get('compiled_prompt'), str)
            and packet['compiled_prompt'] in set(_strings(graph))
            and hashlib.sha256(packet['compiled_prompt'].encode()).hexdigest() == packet['compiled_prompt_utf8_sha256'],
            'composite_real_prompt_or_case_not_consumed')
    library = read_ref(packet['library_binding'])
    require(library.get('book_id') == book_id, 'composite_native_library_book_mismatch')
    require(set(native.get('files', {})) == {'video', 'audio', 'first', 'last'},
            'composite_native_four_artifacts_required')
    for ref in native['files'].values():_media(ref)
    require(_same(native['files']['video'], segment['model_media']), 'composite_native_video_changed')
    return native, plan, packet


def _derivative(segment):
    if segment.get('derivative_result') is None:
        require(_same(segment['selected_media'], segment['model_media']), 'composite_unexplained_media_replacement')
        return
    edited = read_ref(segment['derivative_result']); candidate = read_ref(edited['source_candidate'])
    result = read_ref(edited['processor_result']); proof = read_ref(edited['processor_proof'])
    processor_plan = read_ref(edited['processor_plan'])
    require(edited.get('schema') == 'media_repair_audio_result/v1' and edited.get('operation') == 'cleanup_gap'
            and edited.get('H3_generation_performed') is False
            and edited['source_case'] == segment['source_case']
            and edited['source_native_id'] == candidate['native_id'] == segment['native_id']
            and candidate['result'] == segment['native_result'] and _same(candidate['media'], segment['model_media'])
            and candidate['source_case'] == segment['source_case']
            and _same(edited['media'], segment['selected_media']) and result['file'] == edited['media']
            and result['plan'] == edited['processor_plan'] and result['proof'] == edited['processor_proof']
            and _same(proof['input'], segment['model_media']) and _same(proof['output'], segment['selected_media'])
            and proof.get('video_frames_PTS_and_decoded_hashes_unchanged') is True
            and proof.get('video_streamcopy') is True and proof.get('duration_or_story_cut_performed') is False
            and processor_plan.get('video_duration_or_frame_cut_allowed') is False,
            'composite_CPU_derivation_not_bound_to_native')
    require(_frame_rows(proof['source_framehash']) == _frame_rows(proof['output_framehash']),
            'composite_CPU_derivative_changed_video')
    for ref in result.get('artifacts', []):read_ref(ref, json_content=False)


def render_index(parts):
    lines = ['# Composite production input index', '',
        'This is a registration index of existing production inputs, not a new screenplay.',
        'Legacy chapter attribution is not established. Original source cases remain unchanged.', '']
    for part in parts:
        lines += ['## ' + part['part_id'] + ' / ' + part['script_mode'],
                  'Original media: ' + canonical(part['media']), '']
        if part['script_mode'] == 'authoritative_script':
            lines += ['Original screenplay reference: ' + canonical(part['script']),
                      'Original selection references: ' + canonical(part['script_selections']), '']
        for segment in part['segments']:
            shot, text = _scene(segment['source_case'], segment['shot_id'])
            lines += ['### ' + part['part_id'] + '/' + segment['shot_id'],
                      'SOURCE_CASE: ' + canonical(segment['source_case']),
                      'Verbatim production source: ' + canonical(shot['source']), '', text, '']
    return '\n'.join(lines)


def validate_candidate(handoff_ref, *, provenance_ref, technical_review_ref, account_binding):
    h, p, review = map(read_ref, (handoff_ref, provenance_ref, technical_review_ref))
    _required(account_binding, ('account_uuid', 'account_key', 'binding_version'))
    require(h.get('schema') == HANDOFF and p.get('schema') == PROVENANCE
            and h.get('account_key') == account_binding['account_key']
            and p.get('book_id') == h.get('book_id') and p.get('media') == h.get('media_binding')
            and p.get('book_manifest') == h.get('source_manifest')
            and p.get('assembly_result') == h.get('assembly_receipt_binding'), 'composite_candidate_subject_mismatch')
    book = read_ref(p['book_manifest']); generation = read_ref(h['source_generation_manifest'])
    require(str(book.get('book_id')) == h['book_id'] and book.get('book_name') == h['book_name']
            and generation.get('schema') == GENERATION and generation.get('kind') == 'existing_media_assembly'
            and generation.get('new_model_calls') == 0 and generation.get('parts') == p.get('parts'),
            'composite_book_or_generation_mismatch')
    result, plan, proof = _assembly(h['assembly_receipt_binding'])
    require(result['file'] == h['media_binding'] and result['proof'] == h['technical_proof_binding']
            and {canonical(x) for x in p['source_code']} == {canonical(x) for x in plan['code']},
            'composite_assembly_subject_or_code_changed')
    require(review.get('status') == 'technical_cache_review_passed' and review.get('file') == result['file']
            and review.get('result') == h['assembly_receipt_binding'] and review.get('proof') == result['proof']
            and all(review.get(k) is True for k in ('all_frame_pixels_and_PTS_cache_revalidated',
                'audio_PCM_and_AAC_metrics_cache_revalidated', 'original_sources_SHA_revalidated')),
            'same_composite_media_technical_review_required')
    parts = p.get('parts'); require(isinstance(parts, list) and [x['part_id'] for x in parts] == ['first', 'second'],
                                  'complete_ordered_two_parts_required')
    native_ids = []; all_cases = []
    for index, part in enumerate(parts):
        require(part['media'] == plan['sources'][index]['media']
                and part['original_result'] == plan['sources'][index]['original_result'], 'composite_part_order_or_media_changed')
        original = read_ref(part['original_result']); read_ref(part['media'], json_content=False)
        require(original['file'] == part['media'] and len(part.get('segments', [])) == 4
                and [s['shot_id'] for s in part['segments']] == ['S01', 'S02', 'S03', 'S04'],
                'complete_four_scene_part_required')
        require(part.get('frame_range') == [index * 1448, (index + 1) * 1448], 'composite_part_frame_range_changed')
        if index == 0:
            require(part['script_mode'] == 'source_case_inline_scene' and part.get('chapter_attribution') == 'not_established'
                    and original.get('schema') == 'h3_library_bound_minute_series/v2', 'legacy_inline_scene_mode_required')
            generation_plan = read_ref(part['generation_plan'])
            selected = original['segments']
            require([s['shot_id'] for s in selected] == ['S01', 'S02', 'S03', 'S04'], 'original_native_scene_order_changed')
            for row, segment in zip(selected, part['segments']):
                require(row['native_result'] == segment['native_result'] and row['file'] == segment['selected_media']
                        and row['prompt_id'] == segment['native_id'], 'selected_native_attempt_changed')
                source = next(s['source_case'] for s in generation_plan['sources'] if s['shot_id'] == segment['shot_id'])
                require(source['sha256'] == segment['source_case']['sha256'], 'legacy_selected_case_changed')
        else:
            prior = part['prior_candidate']
            frozen = _validate_pending_v1(prior['handoff'], provenance_ref=prior['provenance'],
                technical_review_ref=prior['technical_review'], account_binding=account_binding)
            prior_p = read_ref(prior['provenance'])
            require(part['script_mode'] == 'authoritative_script' and frozen['book_id'] == h['book_id']
                    and frozen['media'] == part['media'] and part['script'] == prior_p['script']
                    and part['script_selections'] == prior_p['script_selections'], 'rear_original_v1_provenance_changed')
            require({canonical(s['source_case']) for s in part['segments']} == {canonical(s) for s in prior_p['source_cases']},
                    'rear_original_source_cases_changed')
            original_plan = read_ref(original['plan'])
            for row, segment in zip(original_plan['inputs']['segments'], part['segments']):
                require(row['id'] == segment['shot_id'] and row['media'] == segment['selected_media']
                        and row['result'] == (segment.get('derivative_result') or segment['native_result']),
                        'rear_selected_native_or_derivative_changed')
        for pos, segment in enumerate(part['segments']):
            require(segment['frame_range'] == [index * 1448 + pos * 362, index * 1448 + (pos + 1) * 362],
                    'composite_scene_timeline_changed')
            shot, _ = _scene(segment['source_case'], segment['shot_id'])
            native, native_plan, packet = _native(segment, h['book_id']); _derivative(segment)
            if index == 0:
                require(native_plan.get('series_plan') == part['generation_plan']
                        and shot.get('authoritative_script') is None and shot.get('script_selection') is None,
                        'legacy_input_must_not_invent_authoritative_binding')
                library = read_ref(packet['library_binding']); cast = read_ref(library['cast_plan'])
                require(library.get('book_id') == h['book_id'], 'legacy_book_library_evidence_missing')
                for name in shot['character_names']:
                    card = read_ref(library['characters'][name]['feature_card'])
                    require(card.get('book_id') == h['book_id'] and card['source']['cast_plan'] == library['cast_plan'],
                            'legacy_book_asset_source_mismatch')
                    read_ref(card['source']['source_script'], json_content=False)
            else:
                require(shot.get('authoritative_script') == part['script']
                        and shot.get('script_selection') in part['script_selections'], 'rear_authoritative_script_changed')
            native_ids.append(native['prompt_id']); all_cases.append(segment['source_case'])
    require(len(set(native_ids)) == 8 and generation.get('source_cases') == all_cases,
            'eight_actual_native_scene_bindings_required')
    require(_text(p['script']) == render_index(parts) and p.get('script_mode') == 'composite_production_input_index',
            'composite_registration_index_not_verbatim')
    return dict(handoff=handoff_ref, provenance=provenance_ref, technical_review=technical_review_ref,
        account=account_binding, book_id=h['book_id'], book_name=h['book_name'], media=h['media_binding'])


def _native_refs(result_ref, source_case, selected_media, frame_range, derivative=None):
    native = read_ref(result_ref); root = Path(result_ref['path']).parents[2]
    plan_ref = bind(root / 'PLAN.json'); plan = read_ref(plan_ref)
    shot = native['shot_id']; directory = Path(result_ref['path']).parent
    packet = plan.get('input') or plan.get('live_manifest')
    return dict(shot_id=shot, native_id=native['prompt_id'], native_result=result_ref, native_plan=plan_ref,
        native_request=bind(directory / 'REQUEST.json'), native_graph=bind(directory / 'workflow_api.json'),
        native_history=bind(directory / 'HISTORY.json'), input_manifest=packet, source_case=source_case,
        model_media=_media(native['files']['video']), selected_media=selected_media,
        derivative_result=derivative, frame_range=frame_range)


def prepare_package(run, *, account_binding, rear_handoff, rear_provenance, rear_technical_review):
    """Freeze actual composite metadata only. Never register or touch business DBs."""
    run = Path(run).resolve(); require(run.is_relative_to(PROJECT / 'data'), 'project_composite_run_required')
    result_ref = bind(run / 'RESULT.json'); result, plan, proof = _assembly(result_ref)
    prior = dict(handoff=rear_handoff, provenance=rear_provenance, technical_review=rear_technical_review)
    prior_frozen = _validate_pending_v1(rear_handoff, provenance_ref=rear_provenance,
        technical_review_ref=rear_technical_review, account_binding=account_binding)
    old_p = read_ref(rear_provenance); book = read_ref(old_p['book_manifest'])
    parts = []; all_cases = []
    for index, row in enumerate(plan['sources']):
        original = read_ref(row['original_result'])
        part = dict(part_id=row['id'], media=row['media'], original_result=row['original_result'],
                    frame_range=[index * 1448, (index + 1) * 1448], segments=[])
        if index == 0:
            selected = original['segments']
            native_plan = read_ref(bind(Path(selected[0]['native_result']['path']).parents[2] / 'PLAN.json'))
            part.update(script_mode='source_case_inline_scene', chapter_attribution='not_established',
                        generation_plan=native_plan['series_plan'])
            for pos, selected_row in enumerate(selected):
                native_plan = read_ref(bind(Path(selected_row['native_result']['path']).parents[2] / 'PLAN.json'))
                source_case = read_ref(native_plan['input'])['source_case']
                part['segments'].append(_native_refs(selected_row['native_result'], source_case,
                    selected_row['file'], [pos * 362, (pos + 1) * 362]))
        else:
            require(row['media'] == prior_frozen['media'], 'selected_rear_candidate_media_mismatch')
            part.update(script_mode='authoritative_script', script=old_p['script'],
                        script_selections=old_p['script_selections'], prior_candidate=prior)
            selected = read_ref(original['plan'])['inputs']['segments']
            for pos, selected_row in enumerate(selected):
                record = read_ref(selected_row['result']); derivative = None
                if record.get('schema') == 'media_repair_audio_result/v1':
                    derivative = selected_row['result']; candidate = read_ref(record['source_candidate'])
                    native_ref, source_case = candidate['result'], record['source_case']
                else:
                    native_ref = selected_row['result']
                    native_plan = read_ref(bind(Path(native_ref['path']).parents[2] / 'PLAN.json'))
                    source_case = read_ref(native_plan.get('input') or native_plan['live_manifest'])['source_case']
                part['segments'].append(_native_refs(native_ref, source_case, selected_row['media'],
                    [1448 + pos * 362, 1448 + (pos + 1) * 362], derivative))
        parts.append(part); all_cases += [s['source_case'] for s in part['segments']]
    # Fail before creating metadata if any historical native/case edge is absent.
    for part in parts:
        for segment in part['segments']:
            _scene(segment['source_case'], segment['shot_id'])
            _native(segment, str(book['book_id']))
            _derivative(segment)
    directory = run / 'candidate_package_v2'; directory.mkdir(exist_ok=False)
    def freeze(name, value):
        path = directory / name
        with path.open('x', encoding='utf-8') as out:json.dump(value, out, ensure_ascii=False, indent=2)
        return bind(path)
    index = directory / 'COMPOSITE_PRODUCTION_INPUT_INDEX.md'; index.write_text(render_index(parts), encoding='utf-8')
    generation = freeze('GENERATION.json', dict(schema=GENERATION, kind='existing_media_assembly',
        parts=parts, source_cases=all_cases, new_model_calls=0, clock=CLOCK))
    provenance = freeze('PROVENANCE.json', dict(schema=PROVENANCE, book_id=str(book['book_id']),
        media=result['file'], script=bind(index), script_mode='composite_production_input_index',
        source_code=plan['code'], book_manifest=old_p['book_manifest'], assembly_result=result_ref, parts=parts))
    handoff = freeze('HANDOFF.json', dict(schema=HANDOFF, account_key=account_binding['account_key'],
        book_id=str(book['book_id']), book_name=book['book_name'], media_binding=result['file'],
        source_manifest=old_p['book_manifest'], source_generation_manifest=generation,
        technical_proof_binding=result['proof'], assembly_receipt_binding=result_ref,
        overall_video_quality_passed=False))
    review = freeze('TECHNICAL_REVIEW.json', dict(status='technical_cache_review_passed',
        file=result['file'], result=result_ref, proof=result['proof'],
        all_frame_pixels_and_PTS_cache_revalidated=True, audio_PCM_and_AAC_metrics_cache_revalidated=True,
        original_sources_SHA_revalidated=True, overall_video_quality_passed=False,
        new_model_calls=0, new_ASR_calls=0))
    frozen = validate_candidate(handoff, provenance_ref=provenance, technical_review_ref=review,
                                account_binding=account_binding)
    return dict(handoff=handoff, provenance=provenance, technical_review=review, script=bind(index),
                media=frozen['media'], registered=False, database_writes=False)
