"""Provider capability snapshots and explicitly approximate token accounting."""
import json
import math
from copy import deepcopy
from datetime import date

PROFILES = {
    'writer': dict(provider='minimax', model='MiniMax-M3.1-Flash', protocol='openai_chat',
        base_url='https://api.minimax.cn/v1', context_window=1000000,
        max_output_tokens=524288, recommended_output_tokens=131072,
        efforts=['low','medium','high','xhigh','max'], verified_on='2026-11-01',
        source='https://platform.minimax.cn/docs/api-reference/text/api/openapi-chat-openai.json'),
    'director': dict(provider='deepseek', model='deepseek-flash', protocol='openai_chat',
        base_url='https://api.deepseek.com/v1', context_window=1048576,
        max_output_tokens=393216, recommended_output_tokens=65536,
        efforts=['low','high','max'], verified_on='2026-11-01',
        source='https://api-docs.deepseek.com/api/list-models/'),
}


def profiles():
    return deepcopy(PROFILES)


def validate_profile(profile, model, effort, output_tokens):
    if profile['model'] != model or profile['protocol'] != 'openai_chat':
        raise ValueError('capability_model_protocol_mismatch')
    if effort not in profile['efforts']:
        raise ValueError('unsupported_effort')
    if type(output_tokens) is not int or not 0 < output_tokens <= profile['max_output_tokens']:
        raise ValueError('output_exceeds_provider_capability')
    if not profile.get('source') or not profile.get('verified_on'):
        raise ValueError('capability_provenance_missing')


def capacity_report(messages, schema, profile, output_tokens):
    import tiktoken
    # This is a proxy tokenizer, not falsely labelled as either vendor's tokenizer.
    serialized=json.dumps({'messages':messages,'tools_schema':schema},ensure_ascii=False)
    count=len(tiktoken.get_encoding('cl100k_base').encode(serialized,disallowed_special=()))
    margin=max(2048,math.ceil(count*.35))
    estimated=count+margin
    return dict(method='cl100k_base_proxy_with_35pct_margin', exact=False,
        serialized_bytes=len(serialized.encode('utf-8')), estimated_input_tokens=count,
        safety_margin_tokens=margin, reserved_input_tokens=estimated,
        requested_output_tokens=output_tokens, context_window=profile['context_window'],
        decision='fits_estimate' if estimated+output_tokens<=profile['context_window'] else 'needs_exact_count_or_smaller_scope')


def deadline_seconds(output_tokens):
    # Total duration grows with allowed output; SDK read-idle remains 90 seconds.
    return max(900,math.ceil(output_tokens/40)+180)


def official_metadata(profile, data):
    """Merge only machine-readable limits of the exact model; ignore secrets/other fields."""
    row=next((x for x in data.get('data',[]) if x.get('id')==profile['model']),None)
    if row is None:raise ValueError('model_missing_from_provider')
    result=deepcopy(profile)
    for key in ['context_window','max_output_tokens']:
        if type(row.get(key)) is int and row[key]>0:result[key]=row[key]
    levels=row.get('effort',{}).get('supported_levels')
    if levels:result['efforts']=levels
    result['metadata_observed']=True
    return result
