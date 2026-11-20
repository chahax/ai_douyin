"""Local Chrome form checks; no platform requests or promotion submissions."""
import inspect
import json

import pytest
from playwright.sync_api import sync_playwright

from src.platform_adapter.fanqie_promotion import FILL_AND_SUBMIT_JS, FanqiePromotionService


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=["--mute-audio"])
        yield browser
        browser.close()


def run_form(browser, *, selected="请选择", options=("AI数字人", "AIGC"), requested="AIGC",
             auto_submit=True, ignore_click=False, missing=False):
    page = browser.new_page()
    page.route("**/*", lambda route: route.abort())
    try:
        page.set_content('''<div class="arco-modal-content">
          <div><input class="alias-input-EBp1Sw"></div>
          <button class="arco-select">请选择</button>
          <div id="options" style="display:none"></div>
          <button id="submit">提交申请</button></div>''')
        page.evaluate('''({selected,options,ignoreClick,missing}) => {
          window.submits=0;
          const select=document.querySelector('.arco-select');
          select.textContent=selected;
          select.onclick=()=>document.querySelector('#options').style.display='block';
          for(const name of options){
            const option=document.createElement('button');
            option.className='arco-select-option';option.textContent=name;
            option.onclick=()=>{if(!ignoreClick) select.textContent=name;
              document.querySelector('#options').style.display='none';};
            document.querySelector('#options').appendChild(option);
          }
          if(missing) select.remove();
          document.querySelector('#submit').onclick=()=>{window.submits++;
            document.body.insertAdjacentHTML('beforeend','<div class="title-azi_qL">别名创建成功</div>');};
        }''', dict(selected=selected, options=options, ignoreClick=ignore_click, missing=missing))
        result = page.evaluate(FILL_AND_SUBMIT_JS.substitute(
            alias=json.dumps("测试别名"), publish_type=json.dumps(requested), max_attempts="1",
            auto_submit=json.dumps(auto_submit)))
        return result, page.evaluate("window.submits")
    finally:
        page.close()


@pytest.mark.parametrize("selected", ["请选择", "AI数字人", "AIGC"])
def test_selects_aigc_and_submits_once(browser, selected):
    result, submits = run_form(browser, selected=selected)
    assert result["publish_type"] == "AIGC"
    assert result["publish_type_selected"] and result["submitted"]
    assert submits == 1


@pytest.mark.parametrize("kwargs,step", [
    ({"options": ["AI数字人", "视频"]}, "publish_type_unavailable"),
    ({"options": ["AIGC", "AIGC"]}, "publish_type_unavailable"),
    ({"ignore_click": True}, "publish_type_unconfirmed"),
    ({"missing": True}, "publish_type_missing"),
])
def test_uncertain_selection_never_submits(browser, kwargs, step):
    result, submits = run_form(browser, **kwargs)
    assert not result["submitted"] and result["step"] == step
    assert submits == 0


def test_manual_mode_fills_without_submitting(browser):
    result, submits = run_form(browser, auto_submit=False)
    assert result["step"] == "manual_confirm"
    assert result["publish_type"] == "AIGC"
    assert not result["submitted"] and submits == 0


def test_explicit_other_type_remains_supported(browser):
    result, submits = run_form(browser, requested="AI数字人")
    assert result["publish_type"] == "AI数字人" and submits == 1


def test_service_cli_and_agent_default_to_aigc(monkeypatch):
    import ast
    import argparse
    from pathlib import Path
    from src.agent.registry import _fanqie_apply_promotion
    from dataclasses import dataclass

    assert inspect.signature(FanqiePromotionService.apply_promotion).parameters["publish_type"].default == "AIGC"
    # Execute the actual CLI argument declarations without main's database startup.
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    parser_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_parser")
    declarations = [n for n in parser_node.body if
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and
        isinstance(n.value.func, ast.Attribute) and isinstance(n.value.func.value, ast.Name) and
        n.value.func.value.id == "fanqie_apply_parser"]
    parser = argparse.ArgumentParser()
    exec(compile(ast.Module(body=declarations, type_ignores=[]), "main.py", "exec"), {"fanqie_apply_parser": parser})
    assert parser.parse_args([]).publish_type == "AIGC"
    assert parser.parse_args(["--publish-type", "真人出镜"]).publish_type == "真人出镜"
    @dataclass
    class Task:
        publish_type: str
    captured = []
    def apply(self, **kwargs):
        captured.append(kwargs["publish_type"])
        return Task(kwargs["publish_type"])
    monkeypatch.setattr(FanqiePromotionService, "apply_promotion", apply)
    assert _fanqie_apply_promotion()["success"]
    assert captured == ["AIGC"]
