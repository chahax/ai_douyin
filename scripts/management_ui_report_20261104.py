"""Build a reviewable audit bundle from existing, non-sensitive evidence."""
import hashlib
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data/development_checkpoints/management_ui_audit_20261104'


def write(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    inventory = json.loads((OUT/'INVENTORY.json').read_text(encoding='utf-8'))
    observed = json.loads((OUT/'LIVE_ROUTE_OBSERVATIONS.json').read_text(encoding='utf-8'))['observations']
    report_path=ROOT/'data/qa/management_final_acceptance_20261105.xml'
    tests = ET.parse(report_path)
    primary_cases=list(tests.iter('testcase'))
    by_id={(t.get('classname'),t.get('name')):t for t in primary_cases}
    sources=[str(report_path.relative_to(ROOT)).replace('\\','/')]
    followup_path=ROOT/'data/qa/management_final_security_20261105.xml'
    followup_cases=[]
    if followup_path.exists():
        followup_cases=list(ET.parse(followup_path).iter('testcase'))
        by_id.update({(t.get('classname'),t.get('name')):t for t in followup_cases})
        sources.append(str(followup_path.relative_to(ROOT)).replace('\\','/'))
    cases=list(by_id.values())
    result = {'cases': len(cases), 'failed': sum(t.find('failure') is not None for t in cases),
              'errors': sum(t.find('error') is not None for t in cases),
              'skipped': sum(t.find('skipped') is not None for t in cases),
              'native_case_deselected': 1, 'sources':sources,
              'primary_cases':len(primary_cases),'followup_cases':len(followup_cases),
              'method':'unique test IDs; later followup supersedes overlapping primary cases'}
    if result['failed'] or result['errors']:
        raise SystemExit('Latest acceptance has failures; candidate manifest not refreshed')
    suites = {
        'accounts': ['account_manual_handling_ui','account_async_window_polling_integration','account_handling_button_integration','account_refresh_dashboard','manual_window_status','manual_boot_closure','management_account_scope_blackbox'],
        'fanqie_accounts': ['fanqie_account_control'], 'research': ['trend_dashboard'],
        'novel_adaptation': ['natural_director_entrypoints_v10','natural_director_panel_live_read_guard_v10'],
        'serial_story': ['serial_story_v2'], 'creative_v2': ['natural_director_entrypoints_v10'],
        'production': ['video_production_dashboard','h3_recovery_dashboard_20261104'],
        'upload_monitor': ['browser_control_upload_inspection','publication_scoped_popup_authorization'],
        'library': ['video_account_scope'], 'video_usage': ['seedance_dashboard'],
        'overview': ['content_performance','browser_control_compatibility_ui'],
        'comments': ['comment_workflow','video_account_scope'], 'replies': ['comment_workflow'],
        'schedule': ['management_scheduler_blackbox','account_refresh_dashboard','workflow_nodes'],
        'memory': ['management_memory_blackbox'], 'books': ['management_knowledge_blackbox'],
        'batch': ['fanqie_promotion_ledger'], 'workflow': ['workflow_dashboard','workflow_nodes'],
        'rules': ['management_policy_blackbox'], 'words': ['management_policy_blackbox'],
        'assistant': ['management_chat_blackbox'],
        'creative_history': ['management_tools_blackbox','novel_agent_entrypoints_v9'],
        'usage': ['management_tools_blackbox'], 'skills': ['management_tools_blackbox'],
        'users': ['management_admin_blackbox','auth_persistence'], 'settings': ['management_admin_blackbox'],
    }
    routes = []
    for route in inventory['routes']:
        path = route['path'] if route['path'] is not None else route['function']
        url = 'http://127.0.0.1:8501/'+path
        reads = [v for v in observed if v['url'] == url]
        attached = suites.get(route['key'], [])
        matched = [t for t in cases if t.get('classname') in {'tests.test_'+name for name in attached}]
        routes.append(dict(route=route['title'], url=url, minimum_role=route['role'],
            live_read=('known_dependency_error' if route['key']=='books' else
                       'initial_view_observed' if reads else 'role_not_available_in_live_session'),
            isolated_suites=attached, passing_attached_cases=sum(t.find('failure') is None and t.find('error') is None for t in matched),
            coverage='representative_cases_only; every widget/action combination is not certified',
            external_actions='not_executed_on_production'))
    write('COVERAGE.json', {'routes': routes, 'test_result': result,
        'static_widget_calls': len(inventory['widget_calls']), 'widgets_are_not_test_cases': True,
        'not_covered': ['native_browser_successful_startup/RPC','live_paid_model_or_media','live_publish/comment/interaction',
                        'live_account_resume','live_password_or_permission_changes','exhaustive_static_widget_combinations',
                        'all_page_keyboard_and_narrow_layouts; preview only checked at 390px',
                        'assistant_send/history_mutations not exercised on production; isolated widgets and SQLite covered',
                        'skill catalogue/settings are read-only; there is no installation control on this page']})
    findings = [
        ('manual_liveness','旧人工任务与过期探测被当成当前窗口','原owner、代次、绑定与心跳投影；旧探测撤出当前状态'),
        ('manual_preboot_closure','系统重启后旧人工记录阻塞入口','严格绑定原ID/请求SHA/开机证据的显式结清入口；不恢复账号'),
        ('exception_groups','同账号多条异常重复按钮、历史说明刷屏','按账号分组，一组窗口/继续入口，历史诊断折叠'),
        ('handling_copy','已核验/已关窗/必须关窗等提示互相矛盾','历史核验与当前运行分离；按原窗口状态给出动作'),
        ('unknown_states','读取失败、缺控制、未来/非法时间被当成正常','未知状态禁用操作，心跳和日期严格校验'),
        ('local_feedback','保存失败仍成功、刷新丢失提示、空白/坏正则通过','检查真实返回值、一次性反馈、输入/删除确认'),
        ('blocked_words_seed','删空违禁词后读取又补回默认词','只在首次新建词库时播种默认数据'),
        ('memory_privacy','部分记忆查询未按当前用户过滤，查看时创建会话','按用户关联查询；查看使用已有会话'),
        ('knowledge_dependency','知识库页面被可选TorchCodec依赖拖垮','页面惰性加载+版本检查；5.7.0官方包隔离导入检索成功'),
        ('knowledge_accounting','复制文件、部分导入和实际索引成功混淆','结构化写入回执；相同片段稳定ID复用；历史索引不擅删'),
        ('retriever_fallback','检索失败时忽略禁用远程模型开关','关闭fallback时不发起远程加载；本地文本嵌入使用CPU'),
        ('scheduler_view','查看调度页启动服务、停止按钮误称停掉Worker','取消查看副作用，按实际停止范围和返回值反馈'),
        ('browser_start_cleanup','启动超时清理先关阻塞管道，可能无限等待','捕获原进程家族并先回收；管道关闭有界'),
        ('page_boundary','读取失败留下半截操作表单或原始异常','清空失败区域，展示安全未知状态及重新读取入口'),
        ('provider_label','Ark被显示为BytePlus','按实际配置区分Ark/BytePlus/Dreamina/未知'),
        ('media_status','历史制作记录和技术收存被误当仍生成/质量完成','历史记录、技术收存、人工审片分别标注'),
        ('chat_plan_buttons','AI助手确认/取消按钮重绘后消失失效','原会话持久计划恢复；按钮绑定会话/计划SHA；唯一受理回执阻止重复与未知重放'),
        ('chat_session_actions','归档恢复引用缺失对象，删除缺少确认，缓存与会话不一致','用户归属事务和版本绑定；删除保留待确认/未知计划；取消不调用模型'),
        ('chat_permissions','查看者可发送模型请求和确认执行','查看角色只读会话；编辑及调用需要editor；读取页面不创建会话或受理表'),
        ('skill_runtime_scope','编辑者可读其他用户工具诊断，异常原文直接显示','编辑者仅本人记录；系统诊断仅admin；目录/存储失败不显示原始异常'),
        ('legacy_path_boundary','历史记录输入可访问项目授权目录外文件','历史目录限定data/creative_workflows，解析路径后校验归属'),
        ('usage_unknown_values','费用缺失被看成免费，缺失延迟拉低平均值','仅记录费用汇总并标未知条数；延迟/缓存比例使用已记录值'),
    ]
    write('FINDINGS.json', {'groups': [dict(id=k, problem=p, fix=f, state='candidate_fixed_and_regressed; deployment_pending') for k,p,f in findings],
        'known_remaining': ['生产依赖仍5.5.0，后台12796未重启；需最终部署授权',
            '原生浏览器隔离启动不可用；清理已证实45.05秒有界返回，不冒称启动成功',
            '线上账号选择曾出现重绘延迟；共享选择器隔离回归通过，需整包加载后复验',
            'account01原人工记录仍waiting_human，异常35和账号暂停保持；未代点结清或完成']})
    files = inventory['source_files'] + [{'file': str(p.relative_to(ROOT)).replace('\\','/'), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in [ROOT/'requirements.txt', *(ROOT/'src/operations_accounts'/name for name in
            ['manual_window_status.py','manual_boot_closure.py','browser_control.py','browser_control_runtime.py','manual_window_jobs.py']),
            ROOT/'src/platform_adapter/browser_session.py', ROOT/'src/services/database.py',
            ROOT/'src/memory/problem_memory.py', ROOT/'src/memory/humane_recorder.py',
            *(ROOT/'src/rag_engine'/name for name in ['knowledge_importer.py','knowledge_import_result.py','wisdom_retriever.py']),
            *(ROOT/'scripts'/name for name in ['management_ui_preview_20261104.py','management_ui_deploy_preflight_20261104.py',
                'management_ui_acceptance_snapshot_20261104.py','management_knowledge_smoke_20261104.py',
                'management_ui_report_20261104.py','deploy_management_ui_20261104.ps1'])]]
    test_paths=sorted({ROOT/(t.get('classname').replace('.','/')+'.py') for t in cases})
    test_files=[{'file':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in test_paths if p.is_file()]
    test_reports=[{'file':name,'sha256':hashlib.sha256((ROOT/name).read_bytes()).hexdigest()} for name in sources]
    write('SOURCE_MANIFEST.json', {'scope':'current workspace bytes; includes existing project work, not a clean Git checkout',
                                  'files':files,'test_files':test_files,'test_reports':test_reports})
    wheels = [dict(file=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
              for p in (ROOT/'data/qa/management_dependency_20261104').glob('*.whl')]
    write('PROGRESS.json', {'updated_at':time.time(), 'stage':'awaiting_single_final_deployment_approval',
        'goal_status':'active', 'test_result':result, 'routes_inventoried':len(routes), 'live_routes_observed':len({v['url'] for v in observed}),
        'production_deployed':False,'production_dependency_updated':False,'production_backend_pid':12796,
        'deployment_auto_review_rejected':True,'rejection_reason':'需要最终一次具体部署确认；生产依赖更新和后台重启有中断及回滚风险',
        'preview_url':'http://127.0.0.1:8513/', 'dependency_wheels':wheels,
        'no_business_dispatch_or_account_resume':True,'no_codex_timer_created':True,'h3_service_untouched':True})
    write('NATIVE_FINAL_INTERPRETATION.json', {'raw':'data/qa/management_native_after_cleanup_20261104/RESULT.json',
        'startup_status':'unavailable','error_type':'BrowserWorkerStartupTimeout','stage':'starting_driver',
        'startup_elapsed_seconds':45.05,'cleanup_verified':True,'production_browser_touched':False,
        'not_a_successful_native_RPC_test':True})
    print(json.dumps(result))


if __name__ == '__main__':
    main()
