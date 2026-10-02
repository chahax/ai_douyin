"""Read-only production evidence replay; never dispatches or approves content."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(run_dir):
    from src.content_factory.creative_state_plan_v6 import validate_state_plan, build_state_plan_schema
    from src.content_factory.creative_plan_patch import apply_plan_patch, build_patch_schema, timing_budget
    from jsonschema import Draft202012Validator
    def read(name):
        return json.loads((run_dir / name).read_text(encoding='utf-8'))
    state = read('state.json')
    result = read('AUTHORIZED_CONTINUATION_RESULT_24.json')
    evidence, calls = {}, []
    for call in result['calls']:
        path = run_dir / call['receipt']
        receipt = read(call['receipt'])
        evidence[call['receipt']] = digest(path)
        metadata = receipt.get('response_metadata', {})
        calls.append({'call_number': call['call_number'], 'receipt': call['receipt'],
            'recorded_hash_matches': call['receipt_sha256'] == digest(path),
            'finish_reason': metadata.get('finish_reason'), 'output_mode': metadata.get('output_mode'),
            'requested_thinking': metadata.get('thinking_mode'),
            'reported_tokens': metadata.get('total_tokens'), 'status': receipt.get('status')})
    plan_record = read(result['calls'][1]['receipt'])
    plan = json.loads(plan_record['response_text'])
    payload = json.loads(next(m['content'] for m in plan_record['request']['messages'] if m['role'] == 'user'))
    script, manifest = payload['script'], payload['static_visual_manifest']
    patch = json.loads(read(result['calls'][2]['receipt'])['response_text'])
    replays = {}
    for name, action in [('call19_plan', lambda: validate_state_plan(plan, script, manifest)),
                         ('call20_patch', lambda: apply_plan_patch(plan, patch))]:
        try:
            action()
            replays[name] = {'mechanical_status': 'accepted', 'semantic_approval': False}
        except (ValueError, RuntimeError) as exc:
            replays[name] = {'mechanical_status': 'rejected', 'error': str(exc), 'semantic_approval': False}
    schema = build_state_plan_schema(payload)
    patch_schema = build_patch_schema(plan, target_schema=schema)
    replays['call20_schema_errors'] = [{'path': '.'.join(map(str, e.absolute_path)), 'message': e.message[:300]}
        for e in Draft202012Validator(patch_schema).iter_errors(patch)]
    patch_paths = [row['path'] for row in patch['patches']]
    replays['call20_overlapping_paths'] = [[left, right] for i, left in enumerate(patch_paths)
        for right in patch_paths[i + 1:] if left.startswith(right + '.') or right.startswith(left + '.')]
    replays['call19_shared_timing_budget'] = timing_budget(payload, plan)
    references = []
    reference_text_hashes = {row['id']: row['text_sha256'] for row in read('materials.json').get('reference_adaptation', [])}
    for name in ['writer_analysis.json', 'writer_script.json', 'writer_revise__preflight_story_00_01.json', 'director_state_plan__00.json']:
        receipt = read(name)
        messages = receipt.get('request', {}).get('messages', [])
        found = []
        def visit(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    if (key in ('reference_pack', 'reference_expression_rule', 'reference_sha256', 'reference_use') or 'teaching' in key) and item:
                        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True)
                        found.append({'path': path + '.' + key, 'value_sha256': hashlib.sha256(serialized.encode('utf-8')).hexdigest(),
                                      'serialized_characters': len(serialized)})
                        if key == 'reference_pack' and isinstance(item, list):
                            found[-1]['text_binding_checks'] = [{'reference_id': ref.get('id'),
                                'matches_frozen_material_text': hashlib.sha256(ref.get('text', '').encode('utf-8')).hexdigest()
                                    == reference_text_hashes.get(ref.get('id'))} for ref in item if isinstance(ref, dict)]
                    visit(item, path + '.' + key)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    visit(item, path + '.' + str(i))
        for i, message in enumerate(messages):
            if message.get('role') == 'user':
                try:
                    visit(json.loads(message['content']), f'request.messages.{i}.content')
                except (ValueError, TypeError):
                    pass
        references.append({'receipt': name, 'reference_fields_in_actual_messages': found,
                           'model_used_mechanism_verified': False})
        evidence[name] = digest(run_dir / name)
    for name in ['state.json', 'materials.json', 'MODEL_OUTPUT_PROTOCOL_DIAGNOSTIC.json']:
        evidence[name] = digest(run_dir / name)
    return {'schema': 'creative_plan_offline_audit/v1', 'run_dir': str(run_dir.resolve()),
        'network_calls': 0, 'production_state_modified': False, 'content_passed': False,
        'state': {key: state.get(key) for key in ('status', 'calls_started', 'max_calls', 'reported_tokens',
             'max_total_tokens', 'revision_rounds', 'max_revisions', 'contract_repairs_used',
             'max_contract_repairs', 'rule_registry_binding')},
        'calls': calls, 'replays': replays, 'references': references, 'evidence_sha256': evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run, output = args.run_dir.resolve(), args.output.resolve()
    if output == run or run in output.parents:
        parser.error('audit output must be outside the frozen production run')
    result = audit(run)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'network_calls': 0, 'replays': result['replays']}, ensure_ascii=False))


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
