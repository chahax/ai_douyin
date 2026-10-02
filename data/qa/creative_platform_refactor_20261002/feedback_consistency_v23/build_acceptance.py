"""Build F01 acceptance from final release-bound tests and retained receipts."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import ast,hashlib,html,json,shutil,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def suite(path):
 cases=ET.parse(path).findall('.//testcase')
 failed=[x for x in cases if x.find('failure') is not None or x.find('error') is not None]
 skipped=[x for x in cases if x.find('skipped') is not None]
 return {'xml':path.name,'total':len(cases),'passed':len(cases)-len(failed)-len(skipped),'failed':len(failed),'skipped':len(skipped)},cases
final=[];cases=[]
for group in ('core_final','ui_final'):
 row,items=suite(OUT/(group+'_tests.xml'));assert row['failed']==row['skipped']==0,row
 row['log']=group+'_tests.log';final.append(row);cases.extend(items)
ids={(x.get('classname'),x.get('name')) for x in cases};assert len(ids)==len(cases)
new=[x for x in cases if 'test_creative_feedback_consistency' in x.get('classname','')];assert len(new)==17
integ=read(OUT/'integrity_checks.json');pack=ROOT/integ['packs']['v23']['directory']
for row in read(pack/'runtime_sources.json')['sources']:assert sha(ROOT/row['path'])==row['sha256']
for label,row in integ['packs'].items():
 folder=ROOT/row['directory'];assert sha(folder/'artifact_manifest.json')==row['manifest_sha256']
 for item in read(folder/'artifact_manifest.json')['artifacts']:assert sha(folder/item['path'])==item['sha256']
contract=read(pack/'platform_refactor_contract.json')
assert sha(ROOT/contract['source_direction_report'])==contract['direction_report_sha256']
assert sha(ROOT/contract['source_implementation_review'])==contract['implementation_review_sha256']
names=[n.name for n in ast.walk(ast.parse((ROOT/'tests/test_creative_feedback_consistency.py').read_text(encoding='utf-8'))) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
chain=[]
for folder in (OUT/'core_final_tmp').iterdir():
 if folder.is_dir() and any(folder.name.startswith(n[:29]) for n in names):
  chain.extend({'path':p.relative_to(OUT).as_posix(),'sha256':sha(p)} for p in folder.rglob('*') if p.is_file())
assert chain
write(OUT/'execution_chain_manifest.json',{'schema':'creative_v23_execution_evidence/v1','provider':'explicit fake provider fixtures at production entry','files':chain})
for rel in ('tests/test_creative_feedback_consistency.py','tests/test_creative_stage_debug.py','tests/test_creative_workflow_ui.py','tests/test_creative_remaining_refactor.py','tests/test_creative_governed_protocol.py','scripts/version_creative_governance_runtime.py'):
 dest=OUT/'source_snapshot'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
 if dest.exists():assert sha(dest)==sha(ROOT/rel)
 else:shutil.copyfile(ROOT/rel,dest)
assert (OUT.parent/'implementation_review_v22/test_inflight_feedback_contract.py').read_bytes()==(OUT/'fixed/test_inflight_feedback_contract.py').read_bytes()
baseline=read(OUT/'baseline/inflight_feedback_probe.json');fixed=read(OUT/'fixed/inflight_feedback_probe.json')
assert not baseline['feedback_present_after_call'] and baseline['downstream_calls_after_lost_feedback']==1
assert fixed['feedback_present_after_call'] and fixed['pending_feedback_count']==1 and fixed['downstream_calls_after_lost_feedback']==0 and fixed['upstream_repair_calls']==1
attempts=[suite(p)[0] for p in sorted(OUT.glob('*_tests.xml')) if p.name not in {r['xml'] for r in final}]
pending=[('F02','P2','文本派发输入预览与分段准备、批准原尾续段、合成、整片审核页面'),('F03','P2','可审计执行锁诊断、对账、恢复及旧环境恢复工具'),('F04','P2','进一步分离预算、调用、校验和返修编排'),('F05','P2','显式字段来源与逐次修改重建原因'),('F06','P3','真实人工返修与质量试点、冻结留出和三轮评估'),('F07','P3/P4','授权实际服务、媒体格式与浏览器发布验收')]
assert len(read(pack/'dataset_manifest.json')['cases'])==28
result={'schema':'creative_feedback_v23_acceptance/v1','created_at_bjt':datetime.now(timezone(timedelta(hours=8))).isoformat(),'verdict':'F01_P1_passed_offline_production_entry; F02_F07_pending',
 'direction_source':contract['source_direction_report'],'checklist_source':contract['source_implementation_review'],
 'tests':{'final_groups':final,'distinct_final_passed':len(ids),'failed':0,'skipped':0,'new_concurrency_boundary_cases':17,'independent_original_assertions_unchanged':True},
 'baseline':baseline,'fixed_probe':fixed,'prior_attempts':attempts,'integrity':integ,
 'actual_entry_evidence':{'new_boundary_cases':17,'receipt_files':len(chain),'manifest':'execution_chain_manifest.json','network_blocked':True,'remote_paid_calls':0},
 'probe_adaptation':'Original assertion file byte-identical. Correct repair calls director_brief, whereas original continuation only returned director_shots fixture. Fixed probe first asserts director_shots blocked with zero calls, then supplies director_brief repair fixture and stops there; no assertions weakened.',
 'changes':['shared short state lock, monotonic state_revision, no-op preserves bytes','immutable ordered commands, atomic publication and idempotent recovery','runner, control, assistant review and media submission share command replay','only input-consumed feedback IDs resolved; late feedback retains original binding and repair-base rebase','provider gate blocks unresolved feedback; confirmed pre-dispatch rejection differs from unknown remote result','budget, tokens, adopted history and original-ID query preserved'],
 'pending':[{'id':a,'priority':b,'direction':c,'status':'pending'} for a,b,c in pending],
 'quality':{'candidates':28,'human_gold':0,'qualified_holdout':0,'improvement_verified':False},
 'media_policy':{'assistant_content_review_performed':False,'generated_content_status':'awaiting_human_review','real_media_generated':False,'real_browser_publish_performed':False},
 'historical_real_receipt_excluded':{'path':'tests/test_creative_real_receipt_replay.py','counted_as_passed':False,'rerun_this_round':False,'prior_evidence':'../p1_closure_v21/legacy_replay_comparison.json','reason':'Same v20/v21 strict prompt mismatch at writer_revise__preflight_story_00_01; calls_started=30, zero new calls. Original receipts unchanged.'},
 'prior_failure_explanation':['baseline original feedback loss reproduced','candidate03 no-op revision and legacy tamper error behavior fixed; one unchanged UI case hit 15s timeout and final full UI runs isolated','candidate06: 754 passed, one new assertion wrongly expected old assistant review synchronizable after handoff reopened. New test verifies original gate rejects and bytes/feedback/budget unchanged; original gate not relaxed','candidate04 interrupted partial attempt not counted']}
write(OUT/'acceptance.json',result)
rows=''.join('<tr><td>'+a+'</td><td>'+b+'</td><td>'+html.escape(c)+'</td><td>待办</td></tr>' for a,b,c in pending)
body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>v23 F01 反馈一致性验收</title><style>body{{font:16px/1.7 system-ui;background:#f5f6fa;color:#202633;margin:0}}main{{max-width:1050px;margin:32px auto;padding:32px;background:white}}h1{{font-size:29px}}h2{{font-size:21px;margin-top:28px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #d9deea;padding:9px;text-align:left}}a{{color:#235dc2}}.pass{{color:#117442}}</style><main>
<h1>v23：运行中反馈一致性验收</h1><p class="pass">F01 / P1 已通过离线实际执行链验收。正式默认 v23 绑定：{len(ids)} 个不同用例通过，0 失败，0 跳过；其中新增并发边界 17 项。F02–F07 保持待办。</p><p>依据<a href="../direction_report.html">方向报告</a>和<a href="../implementation_review_v22/review_report.html">v22 独立复核清单</a>。本轮未调用真实付费服务或发布作品。</p>
<h2>独立复现与修复后对照</h2><table><tr><th>结果</th><th>v22 基线</th><th>v23</th></tr><tr><td>调用期间反馈存在</td><td>是</td><td>是</td></tr><tr><td>调用返回保存后反馈存在</td><td>否</td><td>是</td></tr><tr><td>未修复反馈数</td><td>0（丢失）</td><td>1</td></tr><tr><td>返修前下游调用</td><td>1</td><td>0</td></tr><tr><td>恢复责任阶段</td><td>director_shots</td><td>director_brief，1 次返修</td></tr></table><p><a href="baseline/inflight_feedback_probe.json">原缺陷复现</a> / <a href="fixed/inflight_feedback_probe.json">修复后链路</a> / <a href="fixed/feedback_state_during_call.json">调用期间状态</a> / <a href="fixed/feedback_state_after_call.json">返回状态</a> / <a href="fixed/feedback_state_after_continuation.json">返修恢复状态</a></p><p>独立复核原断言文件完全保留。原继续执行夹具只提供下游 director_shots 回答；正确修复后应先调用 director_brief。因此仅调整继续执行夹具：先验证下游阻断且调用为 0，再提供责任阶段返修回答并停在该阶段。未删除或放宽原断言。</p>
<h2>实现与验收范围</h2><p>反馈、停止/恢复、助手文本复核和 runner 使用同一短状态提交锁，锁不跨模型等待。不可变回执和有序命令保留用户意图；旧 runner 保存时重放命令。版本仅在状态变化时递增，无变化保存不改文件。命令原子发布，中断后从完整回执恢复。</p><p>派发前复核已接受命令；在途结果可保留，但未修反馈持续阻断下游。只有请求输入实际消费的反馈 ID 可以解决，返修中新增反馈仍待修，保留原绑定并追加返修基准。旧交接重开后，旧助手复核被交接门禁拒绝。</p><p>确认未派发与远程结果未知分开留痕。调用预留、token、失败预算和历史不删除、不重置。新文本反馈阻断媒体提交，原任务 ID 查询仍可进行。操作系统短提交锁强退后释放已有回归；F03 执行锁恢复工具仍待开发。</p><p><a href="core_final_tests.xml">正式核心 JUnit</a>（{final[0]['passed']} 项） / <a href="core_final_tests.log">核心日志</a> / <a href="ui_final_tests.xml">完整页面 JUnit</a>（{final[1]['passed']} 项） / <a href="ui_final_tests.log">页面日志</a> / <a href="targeted_tests.xml">候选 83 项定向回归</a></p><p>新增 17 项覆盖双并发反馈、停止/反馈顺序、同阶段连续两轮、回执/命令/状态提交前后崩溃、解决消费证明、预留后门禁、实际多进程及强退、交接重开、媒体提交阻断、无变化保存、旧反馈兼容、旧助手复核拒绝和发布中断。已有多阶段连续两轮与预算历史回归也在最终集合。服务返回和人工批准均为明确测试夹具。</p><p>保留 {len(chain)} 份新边界执行文件：<a href="execution_chain_manifest.json">回执哈希清单</a>；<a href="source_snapshot">源码和测试快照</a>。</p>
<h2>冻结与历史</h2><p><a href="../../../creative_governance/20261002_v23_feedback_consistency/artifact_manifest.json">v23 冻结包</a>：55 项产物，53 份运行文件，49 份 Python 语法核验。<a href="integrity_checks.json">完整性核验</a>确认 v18–v22 原包均未改，受测候选运行源码等于正式包，规则和数据集未改。</p><p>默认新治理任务绑定 v23。旧任务不静默迁移，同意图保持原目录和累计预算。旧 v22 绑定在新环境于模型调用前拒绝，状态原样保留。本轮未改绑真实任务或重领额度。<a href="../../../../docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md">当前实现文档</a>及调试说明已同步，v22 文档另存归档。</p>
<h2>未完成方向</h2><table><tr><th>编号</th><th>优先级</th><th>工作</th><th>状态</th></tr>{rows}</table><p>数据仍为 28 候选、0 人工金标、0 合格留出，未宣称真实质量提升。真实服务、媒体格式与浏览器发布未验收。视频内容继续由用户审查，接口成功仅记 awaiting_human_review。</p>
<h2>保留失败与限制</h2><p>所有中间失败日志保留，不计最终通过。候选第三轮 748 通过、4 失败：无变化版本号与旧篡改错误报告已修正，原页面用例触及 15 秒超时；最终完整页面集合独立进程执行，没有延长超时、跳过或削弱断言。候选第六轮 754 通过、1 个新用例误期望旧助手复核仍能同步；现验证原门禁拒绝并保持状态、反馈、预算不变。候选第四轮中断部分不计验收。</p><p>test_creative_real_receipt_replay.py 未在本轮运行或计通过。此前 v20/v21 同样拒绝 writer_revise__preflight_story_00_01 提示绑定，calls_started=30、新调用=0；<a href="../p1_closure_v21/legacy_replay_comparison.json">既有证据</a>与历史回执保留。</p><p><a href="acceptance.json">机器可读验收</a> / <a href="evidence_manifest.json">证据哈希</a> / <a href="run_acceptance.py">断网验收入口</a> / <a href="build_acceptance.py">报告生成入口</a></p></main></html>'''
(OUT/'acceptance_report.html').write_text(body,encoding='utf-8')
paths=[p for p in OUT.iterdir() if p.is_file() and p.suffix in ('.json','.xml','.log','.py','.html') and p.name!='evidence_manifest.json']
for name in ('baseline','fixed','baseline_source','source_snapshot'):
 paths.extend(p for p in (OUT/name).rglob('*') if p.is_file() and p.suffix in ('.json','.py','.md','.html','.xml','.log'))
write(OUT/'evidence_manifest.json',{'schema':'creative_v23_evidence_manifest/v1','files':[{'path':p.relative_to(OUT).as_posix(),'sha256':sha(p)} for p in sorted(set(paths))],'execution_chain_manifest':'execution_chain_manifest.json'})
print(json.dumps({'distinct_final_passed':len(ids),'new_boundary_cases':len(new),'receipt_files':len(chain),'F01':'passed','F02_F07':'pending'}))
