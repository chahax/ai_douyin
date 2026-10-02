---
doc_status: current
doc_category: mainline
last_reviewed: 2026-10-02
---

# 系统架构

创作执行与账号运营分别组织。研究可作为创作输入；文本交接、媒体生成、用户审核和发布保持各自的
版本、回执及执行门，任何阶段的技术成功都不自动代替下一阶段的审核。

## 核心执行链

```text
原创简报 / 小说正文 / 已有视频分析 / 表达参考
        ↓ 冻结材料、逻辑任务和预算
候选与人物 → 导演简报 → 完整剧本生成与全文复审
        ↓ 用户可暂停、比较和反馈；返修回到责任阶段
整体导演安排 → 状态计划与分段分镜 → 请求编译和来源绑定
        ↓ 明确执行当前段
服务成功与文件保存 → awaiting_human_review → 用户决定
        ↓ 批准当前原片与服务原始尾帧后继续紧邻下一段
批准链合成 → 整片 awaiting_human_review → 用户整片批准
        ↓ 独立交付和明确发布
绑定账号浏览器发布 → 原作品独立核验 → 对应作品运营回接
```

## 模块与入口

| 边界 | 主要实现 | 职责 |
|---|---|---|
| 任务入口 | scripts/run_creative_workflow.py、creative_workflow_inputs | 材料、简报、逻辑任务登记及继承预算 |
| 文本编排 | creative_workflow、creative_full_script_revision、creative_segmented_director | 编剧/导演调用、完整新稿、文本审核和分镜安排 |
| 阶段控制 | creative_stage_runtime、creative_stage_contracts、creative_stage_debug | 同一运行器的自动/调试、冻结输入、版本、依赖和反馈 |
| 状态提交 | creative_state_store、creative_execution_control | 跨进程短提交锁、有序不可变命令、状态版本、派发许可和消费证明 |
| 媒体执行 | creative_media_workbench、creative_segment_execution、media_review_policy | 请求/候选来源链、预算、原 ID 查询、人工决定、批准链和合成 |
| 交付发布 | creative_delivery、DouyinAdapter、PublishWorkflow | 成片批准、账号核验、主动声明、提交锁和独立作品核验 |
| 质量证据 | creative_quality_evidence、creative_evaluation | 候选、人工金标、冻结留出、评分及原始用量 |
| 创作页面 | creative_workflow_dashboard、creative_workbench_panel | 复用共享命令/服务；部分计划与回执仍需 CLI 或路径输入 |
| 队列 | scheduler.queue、scheduler.runner | 原子领取、租约/心跳、未知结果与迟到提交保护 |
| 研究与运营 | operations_accounts、trend_intelligence、platform_adapter | 身份绑定、调研、趋势、机会、作品与评论回接 |

以上 creative 模块位于 `src/content_factory/`，页面位于 `src/web/`。准确代码链接及命令副作用
见[大模型导航](AI_PROJECT_GUIDE.md)。核心 runner 仍承载较多预算、验证与返修逻辑，F04 是继续拆分责任的增量工作。

## 状态与并发

文本和媒体执行锁避免同任务重复派发，崩溃遗留锁仍须对账；它们与 v23 的短状态提交锁不同。
短提交锁不跨模型等待持有，反馈、停止/恢复及运行器提交以同一命令顺序协调。
旧内存保存先重放已接受命令；返修只解决冻结请求真正消费的反馈，新反馈继续待修。

未决反馈失效下游并阻止新的文本或绑定媒体提交；在途响应保留，原媒体 ID 查询继续可用。
任务状态、产物版本、反馈和 resolution 可追溯，不通过删除回执或换目录恢复额度。

## 治理与历史

只有 `production_protocol=governed_production_v1` 的新任务绑定当前 v23 治理包；
该协议需要 `evidence_review_v6`。普通入口及旧任务的真实配置以参数和任务状态为准。
恢复不能更换已保存的协议、模型、提示词、审核版本或预算；源码/规则哈希不符时在调用前停止。

工作目录文档可维护，冻结治理包和其中的实现文档快照保留。
旧任务在原冻结环境恢复或只读；跨版本迁移和执行锁接管工具尚未提供完整操作闭环。

## 验证范围

核心流程和 F01 已有离线执行证据。完整工作台、真实内容质量和真实服务/媒体格式/浏览器发布
仍按 F02–F07 单独验收，见[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。
旧视频组合保留在[历史设计基线](VIDEO_PIPELINE_V2_BASELINE.md)及归档中，不能据代码存在恢复生产。
