"""Open a managed Chromium profile with its first window already minimized."""
import json
from html import escape
from pathlib import Path
import subprocess
import uuid


def launch(pw, user_data_dir, options, account_label):
    from playwright._impl._driver import compute_driver_executable

    # Ordinary persistent launch waits for an initial, foreground about:blank.
    # Ask this installed driver for its own switches (including sandbox policy
    # and private debugging pipe), using its no-startup-window form instead.
    node, cli = compute_driver_executable()
    driver = Path(cli).parent
    script = """const root = process.argv[1];
require(root);
const { Chromium } = require(require('path').join(root, 'lib/server/chromium/chromium.js'));
const { options, profile } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
Chromium.prototype.defaultArgs(options, false, profile)
  .then(args => process.stdout.write(JSON.stringify(args)));"""
    effective = {'headless': False, 'chromiumSandbox': options['chromium_sandbox'],
                 'channel': options.get('channel'), 'args': options.get('args', [])}
    result = subprocess.run([node, '-e', script, str(driver)], check=True, capture_output=True,
        input=json.dumps({'options': effective, 'profile': str(Path(user_data_dir).resolve())}),
        text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    args = json.loads(result.stdout)
    if ('--no-startup-window' not in args or '--remote-debugging-pipe' not in args
            or any(arg.startswith('--remote-debugging-port') for arg in args)):
        raise RuntimeError('Installed Chromium driver does not support taskbar startup')
    context = pw.chromium.launch_persistent_context(user_data_dir=user_data_dir,
        **dict(options, args=args, ignore_default_args=True, no_viewport=True))
    try:
        browser = context.browser.new_browser_cdp_session()
        try:
            if context.pages:
                raise RuntimeError('Unexpected window at taskbar startup')
            marker = 'about:blank#' + uuid.uuid4().hex
            with context.expect_page(lambda page: page.url == marker) as initial:
                browser.send('Target.createTarget', {'url': marker, 'newWindow': True,
                    'windowState': 'minimized', 'background': True})
            if account_label:
                title = escape(account_label) + ' · 抖音业务窗口'
                initial.value.set_content(f'<title>{title}</title><h1>{title}</h1>'
                                          '<p>点击上方的业务标签页，查看当前页面。</p>')
        finally:
            browser.detach()
        return context
    except BaseException:
        context.close()
        raise


def new_background_tab(context):
    marker = 'about:blank#' + uuid.uuid4().hex
    browser = context.browser.new_browser_cdp_session()
    try:
        with context.expect_page(lambda page: page.url == marker) as opened:
            browser.send('Target.createTarget', {'url': marker, 'background': True})
        return opened.value
    finally:
        browser.detach()
