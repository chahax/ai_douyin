from src.web.account_exception_notice import _unfinished_window_message, _WINDOW_PHASE_LABELS

def test_queued_is_not_waiting_for_close():
    value=_unfinished_window_message(dict(state='starting',phase='queued'))
    assert '尚未开窗' in value and '等待关闭' not in value
    assert '尚未打开浏览器' in _WINDOW_PHASE_LABELS['queued']

def test_unknown_is_not_claim_of_open_window():
    assert '不能据此认定窗口仍打开' in _unfinished_window_message(dict(state='outcome_unknown'))

def test_startup_is_not_close_wait():
    assert '尚未收到打开确认' in _unfinished_window_message(dict(state='starting',phase='starting_browser'))

def test_actual_open_retains_close_guidance():
    assert '关闭回执' in _unfinished_window_message(dict(state='running',phase='window_open_waiting_close'))
