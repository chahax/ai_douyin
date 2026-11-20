# 小说改编路线：实施、主审与使用（2026-10-17）

## 已完成范围

按用户确认的[开发合同](NOVEL_ADAPTATION_ROUTE_PLAN_20261017.md)，新增独立路线：获取正文 → 背景/人物/主线/高潮分析 → 角色与高潮选择、改编规划 → 完整剧本 → 同稿全文审查 → 有界完整返修 → 文本导演交接。子agent分别开发合同、执行器和入口；主agent检查实际接线、补独立负例，并要求修复后统一验收。

真实网页入口为后台侧栏 **小说改编**，URL路径 `/novel-adaptation`。页面不依赖账号/选题卡，也不初始化全局账号范围数据库。旧账号小说入口、默认v23、旧事件稿入口保持原语义，不静默迁移。

正文采集桥接委托已有 `FanqiePromotionService.fetch_book`，默认一次1章，可显式调整。复用采集器自己的登录环境；独立Chrome登录态不自动共享。每次新采集目录独占，成功保存章节和回执，失败保存失败回执并停止。已有meta/采集回执或纯正文也可进入；章标题及实际已取得范围明确保留，简介不能作为正文。

## 创作与审查标准

- `analysis`：世界框架、未知背景、角色身份/性格/处境/目标/关系、主线因果、转折、高潮候选及选择理由。
- `adaptation_plan`：选择的角色和高潮、实际选段、起止状态、因果铺垫与刺激/反应/升级/结尾、必须保留的事实、改编变更和理由、目标时长。
- `screenplay`：一份原生结构化完整稿；世界和角色先行，每场时间线、时间、地点、在场者、首尾状态、顺序表演事件，以及每事件全部在场者的动作/神情/视线。对白允许自然重写，不要求逐字等于小说。`SCREENPLAY.md`由同一完整JSON确定性投影，模型不重复写第二份正文。
- `review`：DeepSeek读取同次冻结正文、完整分析、改编计划和完整剧本，覆盖主线/动机、因果、身份、空间/视线/动作、情绪窗口、对白自然程度、可拍性、完整性、时长九项。问题归属analysis、adaptation_plan或screenplay；退回最早责任阶段，重建其下游并全文复审。

引用采用原文短引文、必要时出现序号；程序定位，不让模型计字符下标或回传SHA。原文SHA、选段SHA、范围与稿件/审查身份由程序保存。引用位置正确只证明证据位置，不证明解读正确。

程序汇总结构/选角/来源/时长/表演窗口问题；总时长等于事件时长之和。公开阅读估算为中文字符数/6＋英文词数/3，重要情绪及反应至少1秒是结构下界，不能当作真实配音时长或表演合格证据。主线忠实、情绪是否有效仍须实际模型全文审查与后续用户评价。

## 执行、预算与恢复

仅`execute`调用文本服务：MiniMax创作，DeepSeek全文审查，沿用现有已核实客户端；本轮开发没有更换模型。默认20次调用、500000 reported tokens、全运行合计最多2轮已知内容完整返修。分析/规划/剧本返修共用这2轮，不按阶段另领。默认值是新入口配置，不能解释为旧任务的新增额度。

每次派发核对冻结来源、代码、提示、协议及预算，保存请求/响应/原生载荷与用量。同故事登记同时约束来源SHA、书ID和标题；换目录或附加registry不能重领。完成响应在阶段推进前中断，可复用原响应；交付写入中断可从已验收阶段恢复，不重复模型请求。未知结果、截断、缺用量/工具/原生证据等停止，不能自动重试。

完成状态为 `text_ready_for_director`，`human_approved=false`。inspect复验当前稿、原生结果、同稿完整审查和输出文件，文件缺失/篡改不能保持完成。派发阻断与产物查看分别处理：完成后禁止重复派发，阅读剧本仍可查看。

历史《婚礼现场，我和全家断绝关系！》仍是累计11次/180079 tokens、截断停止，尚无通过的完整剧本。新入口识别书ID、原路径、来源SHA、标题及旧选段的精确匹配/双向包含，只能本地预览，不能重领。原子文件与旧代码154份的保存基线在本轮QA中逐个校验。匿名、极短或大量改写的文本无法可靠推断历史同源；完整书ID和原采集回执是优先身份依据，不能声称身份识别普遍完备。

## 使用方式

网页依次选择获取正文或已有来源、准备输入、检查章节范围，再启动后台文本创作；结果、阶段问题、历史停点、用量及绝对路径在同页查看。采集需要登录或验证时处理采集器环境，不能把另一个浏览器已登录当作采集成功。页面没有媒体或发布按钮。

CLI入口：`scripts/run_novel_adaptation_v1.py`，支持 `fetch/prepare/preview/inspect/execute`。以下仅为命令示例，不是本轮已执行的真实采集或生成：

```powershell
.\.venv\Scripts\python.exe scripts/run_novel_adaptation_v1.py fetch --book-name '目标小说' --chapters 1 --output-dir 'D:\IT\ai_douyin\data\novel_adaptation\acquisitions_v1\新的独立目录'
.\.venv\Scripts\python.exe scripts/run_novel_adaptation_v1.py prepare --acquisition-receipt 'D:\实际采集目录\RECEIPT.json' --run-dir 'D:\IT\ai_douyin\data\novel_adaptation\v1\新任务'
.\.venv\Scripts\python.exe scripts/run_novel_adaptation_v1.py preview --run-dir 'D:\IT\ai_douyin\data\novel_adaptation\v1\新任务'
.\.venv\Scripts\python.exe scripts/run_novel_adaptation_v1.py execute --run-dir 'D:\IT\ai_douyin\data\novel_adaptation\v1\新任务'
```

成功文本目录输出 `ANALYSIS.json`、`ADAPTATION_PLAN.json`、`SCREENPLAY.json`、`SCREENPLAY.md`、`FULL_TEXT_REVIEW.json`、`DIRECTOR_HANDOFF.json`与`OUTPUT_MANIFEST.json`。原始分阶段稿和原生响应另留，不手工拼接失败稿。交接包是本路线的结构化文本交付；本轮没有接管旧导演/分镜执行器，也没有生成新的分镜、人物图、视频或发布。角色卡是剧情选角，正式图像/声线映射仍在后续制作阶段。

## 实际验证与修复

主agent组合验收 **147项通过，35.87秒**，其中新路线115项、旧事件入口回归32项；包括2项真实Streamlit AppTest（页面运行测试，非浏览器采集/服务验证）。Ruff覆盖所有新增模块和测试通过。CLI帮助入口实际运行。证据：`data/qa/novel_adaptation_route_20261017/root_final_suite_v2.xml`。

首轮组合112项通过、1项失败，发现已存章节项目相对路径被错误拼到meta目录；已按明确路径规则修复并在上述终验中通过。保留首轮JUnit，不覆盖失败证据。此前主审和独立审查修复了引文字符计数负担、错类型聚合崩溃、已收响应中断后重复派发、原生坏结构导致证据丢失、服务URL安全与协议冻结、完成态隐藏产物、测试登记隔离、独立页账号依赖、真实章节范围被覆盖、旁白保留ID冲突、裁短旧稿逃逸及路径兼容问题。

本轮真实模型、浏览器采集、媒体和发布调用均0。离线假服务通过证明接线和停止/恢复行为，不证明实际MiniMax创作或DeepSeek审查质量。下一项真实验收应在有效任务授权与原来源/预算/停止记录核对后执行，不能把上次截断稿改写成已通过。
