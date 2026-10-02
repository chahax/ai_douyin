from pathlib import Path
from datetime import datetime, timezone, timedelta
import json, hashlib, xml.etree.ElementTree as ET, html
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[3]
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def stats(name):
    root=ET.parse(OUT/name).getroot()
    suites=[root] if root.tag=='testsuite' else list(root.iter('testsuite'))
    value={key:sum(int(s.get(key,0)) for s in suites) for key in ['tests','failures','errors','skipped']}
    value['passed']=value['tests']-value['failures']-value['errors']-value['skipped']
    return value
p1=stats('p1_tests.xml')
assert p1=={'tests':379,'failures':0,'errors':0,'skipped':0,'passed':379}
assert 'ACCEPTANCE_EXIT_CODE=0' in (OUT/'p1_tests.log').read_text(encoding='utf-8')
integrity=read('integrity_checks.json')
chain=read('chain_probe.json')
original=read('new_task_binding.json')
legacy=read('legacy_replay_comparison.json')
ruff=read('ruff_baseline_comparison.json')
assert chain['final_calls_started']==7 and chain['historical_artifacts_and_resolutions_unchanged']
assert legacy['matches_v20_failure'] and legacy['historical_source_unchanged']
assert ruff['baseline_matches_frozen_v20'] and ruff['same_existing_unused_summaries']
# Recheck live source and pack bytes after all tests and probes.
for row in integrity['source_checks']+integrity['changed_file_checks']:
    assert sha(ROOT/row['path'])==row['sha256'],row['path']
for pack in integrity['packs'].values():
    directory=ROOT/pack['directory']
    assert sha(directory/'artifact_manifest.json')==pack['manifest_sha256']
    for row in json.loads((directory/'artifact_manifest.json').read_text(encoding='utf-8'))['artifacts']:
        assert sha(directory/row['path'])==row['sha256']
checklist=[
    {'id':'P1-1','result':'accepted','change':'Current logical stages select latest validated input/output; historical executions remain read-only.',
     'evidence':['chain_snapshot.json','chain_probe.json','p1_tests.xml']},
    {'id':'P1-2','result':'accepted','change':'Persist conservative stage prerequisites; invalidate descendants; replay resolved upstream repair context while downstream feedback is pending.',
     'evidence':['p1_tests.xml','chain_probe.json']},
    {'id':'P1-3','result':'accepted','change':'Successive rounds, multiple targets in both feedback orders, invalidated intermediate rebuilds, strict hash rejection, single-step repairs, exhausted budgets and immutable history verified.',
     'evidence':['p1_tests.xml','chain_probe.json','checkpoint_6.json','checkpoint_7.json']},
    {'id':'P1-4','result':'accepted','change':'Implementation docs synced; actual new original governed task uses v21; v20 retained; provenance matches v20 to v21.',
     'evidence':['integrity_checks.json','new_task_binding.json']},
]
result={'schema':'creative_platform_p1_closure/v1','created_at_bjt':datetime.now(timezone(timedelta(hours=8))).isoformat(),
    'verdict':'P1_checklist_closed_offline_execution_chain_verified','direction_report':'../direction_report.html',
    'acceptance_checklist':'../v20_confirmation/confirmation_report.html','checklist':checklist,
    'tests':{'p1_unified':p1,'core':stats('core_tests.xml'),'governance':stats('governance_tests.xml'),
             'v20_boundary_and_extended':stats('boundary_tests.xml'),'additional_ui_fullscript_and_legacy':stats('ui_replay_tests.xml')},
    'actual_runner_cli_chain':chain,'actual_original_governed_task':original,
    'historical_extra_failure':{'classification':'preexisting_strict_prompt_binding_incompatibility',
        'v20_hash_exact_baseline':read('baseline_v20_reconstruction.json'),'comparison':legacy},
    'static_check_note':{'existing_F841_summaries_in_v20_and_current':True,'evidence':'ruff_baseline_comparison.json'},
    'integrity':integrity,'remaining_work':['P2 field-level dependency and compatibility optimization','Creation quality evaluation with human-approved samples and holdout'],
    'limits':['Offline fixtures and retained text receipts only; no paid API calls.',
              'No production task migration, media generation, frame extraction, listening, ASR, media review or publishing.',
              'Conservative stage dependencies verified; field-level compatibility is not implemented.',
              'P1 closure does not certify creativity, semantic quality, media approval or standards compliance.'],
    'historical_receipts_overwritten':False,'runtime_unchanged_after_acceptance':True}
