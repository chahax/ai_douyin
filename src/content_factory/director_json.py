"""Conservative, replayable repair of one final JSON container delimiter.

Never repair strings, values, interior punctuation, or length-truncated responses.
Semantic and stage validation remain separate requirements.
"""
import hashlib
import json
from pathlib import Path

from src.trend_intelligence.cohort_scene_flow import strict_json, FlowError


def sha(data):
    return hashlib.sha256(data).hexdigest()


def terminal_delimiter(raw):
    try:
        strict_json(raw)
    except FlowError as exc:
        if exc.code != 'invalid_json':
            raise ValueError('Only terminal syntax errors can be repaired') from exc
    else:
        raise ValueError('Valid JSON needs no repair')
    stack = []
    quoted = escaped = False
    last = len(raw.rstrip()) - 1
    replacement = None
    for i, char in enumerate(raw):
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack:
                raise ValueError('Unexpected closing delimiter')
            expected = {'{': '}', '[': ']'}[stack[-1]]
            if char != expected:
                if i != last or len(stack) != 1:
                    raise ValueError('Interior delimiter error cannot be repaired')
                replacement = (i, char, expected)
            stack.pop()
    if quoted:
        raise ValueError('Incomplete string cannot be repaired')
    if replacement is None:
        if len(stack) != 1:
            raise ValueError('Only one missing final delimiter can be repaired')
        replacement = (last + 1, '', {'{': '}', '[': ']'}[stack[0]])
    index, old, new = replacement
    repaired = raw[:index] + new + raw[index + len(old):]
    value = strict_json(repaired)
    if not isinstance(value, dict):
        raise ValueError('Director output must be an object')
    return value, {'recipe': 'terminal_container_delimiter/v1',
                   'index': index, 'old': old, 'new': new,
                   'raw_sha256': sha(raw.encode('utf-8')),
                   'repaired_sha256': sha(repaired.encode('utf-8'))}


def repair_failed_output(folder):
    folder = Path(folder)
    if (folder / 'candidate.json').exists() or (folder / 'syntax_repair.json').exists():
        raise ValueError('Cannot replace an existing candidate or repair')
    response = json.loads((folder / 'response.json').read_text(encoding='utf-8'))
    if response.get('finish_reason') != 'stop':
        raise ValueError('Only a completed, non-truncated response can be repaired')
    raw = (folder / 'raw.txt').read_text(encoding='utf-8')
    value, manifest = terminal_delimiter(raw)
    manifest['response_sha256'] = sha((folder / 'response.json').read_bytes())
    manifest['scope'] = 'syntax_only_not_semantic_approval'
    for name, content in [('syntax_repair.json', manifest), ('candidate.json', value)]:
        (folder / name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


def authored_value(folder):
    """Replay raw provenance, including a disclosed terminal repair if present."""
    folder = Path(folder)
    raw = (folder / 'raw.txt').read_text(encoding='utf-8')
    repair = folder / 'syntax_repair.json'
    if not repair.exists():
        return strict_json(raw)
    response = json.loads((folder / 'response.json').read_text(encoding='utf-8'))
    if response.get('finish_reason') != 'stop':
        raise ValueError('Repaired response was not complete')
    value, expected = terminal_delimiter(raw)
    expected['response_sha256'] = sha((folder / 'response.json').read_bytes())
    expected['scope'] = 'syntax_only_not_semantic_approval'
    if json.loads(repair.read_text(encoding='utf-8')) != expected:
        raise ValueError('Syntax repair provenance changed')
    return value
