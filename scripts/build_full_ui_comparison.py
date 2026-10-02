"""Publish only screenshot artifacts, never preview databases or credentials."""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/ui_style_baselines/full_comparison_20260906'
PAGES = [
    ('login', '登录页', '/', '/', '入口'),
    ('home', '创作工作台', None, '/', '创作空间'),
    ('research', '热门选题', '/page_trend_operations', '/page_trend_operations', '创作空间'),
    ('production', '视频制作', None, '/video-production', '创作空间'),
    ('assistant', 'AI 助手', '/', '/page_chat', '创作空间'),
    ('library', '作品库 / 视频', '/page_videos', '/page_videos', '内容运营'),
    ('overview', '运营看板', '/page_dashboard', '/page_dashboard', '内容运营'),
    ('comments', '评论管理', '/page_comments', '/page_comments', '内容运营'),
    ('replies', '回复建议 / 自动回复', '/page_auto_reply', '/page_auto_reply', '内容运营'),
    ('schedule', '任务调度', '/page_scheduler', '/page_scheduler', '内容运营'),
    ('memory', '我的记忆', '/page_memory', '/page_memory', '资源与工具'),
    ('books', '知识库', '/page_books', '/page_books', '资源与工具'),
    ('batch', '批量抓取', '/page_fanqie_batch_queue', '/page_fanqie_batch_queue', '资源与工具'),
    ('usage', 'LLM 用量', '/page_llm_usage', '/page_llm_usage', '资源与工具'),
    ('skills', 'Skill 监控', '/page_skill_monitor', '/page_skill_monitor', '资源与工具'),
    ('workflow', '工作流节点', '/page_workflow_nodes', '/page_workflow_nodes', '资源与工具'),
    ('rules', '规则管理', '/page_rules', '/page_rules', '管理设置'),
    ('words', '违禁词', '/page_blocked_words', '/page_blocked_words', '管理设置'),
    ('users', '用户管理', '/page_users', '/page_users', '管理设置'),
    ('settings', '系统设置', '/page_settings', '/page_settings', '管理设置'),
]


def main():
    public = BASE / 'gallery'
    (public / 'screenshots').mkdir(parents=True, exist_ok=True)
    audit_path = BASE / 'page-capture-status.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else {}
    rows = []
    for identity, title, old, new, group in PAGES:
        item = dict(id=identity, title=title, group=group)
        for version, route in [('old', old), ('new', new)]:
            name = f'{identity}-{version}.png'
            source = BASE / 'screenshots' / name
            status = audit.get(f'{identity}-{version}', {})
            state = '旧版无此页面（新增）' if route is None else status.get('status', '等待登录后采集')
            if source.exists():
                shutil.copy2(source, public / 'screenshots' / name)
                state = status.get('status', '已截取真实页面')
            item[version] = dict(route=route, status=state, image='screenshots/' + name if source.exists() else None,
                                 note=status.get('note', ''))
        rows.append(item)
    data = dict(legacy='2c0d8d5 · 2026-09-01', current='2026-09-06 工作树快照', viewport='1440 × 1000 CSS px · 全页截图', pages=rows)
    (public / 'pages.js').write_text('window.COMPARISON = ' + json.dumps(data, ensure_ascii=False, indent=2) + ';', encoding='utf-8')
    (public / 'page-inventory.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(BASE / 'all-pages-comparison.zip', 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in public.rglob('*'):
            if path.is_file():
                bundle.write(path, path.relative_to(public))
    print(json.dumps({'pages': len(rows), 'captured': sum(bool(p[v]['image']) for p in rows for v in ['old', 'new'])}))


if __name__ == '__main__':
    main()