(OUT/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
page="""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P1 多轮反馈闭环验收 · v21</title><style>
body{margin:0;background:#f4f6fa;color:#233448;font:16px/1.8 "Microsoft YaHei",system-ui,sans-serif}main{max-width:1050px;margin:28px auto;padding:30px;background:#fff;border:1px solid #d8e2eb;border-radius:12px}h1{font-size:28px}h2{font-size:21px;margin-top:28px}.callout{padding:16px;background:#ecf8f1;border-left:4px solid #27784d}.note{font-size:14px;color:#586a7c}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:11px;border:1px solid #d8e2eb;text-align:left;vertical-align:top}th{background:#f1f5fa}a{color:#185aaa}code{background:#f0f4f9;overflow-wrap:anywhere}li{margin:7px 0}.table{overflow-x:auto}@media(max-width:650px){main{margin:10px;padding:17px}table{min-width:600px}}
</style></head><body><main><p class="note">2026 年 10 月 2 日 · 实际运行器、CLI/UI 离线验收 · 保留冻结 v20</p><h1>P1 多轮阶段反馈闭环通过，默认治理包升级为 v21</h1>
<div class="callout">以<a href="../direction_report.html">方向报告</a>为目标、<a href="../v20_confirmation/confirmation_report.html">v20 最新复核</a>为验收清单，四项 P1 均完成。统一验收 <strong>379 通过 / 0 失败 / 0 跳过，退出码 0</strong>。实际 CLI 连续反馈绑定当前剧本，返修后正确暂停，缓存重放不增加调用。此结果证明操作与版本链路，不证明创作效果或媒体内容通过。</div>
<h2>逐项修复与验收</h2><div class="table"><table><tr><th>验收项</th><th>实现行为</th><th>实际证据</th></tr>
<tr><td>1 当前阶段与历史版本</td><td><code>stages</code> 每阶段只保留最新验证视图；<code>history</code> 保留执行记录并标注 historical。反馈核对不可变快照、当前回执与输入/输出哈希。UI 支持只读历史和版本差异。</td><td>最终 3 个当前阶段、7 个历史执行记录；第二轮和第三次返修反馈均绑定当前 writer_script 哈希。<a href="chain_snapshot.json">最终快照</a></td></tr>
<tr><td>2 阶段依赖失效与恢复</td><td>保存保守阶段前置图，按传递依赖失效；无图旧任务按首次遍历兼容建立。返修执行顺序和反馈登记顺序不改变上下游。其他待修目标保持 needs_revision，已解决上游继续严格重放。</td><td>两种多阶段反馈登记顺序、失效中间剧本与分镜重建、上下游哈希篡改阻断均通过。<a href="p1_tests.xml">统一 JUnit</a></td></tr>
<tr><td>3 多轮回归、预算与历史</td><td>同任务同预算恢复；单步将新修订版本计为一步，缓存不计。原产物、反馈原话和 resolution 不覆盖。</td><td>初稿 3 次 → 导演修订 4 次 → 剧本重建 5 次 → 连续返修 6、7 次；两次缓存重放均零调用。累计 fixture tokens=7，额度保持 20 次 / 500000 tokens / 8 次契约修复 / 5 轮返修。另验预算耗尽后零调用、待修反馈保留。<a href="chain_probe.json">链路回执</a></td></tr>
<tr><td>4 文档与新冻结包</td><td>同步<a href="../../../..//docs/CREATIVE_STAGE_DEBUGGING.md">调试指南</a>与<a href="../../../..//docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md">实现文档</a>。新任务默认 v21，旧任务不静默换绑，迁移 provenance 对齐 v20。</td><td>实际新原创治理任务完成首阶段、返修和缓存重放，默认绑定 v21；源码 33 项与工件 49 项均匹配。v20/v19/v18 冻结清单不变。<a href="new_task_binding.json">实际任务绑定</a> · <a href="integrity_checks.json">完整性核验</a></td></tr>
</table></div>
<h2>执行验证范围</h2><div class="table"><table><tr><th>测试组</th><th>结果</th></tr><tr><td>六模块核心回归（新增 13 项阶段回归）</td><td>305 通过</td></tr><tr><td>治理 / 回滚 / 数据库迁移就绪</td><td>40 通过</td></tr><tr><td>原 v20 边界与连续反馈用例（原 2 项失败已转通过）</td><td>14 通过</td></tr><tr><td>UI（含最新反馈、历史与差异）和完整剧本修订</td><td>20 通过</td></tr><tr><td>统一同进程最终验收</td><td>379 通过，13 条既有弃用警告，退出码 0</td></tr></table></div>
<p>实际工作流、CLI 子进程及 Streamlit AppTest 已执行；模型响应使用假服务或保留的文本回执。离线验收脚本禁止网络连接，零付费调用。没有迁移生产任务，没有生成、查看、抽帧、听看、ASR、审核或发布媒体。</p>
<h2>额外历史检查如实保留</h2><p>额外运行一份 2026-09-27 生产文本回执的兼容测试，因 <code>writer_revise__preflight_story_00_01</code> 提示词哈希与当前提示词不一致而停止。这项不计 P1 通过：原始扩展组为 20 通过 / 1 失败。重建的 v20 工作流 SHA-256 与冻结 v20 完全相同，并复现相同错误；v20、v21 均零调用、原计数 30 不变，生产原件未修改。该旧回执仍需显式版本迁移或重新验证，未放宽哈希门。<a href="legacy_replay_comparison.json">v20/v21 对照</a> · <a href="ui_replay_tests.xml">原始额外测试</a></p>
<p class="note">Ruff 的唯一 F841（原有未使用变量 summaries）也在哈希完全匹配的 v20 调试模块中复现，未把整组 Ruff 写成通过。修改文件语法和空白检查通过；29 个运行时 Python 文件解析通过。<a href="ruff_checks.json">原始 Ruff</a> · <a href="ruff_baseline_comparison.json">基线核对</a></p>
<h2>冻结与后续边界</h2><p>新冻结包：<a href="../../../../data/creative_governance/20261002_v21_platform_refactor_multi_feedback/artifact_manifest.json">20261002_v21_platform_refactor_multi_feedback</a>，<a href="../../../../data/creative_governance/20261002_v21_platform_refactor_multi_feedback/MIGRATION.md">迁移说明</a>。v20 工件清单与原复核哈希一致，旧版本只作为历史，不与当前运行时混用。</p>
<p>P1 验收闭环后，下一阶段为字段级依赖与兼容证明、文本和最终请求对照，以及人工批准样本/保留集的创作质量评估。目前的保守阶段图不等于字段级依赖优化；没有人工批准的 gold/holdout，不宣称质量改善。</p>
<h2>可复跑证据</h2><ul><li><a href="acceptance.json">机器可读总回执与验收清单</a></li><li><a href="p1_tests.log">统一验收日志</a> · <a href="p1_tests.xml">统一 JUnit</a></li><li><a href="run_acceptance.py">离线验收脚本</a>：在仓库根目录运行 <code>.venv/Scripts/python.exe data/qa/creative_platform_refactor_20261002/p1_closure_v21/run_acceptance.py p1</code>。</li><li><a href="probe_chain.py">实际运行器与 CLI 链路脚本</a> · <a href="checkpoint_6.json">第 6 次调用状态</a> · <a href="checkpoint_7.json">第 7 次调用状态</a></li><li><a href="integrity_checks.json">源码/冻结包/旧绑定核验</a> · <a href="evidence_manifest.json">本轮证据哈希</a></li></ul>
</main></body></html>"""
page=page.replace('../../../..//','../../../../')
(OUT/'acceptance_report.html').write_text(page,encoding='utf-8')
files=[OUT/name for name in ['acceptance.json','acceptance_report.html','p1_tests.xml','p1_tests.log','p1_selection.json',
    'chain_probe.json','chain_snapshot.json','new_task_binding.json','checkpoint_6.json','checkpoint_7.json',
    'integrity_checks.json','legacy_replay_comparison.json','baseline_v20_reconstruction.json',
    'baseline_v20_workflow.py','baseline_v20_stage_debug.py','ruff_baseline_comparison.json','ruff_checks.json',
    'run_acceptance.py','probe_chain.py','compare_legacy_replay.py','verify_integrity.py','build_report.py']]
manifest={'schema':'creative_p1_closure_evidence/v1','created_at_bjt':result['created_at_bjt'],
    'files':[{'path':p.name,'sha256':sha(p)} for p in files]}
(OUT/'evidence_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'verdict':result['verdict'],'tests':p1,'pack':'v21','report':str(OUT/'acceptance_report.html')},ensure_ascii=False))
