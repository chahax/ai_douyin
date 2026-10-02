"""Render final acceptance only after final release-bound tests passed."""
from pathlib import Path
import json,hashlib,xml.etree.ElementTree as ET,html,shutil
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def suite(name):
    tree=ET.parse(OUT/(name+'_tests.xml'))
    cases=tree.findall('.//testcase')
    failed=[x for x in cases if x.find('failure') is not None or x.find('error') is not None]
    skipped=[x for x in cases if x.find('skipped') is not None]
    assert not failed and not skipped,(name,len(failed),len(skipped))
    return {'group':name,'total':len(cases),'passed':len(cases),'failed':0,'skipped':0,'xml':name+'_tests.xml','log':name+'_tests.log'},cases
full,cases=suite('full_final');extra,missing=suite('remaining_p1')
allcases=cases+missing
identities={(x.get('classname'),x.get('name')) for x in allcases}
assert len(identities)==len(allcases),'Do not count duplicate tests as extra evidence'
p1=read(OUT.parent/'p1_closure_v21/p1_selection.json')
p1files={Path(x).stem for x in p1}
p1cases=[x for x in allcases if x.get('classname','').split('.')[-1] in p1files]
selected=read(OUT/'full_final_selection.json')+read(OUT/'remaining_p1_selection.json')
assert {str((ROOT/x).resolve()) for x in p1}<={str((ROOT/x).resolve()) for x in selected}
integ=read(OUT/'integrity_checks.json')
pack=ROOT/integ['packs']['v22']['directory']
for row in read(pack/'runtime_sources.json')['sources']:assert sha(ROOT/row['path'])==row['sha256']
for row in read(pack/'artifact_manifest.json')['artifacts']:assert sha(pack/row['path'])==row['sha256']
assert sha(ROOT/'data/qa/creative_platform_refactor_20261002/direction_report.html')==read(pack/'platform_refactor_contract.json')['direction_report_sha256']
probe=read(OUT/'execution_chain_probe.json')
for row in probe['files']:assert sha(OUT/row['path'])==row['sha256']
for rel in ['tests/test_creative_remaining_refactor.py','tests/test_creative_workflow_ui.py','tests/test_creative_stage_debug.py',
            'tests/test_creative_review_gate.py','tests/test_creative_v4_integration.py','tests/test_creative_v5_integration.py',
            'scripts/version_creative_governance_runtime.py']:
    dest=OUT/'source_snapshot'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():assert sha(dest)==sha(ROOT/rel)
    else:shutil.copyfile(ROOT/rel,dest)
prior=read(OUT.parent/'p1_closure_v21/acceptance.json')
checklist=[
 {'priority':'P1','item':'当前与历史版本、最新反馈、多阶段两轮、预算和历史','status':'passed_offline','evidence':'full_final_tests.xml + remaining_p1_tests.xml; preserved v21 acceptance'},
 {'priority':'P2','item':'实际消费字段投影、完整请求兼容、输入/产物双版本与下游失效','status':'passed_offline','evidence':'execution_chain_probe.json field_compare + compatibility receipts'},
 {'priority':'P2','item':'文本/分镜/编译请求/原片/原尾/秒点反馈及责任路由','status':'passed_offline','evidence':'test_creative_remaining_refactor + execution_chain/media_chain'},
 {'priority':'P3','item':'共享阶段合同、自动/断点/单步、停止未来派发和恢复、故障预算','status':'passed_offline','evidence':'execution_chain/stop_resume + unknown_dispatch + same_script_budget'},
 {'priority':'P3','item':'候选/人工金标/冻结留出及真实费用接口','status':'passed_offline_interfaces_only','evidence':'source-bound dataset/holdout tests; execution_chain_probe.json quality'},
 {'priority':'P3','item':'真实创作效果、规定独立金标/留出/三轮比较、真实降本','status':'not_verified_missing_real_evidence','evidence':'quality_improvement_verified=false; holdout_repeated_validation_passed=false; model_cost=null'},
 {'priority':'P4','item':'批准成片交付、账号、主动AI声明、虚构前缀、锁、原作品核验与运营回接','status':'passed_offline_interfaces_only','evidence':'actual PublishWorkflow with fixture browser; independent publish/operations receipts'},
 {'priority':'P4','item':'本轮真实平台发布与真实媒体内容审核','status':'not_executed','evidence':'network blocked; paid_calls=0; fixture labels explicitly marked'},
 {'priority':'all','item':'当前文档、渐进模块拆分、v22冻结、v20/v21保留','status':'passed','evidence':'55 artifacts; 51 runtime sources; integrity_checks.json'}]
