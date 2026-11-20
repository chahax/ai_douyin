"""Actual provider/workflow/maintenance/receipt resolver with no platform IO."""
import json
import time
import pytest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.operations_accounts.maintenance import AccountMaintenanceService
from src.operations_accounts.manual_handling import resolve_manual_handling_target
from src.trend_intelligence.providers.douyin_web import build_douyin_search_url
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.research_workflow import AccountVideoResearchWorkflow


@pytest.mark.parametrize("unready,navigation_timeout", [(False, False), (True, False), (False, True)])
def test_actual_blocked_search_survives_full_pipeline_and_targets_same_query(tmp_path, unready, navigation_timeout, monkeypatch):
    monkeypatch.setenv("AI_DOUYIN_BROWSER_CONTROL", "0")
    monkeypatch.setenv("ACCOUNT_BROWSER_CONTROL_DB", str(tmp_path / "browser_control.db"))
    events = []
    class Locator:
        def evaluate(self, script):
            return dict(blocking=unready,frame_count=int(unready),actionable_frames=int(unready),visible_dialogs=0,surface_states=['blank'] if unready else [])
        def inner_text(self):
            return '安全验证'
        def count(self):
            return 0
    class Page:
        def locator(self, selector):
            return Locator()
        def wait_for_timeout(self, milliseconds):
            assert milliseconds in (400,800,1600,3200)  # A bounded second observation, no reload/navigation.
    class Session:
        def open_page(self, url):
            events.append(('open', url))
            if navigation_timeout:
                from src.platform_adapter.browser_session import BrowserNavigationTimeout
                raise BrowserNavigationTimeout(dict(navigation_committed=False, target_matched=False,
                    ready_state='loading', wait_until='domcontentloaded', timeout_ms=30000))
            return Page()
        def save_storage_state(self):
            events.append(('checkpoint',))
        def stop(self):
            events.append(('stop',))
    profile = AccountProfile(account_uuid=stable_account_uuid('account01'), account_key='account01',
        domain_strategy_id='legal_services', display_name='本地测试', seed_keywords=['装修合同', '租房押金'])
    session = Session()
    context = SimpleNamespace(profile=profile, account_uuid=profile.account_uuid,
        account_key=profile.account_key, identity_label='local fixture',
        binding=SimpleNamespace(status='active'), create_browser_session=lambda **k:session)
    class Runtime:
        def resolve(self, key):
            assert key == profile.account_key
            return context
        @contextmanager
        def operation_lease(self, *args, **kwargs):
            events.append(('lease',))
            try:
                yield 'fixture-lease'
            finally:
                events.append(('release',))
        def verify_identity(self, context, *, session):
            return SimpleNamespace(healthy=True, message='local identity fixture')
    class Adapter:
        def sync_videos(self, **kwargs):
            return SimpleNamespace(success=True, message='ok', videos=[SimpleNamespace(video_id='local-video')])
        def fetch_comments(self, query):
            return SimpleNamespace(success=True, comments=[])
        def close(self):
            pass
    research_dir = tmp_path / 'research'
    log_root = tmp_path / 'maintenance'
    workflow = AccountVideoResearchWorkflow(TrendRepository(tmp_path / 'trend.db'), log_dir=research_dir)
    before = time.time()
    result = AccountMaintenanceService(runtime=Runtime(), research_factory=lambda:workflow,
        adapter_factory=lambda *a, **k:Adapter(), log_dir=log_root).run(
            'account01', 'smart-operations', authorization_reference='local test, no network')
    finished = time.time()
    code='browser_navigation_timeout' if navigation_timeout else 'verification_ui_unconfirmed'
    assert result.error_code == code
    assert result.status == ('blocked' if navigation_timeout else 'partial')
    assert result.failure_stage == 'research'
    assert result.blocked_search['query'] == '装修合同'
    assert result.blocked_search['sort_key'] == 'comprehensive'
    assert result.playback_verified_videos == result.actual_watch_seconds == 0
    saved = json.loads(Path(result.log_path).read_text(encoding='utf-8'))
    research = json.loads(next(research_dir.glob('*.json')).read_text(encoding='utf-8'))
    assert saved['blocked_search'] == research['blocked_search'] == result.blocked_search
    assert saved['challenge_evidence'] == research['challenge_evidence'] == result.challenge_evidence
    if navigation_timeout:
        assert saved['navigation_evidence'] == research['navigation_evidence'] == result.navigation_evidence
        assert result.navigation_evidence['navigation_committed'] is False
        assert result.navigation_evidence['target_matched'] is False
        assert not result.challenge_evidence
        assert len([e for e in events if e[0] == 'open']) == 1
        assert events[-2:] == [('stop',),('release',)]
        return
    assert saved['challenge_evidence']['version']==3
    assert saved['challenge_evidence'].get('security_text_confirmed',False) is (not unready)
    assert saved['challenge_evidence']['confirmations']==0
    run_id = '1' * 32
    snap = {'controls':[dict(account_uuid=profile.account_uuid, account_key=profile.account_key,
                state='paused', error_code=code, updated_at=finished)],
            'smart_runs':[dict(run_id=run_id, account_uuid=profile.account_uuid,
                account_key=profile.account_key, status='partial', started_at=before, finished_at=finished,
                detail=dict(error_code=code,maintenance_run_id=result.run_id))]}
    target = resolve_manual_handling_target(profile, snapshot=snap, log_root=log_root)
    assert target.source == 'blocked_search'
    assert target.url == build_douyin_search_url('装修合同')
    assert target.run_id == run_id
    assert [e for e in events if e[0] == 'open'] == [('open',target.url)]
    assert events[-2:] == [('stop',),('release',)]
