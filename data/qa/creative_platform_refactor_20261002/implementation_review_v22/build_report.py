from pathlib import Path
import json, hashlib, html, xml.etree.ElementTree as ET
from datetime import datetime

ROOT = Path.cwd()
OUT = ROOT / 'data/qa/creative_platform_refactor_20261002/implementation_review_v22'
load = lambda name: json.loads((OUT/name).read_text(encoding='utf-8'))
proof = load('inflight_feedback_probe.json')
integrity = load('integrity_and_dataset.json')
inventory = load('code_inventory.json')

def tests(name):
    suite = ET.parse(OUT/name).getroot().find('testsuite')
    return {key:int(suite.attrib.get(key,0)) for key in ('tests','failures','errors','skipped')}

def ref(path, line=None):
    return {'path':path,'line':line}

items = [
 {'id':'F01','priority':'P1','kind':'已复现缺陷','title':'统一任务状态提交，防止运行中的反馈丢失',
  'current':'文本执行锁只串行化 runner；反馈命令仍能另行写 state.json。页面所见输入、输出哈希的检查已经存在。',
  'evidence':'director_brief 已验证后，在 writer_script 的模拟模型调用内部提交带双版本哈希的 must_fix。写入时 revision_required；模型返回后反馈索引和失效状态被旧 runner 状态覆盖。不可变反馈收据仍在，恢复却继续调用 director_shots 1 次。',
  'impact':'用户已经提交的必修问题可能没有返修就继续消耗下游调用；破坏分段调试的核心约束。',
  'change':'让反馈、停止和 runner 共享有版本的任务状态提交规则。可采用追加式命令收件箱，由执行器持久化消费；或事务/CAS 存储。当前在途响应照常保存为历史，应用反馈并失效后续，下一次派发前检查。原子替换只能解决半写，不能解决旧状态覆盖新状态。',
  'acceptance':['本报告独立边界用例转为通过；带双版本哈希的反馈在调用返回、保存和恢复后都可追溯。','并发的多条反馈、停止与反馈交错、消费命令前后崩溃不丢记录，不重复消费。','责任阶段未修复前下游模型调用数为 0；原调用、预算、历史不重置。'],
  'sources':[ref('src/content_factory/creative_workflow.py',3512),ref('src/content_factory/creative_workflow.py',6580),ref('src/content_factory/creative_stage_debug.py',376)],
  'phase':'立即修复，再做依赖与模块优化'},
 {'id':'F02','priority':'P2','kind':'可用性缺口','title':'把分段调试做成连续的用户工作台',
  'current':'正文、分镜、输入/输出版本差异、媒体请求预览、人工视频决定和交付入口已存在；不是从零重做。输入合同已经保存。',
  'evidence':'页面仍要求手填单段计划、保存目录、候选回执和完整成片审核回执。prepare-segment、assembly-chain、assemble 已有 CLI/服务，但未接入当前面板的完整操作链。文本阶段页面及 debug CLI 没有独立的完整冻结输入查看/派发前预览入口，当前主要提供哈希和双版本差异。',
  'impact':'用户仍需要了解目录和回执结构，难以在“看文本 → 改责任阶段 → 审当前段 → 继续下一段”之间自然推进。',
  'change':'以阶段和镜段卡片展示当前稿、导演安排、情绪重心、反应窗口、在途任务和人工决定。自动从绑定任务选择计划、候选和批准链；页面加入首帧选择、批准尾帧续段、合成与整片审核。文本阶段提供派发前冻结请求摘要及可展开的原请求，修改只能通过版本化编辑/反馈命令。',
  'acceptance':['在界面完成文本返修、单段准备与显式提交、人工批准后续段、合成与整片人工审核，无需手填内部回执路径。','预览与实际派发采用同一输入/提示绑定；预览后源变化必须重新确认当前版本。','视频由用户审查；技术成功保持 awaiting_human_review；下游付费生成及发布保留明确执行按钮。'],
  'sources':[ref('src/web/creative_workbench_panel.py',105),ref('src/web/creative_workbench_panel.py',143),ref('src/web/creative_workbench_panel.py',222),ref('scripts/creative_workbench.py',91),ref('scripts/debug_creative_workflow.py',22)],
  'phase':'反馈一致性修复后，优先改善日常使用'},
 {'id':'F03','priority':'P2','kind':'运维与版本支持缺口','title':'提供可审计的锁恢复和旧环境恢复工具',
  'current':'重复文本派发、媒体回执写入有独占锁；异常遗留锁保留以防盲重发。旧任务不静默改绑，也不领取新预算。这些保护应保留。',
  'evidence':'文本锁仅保存 scope 和禁止自动解锁字段，媒体锁为固定字符串；缺少统一的 owner/PID/启动身份、时间及请求关联信息。当前创作命令没有对账后安全恢复遗留锁的入口。MIGRATION.md 明确旧任务须恢复原冻结环境或只读，本版没有跨治理版本迁移命令。',
  'impact':'崩溃后正确停住，但恢复依赖操作者手工查进程、文件和外部任务；源码哈希与运行环境恢复之间仍有操作成本。',
  'change':'增加锁拥有者及进程启动身份、主机、时间、阶段、请求/媒体 ID 的审计元数据；提供诊断和显式对账恢复命令，确认旧进程结束后才接管。交付可重建的冻结源码、依赖锁定和启动步骤。另做显式迁移 dry-run，展示可携带产物、未决任务/反馈和累计预算，再生成迁移收据。',
  'acceptance':['模拟进程强退后能够核对旧请求并恢复；有 ID 只查询，unknown 无 ID 不因清锁而再次提交。','旧进程仍活跃、请求无法对账、租约/所有权不明时拒绝接管；恢复动作有不可变回执。','旧任务恢复或迁移保持 task lineage、累计调用/token/返修/媒体失败预算和历史；身份变化重新人工批准。'],
  'sources':[ref('src/content_factory/creative_workflow.py',6580),ref('src/content_factory/creative_segment_execution.py',297),ref('data/creative_governance/20261002_v22_platform_refactor_workbench/MIGRATION.md')],
  'phase':'与工作台完善并行，先恢复工具后自动迁移'},
 {'id':'F04','priority':'P2','kind':'架构改善','title':'继续拆分核心编排与验证返修责任',
  'current':'媒体、交付、合同和阶段运行模块已经拆出，边界确有进展；核心 runner 仍持有大部分逻辑。',
  'evidence':'AST 统计 creative_workflow.py 8,298 行、138 个函数；_validate_or_repair 1,721 行，_run_unlocked 1,018 行。creative_stage_runtime.execute_stage 仍从 workflow 导入工具/常量，并调用 runner 的 state、预算和私有实现。',
  'impact':'同一函数承担多个阶段的合同、返修和状态转换，变更难以局部验证；增加分段调试功能时容易牵动老流程。行数是耦合线索，不单独构成缺陷。',
  'change':'在现有技术栈内逐步拆为预算与调用账本、请求/响应持久化、阶段合同与 validator 注册、文本审核/返修、阶段编排。用显式 StageContext 和服务接口替代把整个 runner 传入各模块。每次移动一种责任，保留原入口和治理协议。',
  'acceptance':['每个阶段能用冻结输入单独执行与重放，模拟 provider、预算和持久化，验证失败路由。','新阶段只注册合同/依赖/校验与执行函数，不再增加 giant runner 分支。','原断点、全文整体采用、审核门、缓存零调用、预算及历史回归保持通过；冻结旧包不修改。'],
  'sources':[ref('src/content_factory/creative_workflow.py',4033),ref('src/content_factory/creative_workflow.py',6594),ref('src/content_factory/creative_stage_runtime.py',86)],
  'phase':'增量拆分，不建议一次重写'},
 {'id':'F05','priority':'P2','kind':'依赖优化','title':'把字段投影提升为显式输入来源合同',
  'current':'实际非空对象/数组投影与完整输入/提示兼容复用已经实现；保守失效回退仍然存在。不能再把字段级处理列为完全未实现。',
  'evidence':'projections 通过子树内容哈希相同匹配父产物与请求字段，排除标量；相同内容在不同路径出现时并不等同于声明了来源关系。完整请求兼容检查仍是安全边界。',
  'impact':'目前能证明请求包含这些内容，但依赖解释和更细粒度的安全复用仍有限；完整父对象被复制时自然依赖其全部字段。',
  'change':'为 StageContract 声明 source stage/version、输出字段路径与目标输入字段；生成请求时记录显式消费绑定。展示“哪处修改导致哪阶段重建”，减少不必要的完整上下文复制，但未知依赖仍按保守阶段失效。',
  'acceptance':['消费字段变化必重建，未消费字段变化在完整请求仍兼容时可复用；审核决定不跨不同请求复用。','覆盖同值不同来源、重复对象、标量引用、数组重排、移除/空值和规则/模板版本变化。','复用证明可读且可追溯，预算下降按原调用回执统计。'],
  'sources':[ref('src/content_factory/creative_stage_contracts.py',49),ref('src/content_factory/creative_stage_contracts.py',123)],
  'phase':'核心责任拆分后优化，先确保正确性'},
 {'id':'F06','priority':'P3','kind':'质量证据缺口','title':'用真实人工案例验证分段调试是否改善创作',
  'current':'候选采集、人工标注、留出冻结和评分接口已存在，当前不宣称真实质量提升，文档表述诚实。',
  'evidence':'独立检查 v22 治理包 dataset_manifest：28 个候选、0 人工批准金标、0 合格留出；这仅说明当前包的证据，不能把自动夹具计为真实创作样本。',
  'impact':'目前可以证明流程机制，仍不能回答用户最关心的效果：剧本是否更好、情绪反应窗口是否合适、返修是否减少、视频是否符合预期。',
  'change':'先建开发试点：6 个独立简报、12 个实际修复案例、10 个边界案例，记录用户原问题、修订目标、阶段前后版本与人工耗时。按既定标准建设 80 独立人工金标、40 冻结留出、每版本 3 轮评估；开发样本不转为留出。增加当前+归档全部尝试的调用用量、真实账单、时延和人工工时采集。',
  'acceptance':['文本评价覆盖因果、人物动机、重要对白前中后反应和导演可执行性；视频评价仅使用用户明确的人工决定。','预先冻结基线、评分准则与留出来源，再比较改版；重复执行不增加独立样本数。','缺失金额/时延/工时保持未知；分开报告创作质量、规则检测能力、返修成功率和每份合格交付成本。'],
  'sources':[ref('src/content_factory/creative_quality_evidence.py',171),ref('src/content_factory/creative_evaluation.py',7),ref('data/creative_governance/20261002_v22_platform_refactor_workbench/dataset_manifest.json')],
  'phase':'工作台完善时并行做开发试点，满足证据门后宣称提升'},
 {'id':'F07','priority':'P3/P4','kind':'真实运行证据缺口','title':'补服务、媒体技术格式与浏览器运行验收',
  'current':'Mock 故障、媒体 ID 查询、人工批准链和浏览器发布夹具已经验证；本轮没有执行真实媒体或发布。',
  'evidence':'实现文档明确 v22 验收为离线代码/故障链；媒体字节和人工决定是夹具。原验收的 738 项不能替代真实服务及真实浏览器运行证据。',
  'impact':'真实 provider 的合同、连接中断、账单字段、异构媒体音轨/帧率和发布控件变化仍需受控验证，尚不能宣布生产全链路验收完成。',
  'change':'先补不付费的格式与服务合同故障集，再在明确授权的真实任务中验证最小完整链：文字阶段、显式单段生成、人工批准原尾帧、续段、原音轨合成、整片人工审核、浏览器发布与准确作品核验。',
  'acceptance':['服务提交后的连接故障不盲重发；已知 ID 续查，无 ID unknown 对账；保存文件与原尾帧身份正确。','媒体仅检验技术完整性和格式兼容，内容由用户审查；无音轨/格式不兼容清楚报错或有明确配方。','真实发布有主动 AI 声明控件读回、虚构前缀、账号/作品绑定和独立核验；平台待审核保持待核验并锁住提交。'],
  'sources':[ref('docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md',47),ref('docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md',59),ref('src/content_factory/creative_media_workbench.py',388),ref('src/content_factory/creative_delivery.py',133)],
  'phase':'夹具验收与真实验收分别登记，不自动发起付费或发布'}
]
report = {
 'schema':'creative_implementation_review/v1',
 'created_at':datetime.now().astimezone().isoformat(),
 'scope':'Current v22 document, relevant source paths, new offline fault reproduction and targeted regression. Not a repository-wide certification.',
 'core_direction':'data/qa/creative_platform_refactor_20261002/direction_report.html',
 'implementation_document':'docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md',
 'conclusion':'已有 v22 闭环接口基础；仍有 1 处实证反馈并发缺陷，需优先修复。其后完善分段工作台和真实质量试点，增量拆分核心、产品化恢复、优化依赖与补真实运行证据。',
 'tests':{'independent_targeted':tests('targeted_tests.xml'),'new_boundary_contract':tests('inflight_tests.xml'),'author_full_suite_claim':738,'author_full_suite_rerun_this_review':False,'ui_rerun_this_review':False},
 'inflight_feedback':proof,'integrity_and_dataset':integrity,'code_inventory':inventory,
 'roadmap':items,
 'work_performed':{'business_source_changed':False,'governance_pack_changed':False,'paid_calls':False,'real_media_generation_or_content_review':False,'production_publish_or_migration':False},
 'sequence':['F01：反馈一致性及在途边界专测，完成新治理版本绑定与回归。','F02 + F06：顺畅的文本/镜段工作台与真实人工开发试点。','F03 + F04：异常恢复工具及核心责任增量拆分。','F05：基于真实消费绑定缩小重建范围并证明收益。','F07：在授权的真实任务中逐项补运行证据。']
}
(OUT/'review_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

esc=html.escape

def link(path,label=None,line=None):
 url=(ROOT/path).resolve().as_uri()
 return '<a href="'+esc(url,quote=True)+'">'+esc(label or path)+((':'+str(line)) if line else '')+'</a>'

def item_card(r):
 citations=' · '.join(link(s['path'],Path(s['path']).name,s.get('line')) for s in r['sources'])
 accepts=''.join('<li>'+esc(x)+'</li>' for x in r['acceptance'])
 return f'''<article id="{r['id']}"><div class="eyebrow">{esc(r['priority'])} · {esc(r['kind'])}</div><h2>{esc(r['id']+' '+r['title'])}</h2><p><b>已有：</b>{esc(r['current'])}</p><p><b>证据：</b>{esc(r['evidence'])}</p><p><b>影响：</b>{esc(r['impact'])}</p><p><b>建议：</b>{esc(r['change'])}</p><details open><summary>完成标准</summary><ul>{accepts}</ul></details><p class="refs">{citations}</p></article>'''

rows=''.join(f'<tr><td><a href="#{r["id"]}">{esc(r["id"])} {esc(r["priority"])}</a></td><td>{esc(r["title"])}</td><td>{esc(r["kind"])}</td></tr>' for r in items)
sequence=''.join('<li>'+esc(x)+'</li>' for x in report['sequence'])
evidence_links=' · '.join(link(str((OUT/name).relative_to(ROOT)),label) for name,label in [('inflight_feedback_probe.json','在途反馈复现'),('test_inflight_feedback_contract.py','边界回归用例'),('inflight_tests.log','失败回执'),('targeted_tests.log','47 项回归'),('integrity_and_dataset.json','哈希与数据集核验'),('review_report.json','结构化报告')])
page=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>v22 后续修复与重构方向</title><style>
:root{{color-scheme:light;--ink:#18302d;--muted:#5b6c68;--line:#d9e3de;--bg:#f3f6f2;--accent:#126459}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.8 'Microsoft YaHei',sans-serif}}main{{max-width:1120px;margin:auto;padding:38px 26px 72px}}h1{{font-size:34px;line-height:1.35;margin:10px 0 16px}}h2{{font-size:23px;line-height:1.45;margin:6px 0 17px}}h3{{font-size:19px}}p{{margin:12px 0}}a{{color:var(--accent);text-decoration:underline;text-underline-offset:3px;overflow-wrap:anywhere}}.eyebrow{{font-size:13px;letter-spacing:.04em;font-weight:700;color:var(--accent)}}.intro{{font-size:18px}}.note{{background:#fff0dd;border-left:5px solid #be6e25;padding:18px 23px;margin:24px 0;border-radius:5px}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}}.metric{{background:white;border:1px solid var(--line);padding:17px 20px;border-radius:12px}}.metric strong{{display:block;font-size:28px;line-height:1.4}}.metric span{{color:var(--muted);font-size:14px}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;background:white;margin:22px 0 28px}}th,td{{text-align:left;padding:12px 14px;border:1px solid var(--line)}}th{{background:#e8efea}}td:first-child{{white-space:nowrap}}article{{background:white;border:1px solid var(--line);border-radius:14px;padding:26px 29px;margin:20px 0;scroll-margin-top:20px}}details{{background:#f5f8f5;border-radius:8px;padding:12px 18px;margin:18px 0}}summary{{cursor:pointer;font-weight:700}}li{{margin:8px 0}}.refs{{font-size:13px;color:var(--muted)}}.footer{{font-size:14px;color:var(--muted);border-top:1px solid var(--line);padding-top:22px}}code{{overflow-wrap:anywhere;background:#eaf0e9;padding:2px 5px;border-radius:4px}}@media(max-width:680px){{main{{padding:23px 17px 50px}}h1{{font-size:27px}}h2{{font-size:21px}}.metrics{{grid-template-columns:repeat(2,1fr)}}article{{padding:20px 18px}}th,td{{padding:10px;font-size:14px}}}}
</style></head><body><main><div class="eyebrow">独立实现复核 · 2026-10-02 · v22</div><h1>后续修复与重构方向</h1><p class="intro">{esc(report['conclusion'])}</p><p>核心方向仍为 {link(report['core_direction'],'方向报告')}；{link(report['implementation_document'],'当前实现文档')} 用于描述现状，后续验收应区分代码闭环、用户可用性与真实创作效果。</p><div class="note"><b>先修 F01：</b>用户在模型调用期间提交的必修反馈已通过当前版本检查，却被 runner 后续保存覆盖。独立用例失败；恢复后实际又发生了 1 次模拟下游调用。已有测试通过不覆盖这个边界。</div><div class="metrics"><div class="metric"><strong>47 / 47</strong><span>本轮定向回归通过</span></div><div class="metric"><strong>1 处</strong><span>新增实证缺陷</span></div><div class="metric"><strong>51 / 55</strong><span>源码 / 工件哈希通过</span></div><div class="metric"><strong>0 / 0</strong><span>当前包人工金标 / 合格留出</span></div></div><p>作者原联合验收为 738 项；本轮仅独立重跑新增模块与治理协议共 47 项，另新增在途反馈边界用例 1 项失败。没有重跑全量或 UI，没有把原作者回执当作本轮独立执行结果。</p><div class="table-wrap"><table><thead><tr><th>顺位</th><th>方向</th><th>性质</th></tr></thead><tbody>{rows}</tbody></table></div>{''.join(item_card(r) for r in items)}<article><div class="eyebrow">实施顺序</div><h2>围绕“分段看效果、改责任阶段、保留历史”推进</h2><ol>{sequence}</ol><p>后续源码或当前实现文档变化会改变治理哈希，应形成新版本并重新绑定新任务；不要修改 v18–v22 冻结包来消除哈希差异。当前 v22 源码 51 项与工件 55 项均匹配；复核到的 v18–v21 历史工件也匹配各自清单。</p><p>文档下一步应补上“在途反馈提交”“界面完整链”“异常锁恢复”“冻结环境恢复”和“真实质量证据”状态及验收入口。F01 修复前不能把动态反馈一致性写为完成。</p></article><div class="footer"><p><b>证据入口：</b>{evidence_links}</p><p>本轮仅新增 QA 复现、核验和报告文件；业务源码与冻结治理包未修改。没有付费服务调用、真实媒体生成/内容检查、生产发布或任务迁移。媒体始终由用户人工审核。</p></div></main></body></html>'''
(OUT/'review_report.html').write_text(page,encoding='utf-8')
print(json.dumps({'report':str(OUT/'review_report.html'),'roadmap_items':len(items),'targeted':report['tests']['independent_targeted'],'boundary':report['tests']['new_boundary_contract']},ensure_ascii=False))
