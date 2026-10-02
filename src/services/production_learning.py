"""Persistent, account-scoped references and evidence-backed production experiments."""
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from src.services.database import get_db
from src.services.content_performance import _scope, _ensure_table


def _tables(db):
    _ensure_table(db)
    db.execute('''CREATE TABLE IF NOT EXISTS video_learning_references (
        id INTEGER PRIMARY KEY, account_uuid TEXT NOT NULL, url TEXT NOT NULL,
        title TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '待学习',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(account_uuid,url))''')
    db.execute('''CREATE TABLE IF NOT EXISTS production_learning_experiments (
        id INTEGER PRIMARY KEY, account_uuid TEXT NOT NULL, title TEXT NOT NULL,
        hypothesis TEXT NOT NULL, proposed_change TEXT NOT NULL, evaluation TEXT NOT NULL,
        snapshot_ids_json TEXT NOT NULL, reference_ids_json TEXT NOT NULL,
        baseline_version TEXT NOT NULL, candidate_version TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '待验证', outcome TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS production_learning_outcomes (
        id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL, account_uuid TEXT NOT NULL,
        status TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL)''')


def save_reference(account_uuid, url, title, reason='', notes='', tags='', status='待学习'):
    _scope(account_uuid)
    parts = urlsplit(url.strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('请输入完整的 HTTP/HTTPS 视频链接')
    if status not in ('待学习', '已学习', '暂不采用') or not title.strip():
        raise ValueError('请填写标题并选择有效学习状态')
    url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ''))
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        _tables(db)
        db.execute('''INSERT INTO video_learning_references
            (account_uuid,url,title,reason,notes,tags,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(account_uuid,url) DO UPDATE SET title=excluded.title,reason=excluded.reason,
            notes=excluded.notes,tags=excluded.tags,status=excluded.status,updated_at=excluded.updated_at''',
            (account_uuid,url,title.strip(),reason,notes,tags,status,now,now))
        db.commit()
        return db.execute('SELECT id FROM video_learning_references WHERE account_uuid=? AND url=?',
                          (account_uuid,url)).fetchone()[0]


def list_references(account_uuid):
    _scope(account_uuid)
    with get_db() as db:
        _tables(db)
        return [dict(r) for r in db.execute('SELECT * FROM video_learning_references WHERE account_uuid=? ORDER BY updated_at DESC,id DESC', (account_uuid,))]


def save_experiment(account_uuid, *, title, hypothesis, proposed_change, evaluation,
                    snapshot_ids, reference_ids=(), baseline_version='', candidate_version=''):
    _scope(account_uuid)
    if not all(str(v).strip() for v in (title, hypothesis, proposed_change, evaluation)):
        raise ValueError('请填写实验名称、假设、生产改动及评价方法')
    if not snapshot_ids:
        raise ValueError('至少选择一个观看数据快照作为证据')
    with get_db() as db:
        _tables(db)
        for table, ids in [('creator_metric_snapshots', snapshot_ids), ('video_learning_references', reference_ids)]:
            for item_id in ids:
                if not db.execute(f'SELECT id FROM {table} WHERE id=? AND account_uuid=?', (item_id,account_uuid)).fetchone():
                    raise ValueError('证据或参考视频不属于当前账号')
        now = datetime.now(timezone.utc).isoformat()
        cursor = db.execute('''INSERT INTO production_learning_experiments
            (account_uuid,title,hypothesis,proposed_change,evaluation,snapshot_ids_json,reference_ids_json,
            baseline_version,candidate_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (account_uuid,title,hypothesis,proposed_change,evaluation,json.dumps(list(snapshot_ids)),
             json.dumps(list(reference_ids)),baseline_version,candidate_version,now,now))
        db.commit()
        return cursor.lastrowid


def list_experiments(account_uuid):
    _scope(account_uuid)
    with get_db() as db:
        _tables(db)
        return [dict(r) for r in db.execute('SELECT * FROM production_learning_experiments WHERE account_uuid=? ORDER BY id DESC', (account_uuid,))]


def record_outcome(account_uuid, experiment_id, status, outcome):
    _scope(account_uuid)
    if status not in ('待验证', '试验中', '保留改动', '不采用') or not outcome.strip():
        raise ValueError('请填写实验结果说明')
    with get_db() as db:
        _tables(db)
        now = datetime.now(timezone.utc).isoformat()
        result = db.execute('''UPDATE production_learning_experiments SET status=?,outcome=?,updated_at=?
            WHERE id=? AND account_uuid=?''', (status,outcome,now,experiment_id,account_uuid))
        if result.rowcount != 1:
            raise ValueError('当前账号没有此实验')
        db.execute('INSERT INTO production_learning_outcomes(experiment_id,account_uuid,status,outcome,created_at) VALUES (?,?,?,?,?)',
                   (experiment_id,account_uuid,status,outcome,now))
        db.commit()


def experiment_packet(account_uuid, experiment_id):
    """Export an auditable input for future script/storyboard/production revisions."""
    plan = next((r for r in list_experiments(account_uuid) if r['id'] == experiment_id), None)
    if plan is None:
        raise ValueError('当前账号没有此实验')
    with get_db() as db:
        evidence = [dict(db.execute('SELECT * FROM creator_metric_snapshots WHERE id=? AND account_uuid=?',
                                   (item,account_uuid)).fetchone()) for item in json.loads(plan['snapshot_ids_json'])]
        outcomes = [dict(r) for r in db.execute('SELECT * FROM production_learning_outcomes WHERE account_uuid=? AND experiment_id=? ORDER BY id',
                                               (account_uuid,experiment_id))]
    reference_ids = json.loads(plan['reference_ids_json'])
    references = [r for r in list_references(account_uuid) if r['id'] in reference_ids]
    return {'schema_version': 1, 'experiment': plan, 'metric_evidence': evidence, 'references': references, 'outcome_history': outcomes,
            'usage': '用作生产改进实验依据；结合发布时间、样本量、统计口径和单变量对比。执行改动后仍按逐段声画审核流程验收。'}
