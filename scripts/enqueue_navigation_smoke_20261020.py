"""One user-authorized real diagnostic through the normal account command queue."""
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.operations_accounts.browser_control_runtime import _runtime, _submit

OUT=ROOT/'data/browser_navigation_repair/20261020/production_smoke'


def main():
    auth=json.loads((OUT/'AUTHORIZATION.json').read_text(encoding='utf8'))
    assert auth['max_videos']==1 and auth['auto_like'] is False and auth['auto_comment'] is False
    if (OUT/'SUBMITTED.json').exists():
        raise RuntimeError('Existing original request; inspect it, never enqueue another attempt')
    context=_runtime().resolve('account01')
    with sqlite3.connect((ROOT/'data/account_refresh.db').as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        row=db.execute('SELECT state,recovery_token FROM account_controls WHERE account_uuid=?',
            (context.account_uuid,)).fetchone()
        if row is None or row[0]!='active' or row[1]:
            raise RuntimeError('Original account has not passed recovery')
    keywords=context.profile.seed_keywords[:1]
    assert keywords
    from src.platform_adapter.douyin_playback import PlaybackOptions
    from dataclasses import asdict
    options=asdict(PlaybackOptions(max_videos=1,per_video_seconds=15,total_minutes=2,
        min_relevance_score=60,auto_like=False,auto_comment=False))
    payload={'mode':'playback','options':{
        'authorization_reference':str(OUT/'AUTHORIZATION.json'),'headless':True,
        'playback_options':options,'research_keywords':keywords}}
    (OUT/'REQUEST.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    command=_submit('account01','maintenance',payload,
        'navigation-repair:20261020:playback-smoke-1',0)
    receipt={'at':time.time(),'command_id':command['command_id'],'state':command['state'],
        'account_uuid':context.account_uuid,'idempotency_key':command['idempotency_key']}
    (OUT/'SUBMITTED.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':
    main()