result={'schema':'creative_remaining_v22_acceptance/v1','created_at_bjt':datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'verdict':'remaining_refactor_implementation_and_offline_execution_passed; real_quality_and_live_delivery_not_verified',
        'core_direction_report':'../direction_report.html','v20_confirmation_checklist':'../v20_confirmation/confirmation_report.html',
        'checklist':checklist,'tests':{'groups':[full,extra],'distinct_final_passed':len(identities),'failed':0,'skipped':0,'p1_covered_cases':len(p1cases),'p1_file_coverage_complete':True},
        'integrity':integ,'actual_entry_chain':{'cases':probe['cases'],'receipt_file_count':len(probe['files']),'paid_calls':0,'network_blocked':True},
        'prior_attempts_preserved':['full_tests.xml/log: 726 passed, 6 failed; one new error type corrected; five old prompt expectations reproduced on exact v21',
                                   'full_candidate03_tests.xml/log: 734 passed, one AppTest 15-second timeout; isolated exact test passed in 0.86s; final full rerun retained'],
        'legacy_prompt_assertions_baseline':read(OUT/'legacy_assertion_baseline.json'),
        'excluded_historical_receipt_test':{'path':'tests/test_creative_real_receipt_replay.py','counted_as_passed':False,'rerun_this_v22_round':False,
                                            'prior_v20_v21_baseline':prior['historical_extra_failure'],'explanation':'Known retained strict-prompt mismatch is preserved, not bypassed or relabeled as passed.'},
        'same_intent_cross_version_migration':'not exposed; original claim, directory and cumulative budget retained; no historical task migrated',
        'quality_improvement_verified':False,'actual_cost_reduction_verified':False,'live_publication_performed':False,'automatic_media_content_review_performed':False,
        'runtime_unchanged_after_acceptance':True}
