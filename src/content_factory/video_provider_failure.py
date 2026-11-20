"""Classify provider receipts without guessing the offending content or billing."""


def classify_failure(payload):
    if payload.get('status') not in {'failed', 'expired', 'cancelled'}:
        return None
    error = payload.get('error') or {}
    code = str(error.get('code', ''))
    policy = 'SensitiveContentDetected' in code or 'PolicyViolation' in code
    stage = ('output_video' if code.startswith('OutputVideo') else
             'output_audio' if code.startswith('OutputAudio') else
             'input' if code.startswith('Input') else 'unknown')
    return {
        'schema': 'video_provider_failure/v1',
        'task_id': payload.get('id'),
        'provider_status': payload['status'],
        'error_code': code,
        'error_message': error.get('message', ''),
        'category': 'content_policy' if policy else 'provider_failure',
        'stage': stage,
        'cause_confirmed': False,
        'billing_status': 'unknown',
        'counts_as_visual_review_failure': False,
        'automatic_retry_allowed': False,
        'continuation_allowed': False,
        'next_action': ('provider_review_required' if policy else 'inspect_provider_failure'),
    }
