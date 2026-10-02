"""Preserve known usage from a historical safe error without editing that receipt."""
import hashlib
import json
import re
from pathlib import Path


def reconcile(stage_path: Path):
    raw = stage_path.read_bytes()
    record = json.loads(raw)
    error = record.get('error', record.get('call_error', ''))
    response = re.search(r'(?:^|; )response_id=([A-Za-z0-9_-]+)(?:;|$)', error)
    tokens = re.search(r'(?:^|; )total_tokens=(\d+)(?:;|$)', error)
    if not response or not tokens:
        raise ValueError('No explicit provider response id and known total usage')
    value = {'schema':'creative_historical_usage_reconciliation/v1',
             'source_receipt':stage_path.name,'source_sha256':hashlib.sha256(raw).hexdigest(),
             'basis':'Known total_tokens and response_id explicitly preserved in original safe API error; prompt/completion unavailable.',
             'response_metadata':{'response_id':response.group(1),'total_tokens':int(tokens.group(1))}}
    path = stage_path.with_name(stage_path.stem+'__usage_reconciliation.json')
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError('Existing usage reconciliation differs')
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    return path


if __name__ == '__main__':
    import sys
    print(reconcile(Path(sys.argv[1])))
