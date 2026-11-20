"""Public compatibility and real cold imports run only in new Python children."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
PROBE=Path(__file__).with_name('_operations_accounts_lazy_import_probe.py')


def probe(mode,tmp_path):
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    result=subprocess.run([sys.executable,'-B',str(PROBE),mode],cwd=ROOT,env=env,
        capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60)
    record={'mode':mode,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    (tmp_path/'CHILD_RECEIPT.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    assert result.returncode==0,record
    value=json.loads(result.stdout.strip().splitlines()[-1])
    assert all(v==0 for v in value['guard_counts'].values())
    return value


def test_light_package_does_not_import_runtime_or_browser(tmp_path):
    assert probe('light',tmp_path)['runtime_and_browser_not_loaded']


def test_all_public_api_exports_preserve_identity_star_import_and_cache(tmp_path):
    result=probe('api',tmp_path)
    assert result['public_api_identity_count']==18 and result['platform_api_identity_count']==12


def test_failed_runtime_keeps_new_package_registered_and_retrievable(tmp_path):
    assert probe('failure_new',tmp_path)['failed_child_preserves_package_and_retry']


def test_retained_old_source_shows_eager_failure_removes_package_only_in_child(tmp_path):
    assert probe('failure_old',tmp_path)['controlled_failure_removes_old_package']


def test_failed_browser_import_keeps_platform_package_registered_and_retrievable(tmp_path):
    assert probe('platform_failure_new',tmp_path)['failed_child_preserves_platform_package']


@pytest.mark.parametrize('cold_round',range(3))
def test_real_deployment_paths_concurrently_cold_import(cold_round,tmp_path):
    assert probe('concurrent',tmp_path)['threads']==8
