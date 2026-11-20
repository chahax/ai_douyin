"""Read-only original publication dates; never substitute execution timestamps."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .publication_evidence import PublicationEvidenceReader


def _sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _date(value, *, native=False):
    if not isinstance(value,str):raise ValueError('publication_date_missing')
    if native:
        try:t=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:raise ValueError('publication_date_invalid') from None
        if t.tzinfo is None:raise ValueError('native_publication_timezone_required')
    else:
        try:t=datetime.strptime(value,'%Y年%m月%d日 %H:%M').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        except ValueError:raise ValueError('creator_publication_date_invalid') from None
    return t.isoformat()


def read_publication_time(browser_db, publication_command_id, account_uuid, binding_version, *, metadata_command_id=None, evidence_root=None):
    """Return a canonical date plus hash-bound original command evidence."""
    receipt=PublicationEvidenceReader(browser_db,evidence_root=evidence_root).read(publication_command_id,account_uuid,binding_version)
    with sqlite3.connect(Path(browser_db).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        original=dict(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(publication_command_id,)).fetchone())
        result=json.loads(original['result']);payload=json.loads(original['payload'])
        value=result.get('published_at') or (result.get('publish_evidence') or {}).get('published_at')
        if value:
            date=_date(value,native=True);source='original_publish';command=original
        else:
            if not metadata_command_id:raise ValueError('verified_publication_metadata_required')
            r=db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(metadata_command_id,)).fetchone()
            if r is None:raise ValueError('publication_metadata_missing')
            command=dict(r);mp=json.loads(command['payload']);mr=json.loads(command['result'] or '{}').get('read_result',{})
            if (command['kind']!='read' or command['state']!='succeeded' or command['account_id']!=account_uuid
                or command['binding_version']!=binding_version or mp.get('method')!='sync_videos' or mr.get('success') is not True):
                raise ValueError('publication_metadata_wrong_subject')
            account_key=payload.get('account_key') or payload.get('request',{}).get('extra_metadata',{}).get('account_key')
            # Runtime _submit adds account_key to the original publish payload.
            if not account_key:raise ValueError('publication_account_key_missing')
            videos=[v for v in mr.get('videos',[]) if v.get('video_id')==receipt['post_id']]
            if len(videos)!=1 or videos[0].get('account_uuid')!=account_uuid or videos[0].get('account_key')!=account_key:
                raise ValueError('publication_metadata_post_or_account_mismatch')
            value=videos[0].get('publish_time');date=_date(value);source='verified_sync_videos'
        # Exclude mutable cursor/heartbeat. Bind immutable identity and actual payload/result.
        snapshot={k:command[k] for k in ('command_id','account_id','binding_version','kind','state')}
        snapshot.update(payload=json.loads(command['payload']),result=json.loads(command['result']))
        return {'schema':'publication_time_evidence/v1','published_at':date,'source':source,
            'publication_command_id':publication_command_id,'post_id':receipt['post_id'],'account_uuid':account_uuid,
            'binding_version':binding_version,'source_command_id':command['command_id'],
            'source_snapshot_sha256':_sha(snapshot),'raw_publication_time':value}


def verify_publication_time(browser_db, evidence, *, evidence_root=None):
    actual=read_publication_time(browser_db,evidence['publication_command_id'],evidence['account_uuid'],evidence['binding_version'],
        metadata_command_id=evidence['source_command_id'] if evidence.get('source')=='verified_sync_videos' else None,
        evidence_root=evidence_root)
    if actual!=evidence:raise ValueError('publication_time_evidence_changed')
    return actual
