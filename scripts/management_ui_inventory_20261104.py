"""Static feature inventory only: no app imports, DB, network or production calls."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/development_checkpoints/management_ui_audit_20261104'
WIDGETS = {'button', 'form_submit_button', 'download_button', 'link_button', 'page_link',
           'checkbox', 'toggle', 'selectbox', 'multiselect', 'radio', 'text_input',
           'text_area', 'number_input', 'file_uploader', 'tabs', 'expander', 'chat_input'}


def build():
    app = ast.parse((ROOT / 'src/web/app.py').read_text(encoding='utf-8-sig'))
    nav = next(node.value for node in app.body if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'nav_spec' for t in node.targets))
    routes = []
    for group, entries in zip(nav.keys, nav.values):
        for entry in entries.elts:
            key, function, title, icon, role, url = entry.elts
            routes.append({'group': ast.literal_eval(group), 'key': ast.literal_eval(key),
                           'function': function.id, 'title': ast.literal_eval(title),
                           'role': ast.literal_eval(role),
                           'path': ast.literal_eval(url) or ('' if function.id == 'page_studio' else function.id),
                           'live_readonly': 'pending', 'isolated_actions': 'pending'})
    files, widgets, errors = [], [], []
    paths = sorted(set((ROOT / 'src/web').rglob('*.py')) | {ROOT / 'src/scheduler/ui.py'})
    for path in paths:
        body = path.read_bytes()
        rel = path.relative_to(ROOT).as_posix()
        files.append({'file': rel, 'sha256': hashlib.sha256(body).hexdigest()})
        try:
            tree = ast.parse(body.decode('utf-8-sig'))
        except (SyntaxError, UnicodeError) as exc:
            errors.append({'file': rel, 'type': type(exc).__name__})
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in WIDGETS):
                continue
            label = ast.get_source_segment(body.decode('utf-8-sig'), node.args[0]) if node.args else ''
            widgets.append({'file': rel, 'line': node.lineno, 'kind': node.func.attr,
                            'label_source': (label or '')[:240],
                            'key_source': next((ast.unparse(k.value) for k in node.keywords if k.arg == 'key'), ''),
                            'coverage': 'unclassified'})
    return {'version': 1, 'method': 'static_ast_not_execution_or_blackbox',
            'routes': routes, 'source_files': files, 'widget_calls': widgets, 'parse_errors': errors}


if __name__ == '__main__':
    result = build()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'INVENTORY.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'routes': len(result['routes']), 'widget_calls': len(result['widget_calls']),
                      'source_files': len(result['source_files']), 'parse_errors': result['parse_errors']}))
