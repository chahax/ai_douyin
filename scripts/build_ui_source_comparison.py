"""Offline, source-only UI comparison. Never imports application code or reads credentials."""
import ast
import difflib
import hashlib
import html
import json
import re
import subprocess
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_full_ui_comparison import PAGES, ROOT, BASE

OLD = BASE / 'legacy'
OUT = BASE / 'gallery'
SPECIAL = {
    'login': ('src/web/components/auth.py', 'render_login_page'),
    'home': ('src/web/studio_home.py', 'render_studio_home'),
    'production': ('src/web/video_production_dashboard.py', 'page_video_production'),
    'research': ('src/web/trend_dashboard.py', 'page_trend_operations'),
    'schedule': ('src/scheduler/ui.py', 'page_scheduler'),
    'workflow': ('src/web/workflow_dashboard.py', 'page_workflow_nodes'),
}
NAMES = dict(assistant='page_chat', library='page_videos', overview='page_dashboard',
             comments='page_comments', replies='page_auto_reply', memory='page_memory',
             books='page_books', batch='page_fanqie_batch_queue', usage='page_llm_usage',
             skills='page_skill_monitor', rules='page_rules', words='page_blocked_words',
             users='page_users', settings='page_settings')
ROLES = dict(login='未登录入口', research='editor', replies='editor', schedule='editor',
             books='admin', batch='editor', skills='editor', workflow='admin', rules='admin',
             words='admin', users='superadmin', settings='superadmin')
UI = {'title', 'header', 'subheader', 'caption', 'tabs', 'expander', 'button', 'form_submit_button',
      'selectbox', 'multiselect', 'radio', 'text_input', 'text_area', 'checkbox', 'toggle',
      'metric', 'file_uploader', 'download_button', 'number_input', 'page_header', 'section_header'}


def read(root, path):
    p = root / path
    return p.read_text(encoding='utf-8-sig') if p.exists() else ''


