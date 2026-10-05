"""Offline sidecar investigation. Never calls a provider or mutates production receipts."""
import json, hashlib, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

PROJECT = Path(__file__).resolve().parents[3]
QA = Path(__file__).resolve().parent
ROOT = PROJECT/'data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v4'

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(name, value):
    p=QA/name
    if p.exists(): raise RuntimeError('Investigation record already exists: '+name)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

baseline=read(PROJECT/'data/production_records/this_time_i_leave_s6_20261005/BASELINE_RECORD.json')
r=read(ROOT/'call_070_direction_s6_r2.json'); w=r['request']; ctx=json.loads(w['messages'][1]['content'])['context']
preflight=read(QA/'ORIGINAL_REQUEST_INPUT_PREFLIGHT.json')
assert digest(w)==r['request_sha256']==preflight['wire_sha256']
assert preflight['wire_exactly_reconstructed'] and preflight['inner_schema_exact_in_messages']
assert json.loads(w['messages'][2]['content'])['previous_direction_fault']==read(ROOT/'DIRECTION_INPUT_FOCUS_s6_r2_FINAL.json')
assert ctx['raw_linear_script']==read(PROJECT/'data/production_records/this_time_i_leave_s6_20261005/FULL_SCRIPT.json')
sdk=read(QA/'OFFLINE_EXPECTED_SDK_PARAMETERS.json'); body=read(QA/'EXPECTED_PROVIDER_BODY_NOT_SENT.json')
assert sdk['messages']==w['messages'] and sdk['model']==w['model']
assert sdk['max_completion_tokens']==8000 and sdk['extra_body']=={'thinking':{'type':'disabled'}}
assert sdk['tool_choice']=={'type':'function','function':{'name':'submit_creative_json'}}
assert sdk['tools'][0]['function']['parameters']==w['structured_schema']
assert body=={**{k:v for k,v in sdk.items() if k!='extra_body'},**sdk['extra_body']}
unchanged={n:sha(ROOT/n)==h for n,h in baseline['immutable_original_file_hashes'].items()}; assert all(unchanged.values())
ledger=read(ROOT/'CALL_LEDGER.json'); source_checks={n:sha(PROJECT/n)==h for n,h in ledger['source_manifest'].items()}; assert all(source_checks.values())
assert digest(ledger['source_manifest'])==r['source_binding_sha256']
known=[]; unknown=[]
for c in ledger['calls']:
    assert sha(ROOT/c['receipt'])==c['receipt_sha256']
    receipt=read(ROOT/c['receipt']); usage=receipt.get('response_metadata',{}).get('total_tokens')
    if type(usage) is int and usage>=0: known.append(usage)
    else: unknown.append(c)
assert len(known)==7 and [x['ordinal'] for x in unknown]==[70]
spend={'effective_calls_started':70,'calls_with_known_usage':69,'effective_reported_tokens':620826+sum(known),'unknown_token_reservations':sum(x['token_reservation'] for x in unknown),'max_total_tokens':None,'old_budget_reset':False,'media_calls':0}
assert spend['effective_reported_tokens']==709272 and spend['unknown_token_reservations']==64010
proc=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*run_creative_resume_v4.py*' }).Count"],capture_output=True,text=True,check=True)
process_count=int(proc.stdout.strip())
log=PROJECT/'data/logs/agent.log'; log_stats={'path':str(log),'exists':log.exists()}
if log.exists():
    text=log.read_text(encoding='utf-8',errors='replace')
    log_stats.update(bytes=log.stat().st_size,lines=len(text.splitlines()),request_sha256_match_count=text.count(r['request_sha256']),stage_label_match_count=text.count(r['label']))
now=datetime.now(timezone.utc); bjt=timezone(timedelta(hours=8)); started=datetime.fromisoformat(r['started_at'])
windows=[]
for bi,beat in enumerate(ctx['raw_linear_script']['beats']):
    if beat['id'] in ['B02','B04','B05','B06','B07','B08','B09']:
        windows.append({'beat_id':beat['id'],'source_steps':[{'ref':f'raw_linear_script.beats.{bi}.steps.{i}','original_step':s} for i,s in enumerate(beat['steps'])],'actual_start_seconds':None,'actual_end_seconds':None})
