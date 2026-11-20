"""Bounded navigation evidence; no URL, page text, headers or credentials in receipts."""
import time
from urllib.parse import unquote, urlsplit


def clean_navigation_evidence(value):
    value = value if isinstance(value, dict) else {}
    result = {'version': 1}
    for key in ('navigation_committed', 'target_matched'):
        result[key] = value.get(key) is True
    result['ready_state'] = value.get('ready_state') if value.get('ready_state') in {
        'loading', 'interactive', 'complete'} else 'unknown'
    result['wait_until'] = value.get('wait_until') if value.get('wait_until') in {
        'commit', 'domcontentloaded', 'load', 'networkidle'} else 'unknown'
    for key in ('timeout_ms', 'elapsed_ms'):
        number = value.get(key)
        if isinstance(number, (int, float)) and not isinstance(number, bool) and 0 <= number <= 3_600_000:
            result[key] = round(number)
    return result


def navigate(page, url, *, wait_until, timeout):
    """One navigation, with a read-only observation on a native Playwright timeout."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    committed = False

    def on_navigation(frame):
        nonlocal committed
        if frame == page.main_frame:
            committed = True

    started = time.monotonic()
    page.on('framenavigated', on_navigation)
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout)
        return {'status': 'ok', 'url': page.url}
    except PlaywrightTimeout:
        evidence = {'navigation_committed': committed, 'wait_until': wait_until,
                    'timeout_ms': timeout, 'elapsed_ms': (time.monotonic() - started) * 1000}
        try:
            expected, actual = urlsplit(url), urlsplit(page.url)
            evidence['target_matched'] = (
                expected.scheme == actual.scheme and expected.netloc == actual.netloc
                and unquote(expected.path) == unquote(actual.path) and expected.query == actual.query)
            evidence['ready_state'] = page.evaluate('document.readyState')
        except Exception:
            pass  # An unreadable page is unknown, never evidence of success.
        return {'status': 'error', 'code': 'browser_navigation_timeout',
                'msg': '页面跳转等待超时；保留当前标签页供只读检查，尚未确认页面可用。',
                'navigation_evidence': clean_navigation_evidence(evidence)}
    finally:
        page.remove_listener('framenavigated', on_navigation)
