"""Inspect live schema read-only; optionally rehearse migration on a new copy."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.fanqie_promotion_ledger import REQUIRED, migrate_ledger


def row_hash(db, table):
    # Only aggregate hashes leave the DB; no account identifiers or credentials.
    rows = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str,
        separators=(",", ":")).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读检查番茄账本；可在新副本演练迁移，不改生产库")
    parser.add_argument('--source', default=str(ROOT/'data/fanqie_closed_loop_p0.db'))
    parser.add_argument('--rehearse-directory', help='新的项目内目录，保存副本、迁移前备份和证据')
    args = parser.parse_args(argv)
    source = Path(args.source).resolve()
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db:
        schema = {table: [r[1] for r in db.execute(f'PRAGMA table_info({table})')] for table in REQUIRED}
        result = {'source_read_only': True, 'compatible_base_schema': all(cols <= set(schema[t]) for t,cols in REQUIRED.items()),
                  'columns': schema, 'production_migrated': False}
        if args.rehearse_directory:
            root = Path(args.rehearse_directory).resolve()
            if not root.is_relative_to(ROOT):
                raise ValueError('rehearsal_directory_must_be_inside_project')
            root.mkdir(parents=True,exist_ok=False)
            copy = root/'ledger_copy.db'
            with sqlite3.connect(copy) as target:
                db.backup(target)
    if args.rehearse_directory:
        with sqlite3.connect(copy) as target:
            names=[r[0] for r in target.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            before={t:row_hash(target,t) for t in names}
        result['migration']=migrate_ledger(copy,root/'before_migration.db')
        with sqlite3.connect(copy) as target:
            after={t:row_hash(target,t) for t in names}
            result['integrity_check']=target.execute('PRAGMA integrity_check').fetchone()[0]
        result['original_tables_preserved']=before==after
        result['original_table_count']=len(names)
        if before!=after or result['integrity_check']!='ok':
            raise RuntimeError('migration_rehearsal_failed')
        (root/'REPORT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='columns'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