save('PERFORMANCE_SOURCE_TARGETS_NOT_A_PLAN.json',{'schema':'source_targets_for_pending_director/v1','status':'input_audit_only_not_director_or_local_output','raw_script_sha256':digest(ctx['raw_linear_script']),'items':windows,'critical_requirements':['B02完整长对白须按局部真实安排核对，不以82秒整片估算放行','B04拒绝前目光变化可读；B05同一完整对白during窗口；B06拒绝后独立after反应','B07停住、比对、划掉重写及B08携票真正离场须可读','每镜新增信息/观察对象/切镜理由，不按每个拿放操作拆镜','便利贴所有权与持有分开，持笔连续来源不擅加放开再拿起'],'timing_contract':'during仅同一完整dialogue；跨镜只after；普通action由step_units串行安排','actual_duration_seconds':None,'director_adopted':False,'local_performance_complete':False})
audit={'schema':'unknown_original_text_call_reconciliation_audit/v1','checked_at_utc':now.isoformat(),'checked_at_beijing':now.astimezone(bjt).isoformat(),'user_instruction':'核实原请求，再完成导演与实际表演窗口','original_receipt':{'path':str(ROOT/'call_070_direction_s6_r2.json'),'sha256':sha(ROOT/'call_070_direction_s6_r2.json'),'ordinal':70,'label':r['label'],'started_at_utc':r['started_at'],'started_at_beijing':started.astimezone(bjt).isoformat(),'request_sha256':r['request_sha256'],'source_binding_sha256':r['source_binding_sha256'],'unchanged_status':r['status'],'response_id':None,'response_or_usage_saved':False,'token_reservation':64010},'verified_request_configuration':{'provider':'minimax','base_url':'https://api.minimaxi.com/v1','endpoint':'POST /chat/completions','model':'MiniMax-M3','max_completion_tokens':8000,'temperature':0.4,'thinking':{'type':'disabled'},'named_tool':'submit_creative_json','tool_choice_forced':True,'timeout_seconds':600,'sdk_max_retries':0,'request_messages':5,'sdk_capture_fake_calls':1,'sdk_capture_real_provider_calls':0,'provider_received_request_verified':False},'local_recovery_evidence':{'matching_original_python_processes':process_count,'agent_log':log_stats,'original_tool_session_id':91043,'original_tool_session_observed_error':'Unknown process id 91043','no_original_receipt_response_id':True,'original_local_files_unchanged':unchanged,'source_files_verified':len(source_checks)},'public_documentation_review':{'text_api':'https://platform.minimax.io/docs/api-reference/text-chat-openai','api_index':'https://platform.minimax.io/docs/llms.txt','account_faq':'https://platform.minimax.cn/docs/faq/about-account','console_billing_page':'https://platform.minimax.cn/console/recharge-records','limited_finding':'已查公开文档中未找到同步文本历史结果恢复接口，不据此断言服务方不存在内部查询能力','no_undocumented_authenticated_endpoints_probed':True},'console_access':{'completed':False,'cua_get_state_failure':'trusted Node process exited unexpectedly; kernel reset','computer_use_init_failure':'windows sandbox failed: helper_unknown_error: apply deny-read ACLs; kernel exited unexpectedly','reason_type':'tool_initialization_failure_not_approval_rejection','authentication_data_read':False,'security_settings_changed':False,'required_manual_lookup_question_already_sent':True},'confirmed_facts':['冻结代码重构请求全等；完整S6/R01/最终r2反馈/内部Schema在本地messages中','本地无可恢复原响应或请求ID；原进程不存在','原服务结果、是否计费和真实用量仍未知'],'unverified_inferences':['最初进程消失观察时间接近600秒超时，不能证明发生SDK超时、服务故障或进程中断','pending_response在客户端构造和网络调用前写入，不能单独证明服务收到请求'],'required_reconciliation_evidence':['匹配原时间/模型/配置的服务请求或响应身份','原调用结果及真实用量','成功时完整原响应；无法恢复时可核实服务方对账证据和具体恢复决策'],'current_dispatch_decision':'blocked_original_outcome_and_usage_unknown','automatic_retry':False,'reservation_released':False,'budget_reset':False,'receipt_or_ledger_mutated':False,'new_provider_calls':0,'new_media_calls':0,'spend':spend,'director_adopted':False,'local_performance_complete':False,'production_handoff_complete':False}
save('RECONCILIATION_AUDIT.json',audit)
md=f'''# 第70次原导演请求核查

核查时间：{now.astimezone(bjt).isoformat()}。这是原请求对账证据，不是导演计划或制作交接。

## 已核实

原调用时间：{started.astimezone(bjt).isoformat()}；MiniMax-M3；8000输出上限；温度0.4；thinking disabled；指定submit_creative_json工具；客户端600秒超时、max_retries=0。

冻结代码重构请求与原回执全等，SHA：{r['request_sha256']}。完整S6九拍、R01全文、最终r2反馈及内部Schema均在本地messages中。

原响应/服务请求ID/真实用量未保存。当前原Python进程数量{process_count}；本地agent.log没有恢复原结果。所有原run文件和144个代码绑定保持SHA。累计70次启动、69次用量已知、709272 reported tokens；64010未知预留不是实耗。本次真实模型/媒体调用均0。

## 尚未知

服务端是否收到、完成或计费仍未知。SDK离线捕获只证明代码构造请求，不能证明服务收到请求。

最初进程消失观察时间接近600秒超时只是线索，不能证明SDK超时、服务故障或进程中断。历史长分析服务端原因也没有因此查明。

[公开文本文档](https://platform.minimax.io/docs/api-reference/text-chat-openai)与[API索引](https://platform.minimax.io/docs/llms.txt)中未找到同步文本历史结果查询入口；这是本次检索范围内的结果，不证明内部查询不存在。

## 控制台核对受阻

浏览器工具初始化两次失败；computer-use初始化报Windows sandbox apply deny-read ACLs错误。未进入控制台；这是工具初始化故障，不是自动批准审查拒绝。没有读取凭据或更改安全设置。已向用户一次性请求03:03:43前后原MiniMax-M3调用的服务ID、结果、用量和原响应，同一问题保持待答。

## 导演与实际表演窗口

[原请求输入核对](ORIGINAL_REQUEST_INPUT_PREFLIGHT.json)确认全文、参考、反馈与Schema全等。[表演所需源步骤](PERFORMANCE_SOURCE_TARGETS_NOT_A_PLAN.json)仅列原稿来源，实际起止秒数仍为null。

拒绝前的方澄目光、完整拒绝句、听完后的林屿独立反应、对账困难与比对重写、携票真正离场是后续必须兑现的内容。故事保持真实克制、释放可见，没有新增第三角色、手机或奖励式翻转。

未采用call69失败导演稿，未手改正文或拼接方案。call70无法采用；整片导演、局部表演、确定性编译和制作交接均尚未完成，不能称创作质量通过。

## 继续条件

恢复原响应和真实用量，或得到能匹配原调用的服务方对账证据，再走保留原记录的显式恢复。不能重发原请求、换目录绕过未知结果、清预留或改冻结哈希。

[核查详情](RECONCILIATION_AUDIT.json)、[SDK离线参数](OFFLINE_EXPECTED_SDK_PARAMETERS.json)、[预计服务请求正文——未发送](EXPECTED_PROVIDER_BODY_NOT_SENT.json)。
'''
(QA/'RECONCILIATION_STATUS.md').write_text(md,encoding='utf-8')
p=PROJECT/'data/task_progress_monitor/creative_progress_state.json';progress=read(p);save('PROGRESS_VIEW_BEFORE_RECONCILIATION.json',progress)
progress.update(updated_at_utc=now.isoformat(),actual_latest_call=70,latest_call=70,latest_story_direction='call64 story_plan_r10 adopted for complete script only',last_completed_semantic_review=68,latest_independent_semantic_review=str(ROOT/'SOURCE_SEMANTIC_VERIFICATION_s6_call68.json'),latest_review='call68 complete source-bound script review valid; adopted for direction only',pending_calls=[70],unknown_usage_calls=[70],spend_snapshot=spend,content_review_artifact=str(PROJECT/'data/production_records/this_time_i_leave_s6_20261005/FULL_SCRIPT.md'),next_step='原70结果及真实用量对账后，采用或完整返修导演，逐镜生成实际表演窗口并确定性编译与全文复审',latest_reconciliation_audit=str(QA/'RECONCILIATION_AUDIT.json'),console_recovery_tool_blocked=True,required_user_lookup_pending=True,last_periodic_visible_summary_utc='2026-10-05T04:03:49Z',last_periodic_visible_summary_beijing='2026-10-05 12:03',user_quality_confirmation=None)
progress['unresolved']=['原70结果/真实用量未知，所有新模型派发阻止','无有效整片导演/实际局部窗口/编译/交接','B02真实对白时间及拒绝前中后/听者反应未实际验收','历史长分析服务端原因与心跳延后原因未查明']
progress['latest_git_backup']={'branch':'codex/backup-ai-creative-20261003','commit':'0e26aa852436465b009e0d0e1af285c42583f8f3','remote_verified':True,'scope':'S6剧本、144代码绑定和制作文档；本次核查尚未备份'}
progress['last_progress_check']={'at_utc':now.isoformat(),'latest_actual_call':70,'effective_reported_tokens':709272,'new_provider_calls':0,'full_text_handoff_available':False,'frozen_records_modified':False}
p.write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for target in ['docs/THIS_TIME_I_LEAVE_S6_PRODUCTION_RECORD_20261005.md','docs/CREATIVE_TEXT_CONTINUATION_20261004.md']:
    with (PROJECT/target).open('a',encoding='utf-8') as f:
        f.write(f'\n\n## 2026-10-05 原70请求继续核查\n\n{now.astimezone(bjt).isoformat()}：按用户“核实原请求，再完成导演与实际表演窗口”执行。冻结代码重构原请求全等，S6全文/R01全文/最终r2反馈与Schema均已进入本地messages；离线SDK捕获确认M3、8000上限、disabled thinking、指定工具、600秒超时和0重试。不能据此证明服务收到请求。\n\n原70仍无响应ID/结果/真实用量。进程与日志未恢复结果；浏览器和computer-use初始化失败，未进入控制台。原服务记录问题待答，不重发、不清64010预留、不改原回执或账本。累计70次启动、69次用量已知、709272 reported tokens；本次真实模型/媒体调用0。\n\n[核查结果与继续条件](../data/qa/call70_reconciliation_20261005/RECONCILIATION_STATUS.md)。实际导演/表演窗口/编译/交接尚未完成，S6故事与结尾保持。北京时间12:03已在会话输出可见30分钟内容与进度核对。\n')
assert all(sha(ROOT/n)==h for n,h in baseline['immutable_original_file_hashes'].items())
save('VALIDATION.json',{'schema':'reconciliation_documentation_offline_validation/v1','all_original_run_files_unchanged':True,'original_run_files_checked':len(unchanged),'frozen_source_files_verified':len(source_checks),'wire_reconstruction_exact':True,'full_reference_and_feedback_exact':True,'sdk_capture_matches_wire':True,'source_script_unchanged':True,'initial_documentation_attempt_error':'QA source-target projection used beat_id instead of raw id; corrected before audit/production-view writes; original source untouched','new_provider_calls':0,'new_media_calls':0,'budget_reset':False,'production_quality_passed':False,'director_and_performance_complete':False})
print(json.dumps({'saved':str(QA),'wire_exact':True,'original_files_unchanged':len(unchanged),'code_files_unchanged':len(source_checks),'actual_calls':0,'original_result_recovered':False,'director_or_windows_complete':False},ensure_ascii=False))