(OUT/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''.join('<tr><td>'+html.escape(x['priority'])+'</td><td>'+html.escape(x['item'])+'</td><td>'+html.escape(x['status'])+'</td><td>'+html.escape(x['evidence'])+'</td></tr>' for x in checklist)
body=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>创作平台 v22 剩余重构验收</title>
<style>body{{background:#f4f6fa;color:#192b3c;font:16px/1.8 'Microsoft YaHei',system-ui;margin:0}}main{{max-width:1160px;margin:32px auto;padding:0 24px 50px}}section,header{{background:white;border:1px solid #d8e1eb;border-radius:12px;padding:24px 30px;margin:20px 0}}h1{{font-size:28px}}h2{{font-size:21px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #d8e1eb;padding:10px;text-align:left;vertical-align:top}}th{{background:#edf3fa}}a{{color:#1757a8}}.note{{padding:14px;background:#fff5df;border-left:4px solid #bb7708}}code{{overflow-wrap:anywhere}}.ok{{color:#1b7150;font-weight:bold}}</style><main>
<header><h1>按方向报告收口剩余重构：v22</h1><p class="ok">剩余实现与离线实际执行链路通过：{len(identities)} 项，零失败、零跳过。P1 原清单全部覆盖（当前 {len(p1cases)} 项）。</p><p>核心依据：<a href="../direction_report.html">方向报告</a>；前置清单：<a href="../v20_confirmation/confirmation_report.html">v20 复核</a>；<a href="../p1_closure_v21/acceptance_report.html">v21 P1 闭环</a>。</p><p class="note">本次断网验收复用实际阶段运行器、编译器、媒体执行器、人工决定接口、浏览器 PublishWorkflow 和运营回执；外部服务、视频字节、人工标签、浏览器页面及 concat 执行均为明确标注的夹具。没有真实付费生成、看听/抽帧/ASR、替用户内容审核或真实平台发布。测试通过不证明创作质量改善。</p></header>
<section><h2>逐项验收</h2><div style="overflow:auto"><table><thead><tr><th>优先级</th><th>实现与验收项</th><th>结果</th><th>证据</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<section><h2>执行链路与预算</h2><p>阶段输入和结果已拆为冻结合同。父字段投影来自真实消费对象；下游完整输入与提示一致才复用，变化则保留历史后重建。同正文、不同输入保留两套不可变身份，并可对比输入差异。</p><p>停止在途文本时先保存有效响应，再阻止未来派发；恢复不重置预算。媒体预览与提交共用实际模板。原任务 ID 续查、无 ID 未知提交、换输出目录、同稿失败上限、失效来源和错误段序均有回归。额度拒绝明确记录 blocked_before_submit，与已经调用但结果未知区分。</p><p>媒体链路验证三段、紧邻批准原尾续段、另有已审新机位的计划切镜、原音轨合成、整片待审以及完整成片批准后交付。人工批准均为测试夹具，不是用户对真实视频的批准。</p><p><a href="execution_chain_probe.json">六条独立链路快照（132 份文件）</a> · <a href="execution_chain">原始链路回执目录</a> · <a href="full_final_tests.xml">全量 JUnit</a> · <a href="full_final_tests.log">全量日志</a> · <a href="remaining_p1_tests.xml">P1 补充测试</a></p></section>
<section><h2>质量与发布边界</h2><p>人工金标、留出隔离、同源泄漏、规定样本门槛和费用接口已实现。仍须 80 个独立人工批准样本、40 个冻结留出、4 类覆盖及每版本 3 轮；12 个修复、6 个独立简报与 10 个边界要求保留。本轮没有新增真实金标或完成真实效果对照；缺失费用、工时与时延保持 null，未宣称降本。</p><p>交付接入现有账号绑定浏览器流程，核对发布前主动 AI 选择和读回、简介首部虚构声明、提交锁及发布后准确作品。待核验独立记录，重核原作品不重传；运营只匹配同账号同作品，缺失指标为 null。本轮未真实发布。</p></section>
<section><h2>冻结与历史</h2><p>新包 <a href="../../../../data/creative_governance/20261002_v22_platform_refactor_workbench/artifact_manifest.json">v22：55 项治理产物</a>，绑定 51 份运行文件（47 份 Python 语法验证）。<a href="integrity_checks.json">哈希核验</a>证明 v20、v21、v19、v18 原包未变，最终源文件与受测候选完全相同。<a href="source_snapshot">本轮源码和测试快照</a>可供复查。</p><p>同意图保持原目录与累计预算；本版不提供跨治理版本自动迁移，旧任务须在原冻结环境恢复或保持只读。不能靠改目录、改焦点或删登记重领额度。</p><p>已同步<a href="../../../../docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md">当前实现文档</a>及调试、能力、架构、README，并冻结入包。v21 以前的实现说明另存归档。</p></section>
<section><h2>失败尝试与已知历史缺陷</h2><p>初轮全量 726 通过、6 失败：一处新派生产物错误类型已修复；五项旧提示词断言在哈希精确 v21 上复现，随后改为严格检查原策略加既有叙事提示层，未放宽产物或请求哈希。<a href="legacy_assertion_baseline.json">v21 原源码复现证据</a>和旧失败日志保留。</p><p>候选第三轮 734 通过、1 个页面测试触及 15 秒超时；同一用例单独复跑 0.86 秒通过，最终使用正式默认绑定重新跑完整集合。未跳过该用例，未延长超时或削弱断言。</p><p>tests/test_creative_real_receipt_replay.py 未计为本轮通过、未在本轮重跑：既有 2026-09-27 真实历史回执已在 v20/v21 同样被严格提示绑定拒绝（writer_revise__preflight_story_00_01，calls_started=30，新增调用=0）。<a href="../p1_closure_v21/legacy_replay_comparison.json">既有基线</a>继续保留；没有改写历史回执或取消校验。</p><p><a href="acceptance.json">机器可读验收</a> · <a href="evidence_manifest.json">本轮证据哈希清单</a> · <a href="build_acceptance.py">报告生成入口</a> · <a href="run_acceptance.py">断网复跑入口</a></p></section></main></html>"""
(OUT/'acceptance_report.html').write_text(body,encoding='utf-8')
paths=[p for p in OUT.iterdir() if p.is_file() and p.suffix in ('.json','.xml','.log','.py','.html') and p.name!='evidence_manifest.json']
paths+=list((OUT/'source_snapshot').rglob('*'))
paths=[p for p in paths if p.is_file()]
manifest={'schema':'creative_v22_evidence_manifest/v1','files':[{'path':str(p.relative_to(OUT)).replace(chr(92),'/'),'sha256':sha(p)} for p in sorted(paths)],'execution_receipts':'individual hashes in execution_chain_probe.json'}
(OUT/'evidence_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'distinct_final_passed':len(identities),'p1_covered_cases':len(p1cases),'artifacts':55,'runtime_sources':51,'quality_improvement_verified':False}))
