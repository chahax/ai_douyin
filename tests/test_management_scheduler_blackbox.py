import ast
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize('outcome', [True, False, 'error'])
def test_scheduler_controls_acknowledge_real_return_not_just_no_exception(monkeypatch, outcome):
    calls = []
    def start():
        calls.append('start')
        if outcome == 'error':
            raise RuntimeError('PRIVATE_TOKEN_VALUE')
        return outcome
    monkeypatch.setitem(sys.modules, 'src.scheduler.runner', NS(start_scheduler=start,
                       stop_scheduler=lambda: calls.append('stop')))
    source = (Path(__file__).parents[1] / 'src/scheduler/ui.py').read_text(encoding='utf-8-sig')
    functions = '\n\n'.join(ast.get_source_segment(source, n) for n in ast.parse(source).body
                            if isinstance(n, ast.FunctionDef) and n.name in {'_start_scheduler', '_stop_scheduler'})
    script = ('import streamlit as st\nfrom src.web.components.action_feedback import render\n'
              + functions + "\nrender('scheduler_control')\n"
              + "if st.button('start') and _start_scheduler(): st.rerun()\n"
              + "if st.button('stop') and _stop_scheduler(): st.rerun()\n")
    app = AppTest.from_string(script).run()
    app.button[0].click().run()
    assert not app.exception and calls == ['start']
    if outcome is True:
        assert any('已确认启动' in x.value for x in app.success)
    else:
        assert not app.success and (app.warning or app.error)
        assert 'PRIVATE_TOKEN_VALUE' not in str(app.error)
    app.button[1].click().run()
    assert calls == ['start', 'stop'] and not app.exception
    assert any('Worker' in x.value and '仍按原状态执行' in x.value for x in app.success)
