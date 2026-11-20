# 618原生规划复用与历史语用诊断接线

本轮按 `CREATIVE_COUNTED_REPAIR_EXECUTION_20261015.md` 新增独立入口，旧round25终态、618原生规划、619失败报告与全部账本不改。这里记录工程接线，不是完整正文、导演或创作质量交付。

## 正式文本入口v27

`scripts/run_goal_context_text_production_v27.py` 复用round25的618完整原生规划，从source6开始，接同源commitment/drama审查、原生开场初态、完整正文、semantic/physical全文复审。source6仍需模型原生工具报告，不把619报告转换为通过。已知完整正文失败最多两份整稿返修。

本地安全容量为三审3次、初态2次、完整正文3次、全文分审6次；不新增整片规划。底层`goal_plan`阶段仅允许opening_setup/v4，拒绝整片规划30。旧导演7/7仍保留、没有新增导演或媒体容量。

新strict-client/v5及dispatch/v11只接source6的DeepSeek beta严格请求，MiniMax-M3.1-Flash-Preview和其他DeepSeek普通通道参数保持原分工。SDK retries为0，未知、截断、缺工具、不完整结果停止，不重新领取旧格式恢复额度。

新增strict证明由实际客户端和调用后的wire比对验收。历史lineage-v6仅验证父619及更早记录；它不支持把本轮source6新证明当作未来子运行证书，当前明确没有实现该未来继承能力。

**当前实际停点：** 真实当前时间调用原生产来源门返回`opportunity_outside_validity`。证据见`data/qa/creative_speech_act_producer_20261015/V27_CURRENT_FRESHNESS_STOP_v1.json`；没有创建正式v27 root/claim、没有调用模型。不回拨生产时钟、不静默替换冻结来源。

## 独立历史小上下文probe

`scripts/run_legal_speech_act_probe_v1.py` 是单次DeepSeek普通通道历史诊断，最多1次、writer/media/publish均为0。它继承619次、12,930,923 reported tokens、617次已知用量，历史未知70/160与93,117预留不变。调用后新的累积消耗必须成为后续生产继承锚点。

它读取12个已有故障正反案例，核对原文件SHA、同一原生规划的来源目录、原句和上下文。请求只保留盲化T编号、目标原句与同稿上下文、七类通用定义；不包含期待分类、以前的审查判定、案例设计说明或答案示例。顺序和原案例映射保存在请求预览旁，本地评价使用原案例期待值。

评价分别报告法律/不确定分流正例召回、非法律误报和细类准确率。普通F/R/P/M/N细类差异单列，不自动当法律误报；正例必须进入允许的L/U分支并说明实际命题。负例即使标为非法律，只要另外发明非空法律命题，也失败。原生结果仍须检查理由是否真的符合原句，标签统计不证明语义能力或作品质量。

`preview`只核案例和实际wire，不执行完整历史证书guard。`register`、`prepare`及真实runtime保留完整历史校验；历史证书的来源重建显式使用原记录采样日期，仅证明历史记录在当时的身份/完整性。所有输出均标`historical_diagnostic_only`与`current_source_freshness_passed=false`，不能拿历史诊断代替新热度来源准入。

当前修正版预览：`data/qa/creative_speech_act_producer_20261015/HISTORICAL_PROBE_REQUEST_PREVIEW_v2.json`。此前启动的只读旧预览进程可能保存v1；该旧版不注册、不使用，v2另存，不覆盖旧证据。

## 复盘停止门与防漏消耗

每次真实调用除外层检查，还在runtime内部派发admission核对`CountedExecution.assert_dispatch_allowed`，绑定现有执行root和`source_speech_act_v6_attempt_01`，不初始化、清零或替代原预算。第10次复盘后的停止、复盘待办或非活动轮次均不能继续派发；准备和预览不计新修复轮。

只要历史probe的claim或ledger存在，v27的旧619锚点即拒绝prepare/run，包括probe未知结果或已完成情况。后续须新增明确承接probe真实消耗和未知状态的入口；不得使用v27跳过probe新消耗，也不能仅把“后续应继承”写成备注后继续。

## 命令与本轮边界

只读请求预览：

```powershell
.\.venv\Scripts\python.exe scripts/run_legal_speech_act_probe_v1.py preview
```

主agent完成代码、真实wire、案例和历史guard审查后，独立诊断的单次顺序是：

```powershell
.\.venv\Scripts\python.exe scripts/run_legal_speech_act_probe_v1.py register
.\.venv\Scripts\python.exe scripts/run_legal_speech_act_probe_v1.py prepare
.\.venv\Scripts\python.exe scripts/run_legal_speech_act_probe_v1.py run
```

此文档编写时，实施agent仅开发、预览和离线SDK模拟，没有register/prepare、真实claim、模型或媒体调用。正式v27仍因来源过期停在生产前；probe通过也不自动启动source6、正文、导演或媒体。