def digest(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def extract(root, path, name):
    source = read(root, path)
    if not source:
        return None
    tree = ast.parse(source)
    node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if node is None:
        raise ValueError(f'Missing {path}:{name}')
    segment = '\n'.join(source.splitlines()[node.lineno - 1:node.end_lineno])
    labels, calls, imports = [], Counter(), set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            method = n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id if isinstance(n.func, ast.Name) else ''
            if method in UI or method in {'columns', 'container', 'dataframe', 'data_editor', 'plotly_chart', 'image', 'video', 'form'}:
                calls[method] += 1
            if method in UI and n.args:
                try:
                    val = ast.literal_eval(n.args[0])
                except (ValueError, TypeError):
                    continue
                if isinstance(val, (str, list, tuple)):
                    labels.append(f'{method}: {val}')
        if isinstance(n, ast.ImportFrom):
            imports.add((n.module or '') + ': ' + ', '.join(a.name for a in n.names))
    return dict(path=path, absolute=str((root / path).resolve()), function=name, line=node.lineno,
                end_line=node.end_lineno, sha256=digest(segment), source=segment,
                labels=list(dict.fromkeys(labels)), calls=dict(calls), imports=sorted(imports))


def difference(a, b):
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), fromfile='旧版', tofile='新版', lineterm=''))
    return dict(added=sum(x.startswith('+') and not x.startswith('+++') for x in lines),
                removed=sum(x.startswith('-') and not x.startswith('---') for x in lines), text='\n'.join(lines))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for identity, title, old_route, new_route, group in PAGES:
        path, name = SPECIAL.get(identity, ('src/web/app.py', NAMES.get(identity)))
        old = extract(OLD, path, name) if old_route is not None else None
        new = extract(ROOT, path, name)
        assert new, identity
        diff = difference(old['source'] if old else '', new['source'])
        added_labels = [x for x in new['labels'] if not old or x not in old['labels']]
        removed_labels = [x for x in old['labels'] if x not in new['labels']] if old else []
        status = '新增页面' if old is None else '页面函数有变化' if diff['text'] else '页面函数未变；公共主题仍影响呈现'
        rows.append(dict(id=identity, title=title, group=group, role=ROLES.get(identity, 'viewer'),
                         old_route=old_route, new_route=new_route, old=old, new=new, diff=diff,
                         status=status, added_labels=added_labels, removed_labels=removed_labels))
    # Full web modules include helpers, global setup and imports beyond page entry functions.
    paths = {str(p.relative_to(root)).replace('\\', '/') for root in [OLD, ROOT]
             for p in (root / 'src/web').rglob('*') if p.suffix in {'.py', '.css', '.svg'}}
    paths.add('src/scheduler/ui.py')
    modules = []
    for path in sorted(paths):
        a, b = read(OLD, path), read(ROOT, path)
        d = difference(a, b)
        modules.append(dict(path=path, old_sha256=digest(a) if a else None,
                            new_sha256=digest(b) if b else None, diff=d,
                            status='新增' if not a else '移除' if not b else '修改' if a != b else '未变'))
    theme_old = read(OLD, 'src/web/components/ui.py')
    theme_new = read(ROOT, 'src/web/components/studio.css')
    tokens = []
    for key in ['bg', 'surface', 'surface-soft', 'sidebar', 'text', 'muted', 'line', 'accent', 'accent-2', 'shadow']:
        def token(source):
            match = re.search(r'--studio-' + re.escape(key) + r'\s*:\s*([^;]+);', source)
            return match.group(1).strip() if match else '未定义'
        tokens.append(dict(name=key, old=token(theme_old), new=token(theme_new)))
    legacy_commit = '2c0d8d5984525f033e0b169971c56aaa7de7d81d'
    # Verify archived Python source against Git; preview-only configuration is excluded.
    baseline_checks = []
    for path in sorted({p['old']['path'] for p in rows if p['old']} | {'src/web/components/ui.py'}):
        result = subprocess.run(['git', 'show', f'{legacy_commit}:{path}'], cwd=ROOT, capture_output=True, check=True)
        matches = result.stdout.decode('utf-8-sig').replace('\r\n', '\n') == read(OLD, path).replace('\r\n', '\n')
        assert matches, f'Baseline mismatch: {path}'
        baseline_checks.append(path)
    data = dict(generated_at=datetime.now(timezone.utc).astimezone().isoformat(), legacy_commit=legacy_commit,
                current='当前工作树（包括未提交改动）', baseline_verified=baseline_checks,
                scope='20 个导航/入口页面及 src/web 全部 Python/CSS/SVG 模块、调度 UI；非整个业务后端审计',
                limitations='静态代码证据，不是真实截图，不代表接口调用、登录持久化或生成任务已通过运行验证。UI 调用数是静态调用点，非实际显示控件数；动态标题和跨模块辅助函数不会出现在页面标签清单中。',
                pages=rows, modules=modules, theme=tokens)
    (OUT / 'source-comparison.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    md = ['# 全页面旧新源码对比', '', f'生成时间：{data["generated_at"]}', '',
          f'旧版：`{legacy_commit}`；新版：当前工作树。', '', data['scope'], '', data['limitations'], '',
          '## 总体结论', '',
          '- 旧版浅色内容区＋紫色强调色，新版深石墨内容区＋青柠强调色；公共 CSS 会影响所有页面。',
          '- 新增创作工作台、视频制作；默认入口从 AI 助手变成创作工作台，导航改为按创作、运营、资源、管理分组。',
          '- 新版更偏创作工作室：突出内容生产入口；旧版更偏后台工具。此为基于样式及导航源码的设计解读，不是实际截图评测。',
          '- 对比风格时建议固定视口、角色、数据状态；不能把权限隐藏、空数据或功能增减误判为纯视觉变化。', '',
          '## 全部页面', '', '| 页面 | 分组 | 最低角色（新版导航） | 变化 | 文本增/删行 |', '|---|---|---|---|---|']
    for p in rows:
        md.append(f'| {p["title"]} | {p["group"]} | {p["role"]} | {p["status"]} | +{p["diff"]["added"]} / -{p["diff"]["removed"]} |')
    md += ['', '## 主题参数', '', '| Token | 旧版 | 新版 |', '|---|---|---|']
    md += [f'| {t["name"]} | {t["old"]} | {t["new"]} |' for t in tokens]
    for p in rows:
        md += ['', f'## {p["title"]}', '', f'{p["status"]}。路由：{p["old_route"] or "无"} → {p["new_route"]}。', '']
        for label in ['old', 'new']:
            s = p[label]
            if s:
                md.append(f'- {"旧版" if label == "old" else "新版"}源码：[{s["path"]}:{s["line"]}]({s["absolute"].replace(chr(92), "/")}:{s["line"]})，函数 `{s["function"]}`。')
        md += ['', '新增/修改的静态界面文案：', ''] + [f'- {x}' for x in p['added_labels']]
        if not p['added_labels']:
            md.append('未提取到新增静态文案；不等于功能或样式没有变化。')
        md += ['', '移除/被替换的静态界面文案：', ''] + [f'- {x}' for x in p['removed_labels']]
        if not p['removed_labels']:
            md.append('无。')
    md += ['', '## 审计说明', '', f'旧版 {len(baseline_checks)} 个页面/主题源文件已逐一与 Git 原文核对一致。', '',
           '交互 HTML 包含全部页面的旧新完整入口函数、逐行差异及所有扫描模块的完整差异；JSON 保留源码指纹供下次比较。未读取账号密码、Cookie、环境密钥或数据库记录。']
    (OUT / 'source-comparison.md').write_text('\n'.join(md), encoding='utf-8')
    template = Path(__file__).with_name('ui_source_comparison_template.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    (OUT / 'source-comparison.html').write_text(template.replace('__DATA__', payload), encoding='utf-8')
    with zipfile.ZipFile(BASE / 'source-comparison.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ['source-comparison.html', 'source-comparison.md', 'source-comparison.json']:
            z.write(OUT / name, name)
    print(json.dumps(dict(pages=len(rows), added=[p['title'] for p in rows if not p['old']], modules=len(modules),
                          baseline_verified=len(baseline_checks), output=str(OUT / 'source-comparison.html')), ensure_ascii=False))


if __name__ == '__main__':
    main()
