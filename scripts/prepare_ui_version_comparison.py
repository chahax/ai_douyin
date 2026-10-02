"""Recover code into isolated preview roots; never reset the working tree."""
import hashlib
import json
import shutil
import sqlite3
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/ui_style_baselines/full_comparison_20260906'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / 'legacy-source.zip'
    if (OUT / 'legacy/src').exists() or (OUT / 'current/src').exists():
        raise RuntimeError('Preview already exists; do not overwrite a captured version')
    subprocess.run(['git', 'archive', '--format=zip', '--output=' + str(archive),
                    '2c0d8d5', 'src', 'config', 'alembic', 'assets', 'data/books'], cwd=ROOT, check=True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not (OUT / 'legacy' / name).resolve().is_relative_to((OUT / 'legacy').resolve()):
                raise ValueError('Archive path escape')
        bundle.extractall(OUT / 'legacy')
    for name in ['src', 'config', 'assets', '.streamlit']:
        if (ROOT / name).exists():
            shutil.copytree(ROOT / name, OUT / 'current' / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for version in ['legacy', 'current']:
        preview = OUT / version
        (preview / 'data').mkdir(exist_ok=True)
        # SQLite online backup gives a consistent local snapshot, not live DB paths.
        for name in ['douyin.db', 'wisdom_ai.db', 'trend_intelligence.db']:
            source = ROOT / 'data' / name
            if source.exists():
                with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
                    with sqlite3.connect(preview / 'data' / name) as dst:
                        src.backup(dst)
        for name in ['pre_video_scripts', 'video_generation/jimeng_continuity_20260906', 'ui_style_baselines/screenshots']:
            source = ROOT / 'data' / name
            if source.exists():
                shutil.copytree(source, preview / 'data' / name)
    report = dict(legacy_commit=subprocess.check_output(['git', 'rev-parse', '2c0d8d5'], cwd=ROOT, text=True).strip(),
                  snapshot_at=datetime.now(timezone.utc).isoformat(),
                  current_app_sha256=hashlib.sha256((ROOT / 'src/web/app.py').read_bytes()).hexdigest(),
                  notes=['Current is a copy of the dirty working tree, not HEAD.',
                         'Both versions use matching SQLite snapshots; no API configuration copied.',
                         'Preview launcher disables scheduler workers and external network connections.',
                         'Existing signed login is verified normally; user roles are not elevated.'])
    (OUT / 'capture-manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(str(OUT))


if __name__ == '__main__':
    main()
