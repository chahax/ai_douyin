# 分类规则与精简审核：实施说明

更新：2026-09-28。对应[问题归因与修改规划](VIDEO_PRODUCTION_ROOT_CAUSE_AND_CHANGE_PLAN_20260928.md)。本次完成代码更新与离线验证；未调用付费模型或媒体接口，未声称新剧本或视频生产已经通过。

## 1. 使用范围与版本

新增显式协议 `governed_production_v1`，在现有原创事件编剧、MiniMax创作/DeepSeek审核、`evidence_review_v6`基础上启用。选择参数为 `--production-protocol governed_production_v1 --review-policy-version evidence_review_v6`，通过现有 `scripts/run_creative_workflow.py`运行。标题、已确认简报、全新run-dir及调用预算仍由实际任务确定；本文不自动提交调用。

默认入口保持现状，已有任务沿用绑定版本，恢复不能切换协议。新协议绑定 `whole_film_action_plan_v2`、`focused_review_packet_v1`和[规则快照v4](../data/creative_governance/20260928_v4/artifact_manifest.json)。新入口每阶段校验工件与12个运行源码hash；修改实现后需另建明确版本，不自动让旧任务使用新规则。

## 2. 已落实的修改

| 范围 | 实现 | 真实边界 |
|---|---|---|
| 规则治理 | 注册表Schema、来源/字段/检查器、优先级冲突、生命周期、阶段选择及不可变绑定 | 10条已盘点规则，非全库盘点；7条确定性active、3条语义proposed |
| 动作与切点 | action v2唯一切点锚，动作/对白必须完成；身体朝向和坐下前空间关系；跨镜首末态校验 | 文字暗含动作或错误空间配置仍需语义及图片审核 |
| 不可表达需求 | 模型可以返回含真实源路径的unsupported响应；源路径、原因和hash保存到停止回执 | 模型声称冲突本身未自动判真，但不会强制改剧情以适配Schema |
| 精简审核 | 原字段映射到去重来源、重复原文片段无损共享，保留最终prompt独有内容；每项明确结论 | 尚未证明模型理解该表达后的漏审率和误报率 |
| unknown | 审美/实际媒体待验可带标记继续；关键语义需复核；缺源/冲突/不兼容禁止交接 | 未知不算通过；blocked不能由无证据签字覆盖 |
| 局部修复 | 原稿hash、有界补丁、空间字段允许范围、无变化停止、后续镜头依赖清单 | 仍保守整稿重编译和语义审核，未宣称精准局部复核省费 |
| 交接与恢复 | 原始响应、输入、提示词、处置、展开和人工复核回执核验；这些工件进入交接manifest | 必须经过原有实际助手阅读全文审核；程序不会替助手批准 |
| 评测与成本 | 样本清单、阈值配置、召回/误报/unknown、样本分母、缓存/费用/延迟/人工记录 | gold/holdout不足；费用缺项为null，不能报告实际节省 |

## 3. R01—R03如何处理

- R01：结构化视线操作仍为权威，审核包同时保留对白表演、动作文字、首末态和最终prompt。模型必须核对是否在文字中提前改变视线；没有使用“抬眼”等关键词假装理解语义。
- R02：`cut_after_event_id`和`completion_condition`由程序检查，早于未完成对白/动作的锚被拒绝。camera/cut_reason自由文中的另一个切点仍是明确语义审核对象，格式通过不代表此问题解决。
- R03：`spatial_contract.seats`给出可坐侧位置与必要朝向，sit必须在组开始前满足；同组移动/转向不能倒填前提。缺证据明确unknown，不能凭站姿就批准。配置是否忠实实际布局仍需看图。

## 4. unknown与恢复操作

新审核首次只调用一次；格式失败、响应未确认或required unknown均保留回执，恢复不会偷偷再发同一请求。若格式失败需要再次模型尝试，应另登记明确修复任务与预算，目前没有自动格式补证循环。

需复核unknown可以由助手实际阅读全文后提交 `<stage>__focused_resolution.json`。协议为 `focused_review_resolution/v1`，绑定 `context_sha256`和`raw_review_sha256`，必须 `reviewed_by=assistant`、`reviewed_full_text=true`；逐项resolutions包含check_id、明确status、reason、真实evidence_ids和issue_ids，新增问题列入additional_issues。只有原unknown项允许改，已知failed不能借此改pass；完整审核对象重新校验，再进入原助手gate。该文件不得由程序填造通过。本轮生产目录没有创建任何通过复核，只在测试临时目录使用了明确标注的假客户端样本。

blocked原因（含非规范大小写）仍阻断人工覆盖。原始审核不改写，派生展开记录人工复核文件hash；交接后删除或改动复核文件也会在恢复时失败。

## 5. 工件与验证入口

- [规则、Schema、P1工件和评测数据manifest](../data/creative_governance/20260928_v4/artifact_manifest.json)
- [规则盘点](../data/creative_governance/20260928_v4/rules.json)
- [评测配置](../data/creative_governance/20260928_v4/eval_config.json)
- [样本与实际缺口](../data/creative_governance/20260928_v4/dataset_manifest.json)
- [质量成本报告](../data/creative_governance/20260928_v4/quality_cost_report.md)
- [P2来源完整性及字符测量](../data/creative_governance/20260928_p2_v2/packet_diff.json)
- [统一回归JUnit](../data/qa/governed_protocol_release_20260928_junit.xml)
- [本轮发布检查回执](../data/qa/governed_protocol_release_20260928.json)
- [隔离恢复回执](../data/qa/governed_protocol_release_20260928/rollback_receipt.json)
- [规则迁移与旧版保留](../data/qa/governed_protocol_release_20260928/rule_migration.json)
- [修复路由工件](../data/qa/governed_protocol_release_20260928/repair_routing.json)

离线验证规则包（不会调用模型）：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/manage_creative_governance.py verify --output data/creative_governance/20260928_v4
```

CLI的build只允许新目录，不应覆盖已冻结版本。v1—v3为本轮早期冻结快照，保留审计，当前实验入口绑定v4；P2独立工件使用p2_v2。

最终统一回归420项通过，另有隔离旧任务恢复测试1项通过，共421项、0失败；全部使用离线/假客户端。本轮统一测试覆盖原工作流、动作v1/v2、状态计划、补丁、审核证据、精简审核、规则治理和新协议集成。具体数量、命令、失败项由JUnit和发布回执记录，不能拿这些测试证明创作质量已经过关。

## 6. 已测改进与未达门槛

在上一轮真实审核输入上离线重建：77,001 → 50,122字符，下降34.91%；计划与分镜的241/241语义叶保留，最终生成prompt完整可还原。只省略已有结构化正文对应的显示Markdown。字符不是tokens；没有新增真实审核调用，因此没有真实费用、延迟或质量收益结论。

目前28个候选案例、0个人工批准gold/holdout；R01—R03属于同一故事，不能当三个独立来源家族。80个独立样本、40个保留样本、重复评测、新简报及边界需求生产试验均未达到或未执行。评测工具按缺口阻断准入，不会自动填满样本或启动240次付费调用。

P0已交付范围内的可检查工件，但不是全仓库规则盘点完成。P1—P3完成本轮代码与离线验证，P4完成工具而未完成真实质量验收，P5完成实验入口及文档同步而未批准默认生产升级。

后续应先人工核定已有候选样本并补齐独立样本，再在明确预算内进行少量审核对照与新简报生产。图片、视频、声音和口型仍按原逐段实际审核流程执行；《玄关一步》的特殊授权不跨序列继承。
