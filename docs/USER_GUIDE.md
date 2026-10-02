---
doc_status: current
doc_category: mainline
last_reviewed: 2026-10-02
---

# 操作指南

先确认本次是新故事还是恢复同一任务，并确认用户已授权的调用范围和预算。
研究、文本、媒体、审核和发布分别执行；分析或预览不会自动触发生成与发布。
详细执行要求见 [AGENTS.md](../AGENTS.md)及[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。

## 文本创作与分段调试

1. 在“创作空间 → 双角色剧本”选择小说、已有原视频分析或原创简报，填写来源和参考路径。
2. 新任务冻结材料并登记预算；已有任务从原运行目录恢复，不能换目录或修改预算领取新额度。
3. 查看剧本与导演安排，在阶段调试区运行下一阶段、指定断点或停止后续派发。
4. 对当前输入/输出版本提交原话反馈。`must_fix` 阻止下游，`suggestion` 留档；当前页面自动传递所见版本哈希。
5. 恢复时先到最早未解决责任阶段返修，再重建失效下游。运行中新增反馈也会保留；已有响应不自动解决未消费的反馈。

页面目前不是完整的治理协议配置入口。新原创普通入口通常使用已实现的 v5 文本审核，
新治理任务需在 CLI 明确选择 `governed_production_v1` 与 `evidence_review_v6`；旧任务沿用原绑定。
完整文本派发前预览仍属 F02，不将差异查看称为完整预览已完成。

### 只读检查与局部控制

在项目根目录运行；将路径替换为实际已有任务。以下命令不调用生成模型或媒体生成服务：

```powershell
$runDir = 'D:/IT/ai_douyin/data/creative_workflows/实际任务目录'
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir inspect
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir compare --stage writer_script
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir stop
```

`resume` 只解除停止意图，不单独启动模型执行；继续文本还需页面或 `run_creative_workflow.py`
按原材料和原参数恢复。stage_id 以 inspect 的实际记录为准，具体示例见[阶段调试](CREATIVE_STAGE_DEBUGGING.md)。

## 单段视频与用户决定

1. 文本审核及反馈门满足后，编译当前剧本/分镜为媒体预览，查看实际请求和来源绑定。
2. 使用 `creative_workbench.py prepare-segment` 准备当前单段计划；首段绑定首帧依据，续段绑定紧邻前段人工批准的服务原始尾帧。
3. `run_creative_seedance_segment.py preview` 查看本段实际请求。用户制作授权与预算支持时，显式 `submit` 当前段。
4. 有原任务 ID 时使用 `query` 续查；结果未知且无 ID 时先对账。不要新目录重发。
5. 保存成功后，用户播放并给出决定，程序仅记录技术成功和 `awaiting_human_review`。
6. 从当前回执登记候选，再记录用户原话及 approved/rejected。不通过时可按秒点和实际证据定位责任阶段，返修后才另行生成。

当前页面已有预览、启动单段操作和用户视频决定，但单段计划、保存目录和候选回执仍需输入路径。
完整无内部路径的准备/续段操作链尚待 F02 完善。

助手不主动抽帧、听看、ASR 或调用音画审核模型。只有用户明确批准，且原片、回执和原始尾帧身份仍匹配，
才允许继续下一段。计划切镜使用另外经过批准的新机位首帧，同时保留前段批准依据。

## 合成与发布

批准顺序、原片和版本链核对后，通过 `assembly-chain` 建链，显式 `assemble --execute`
采用原音轨生成整片候选。合成成功再次等待用户整片审核，不能从逐段批准推断整片已批准。

完整成片的 `segment_id=final` 人工批准回执可用于 `prepare-delivery` 生成交付预览。
核对账号、标题、简介、AI 主动声明要求与虚构前缀后，按发布授权显式执行 `publish --execute`。
随后用 `verify-publish` 核验原作品；待核验保留提交锁，不能重传。
`collect-operations` 只回接对应账号与作品，缺失指标保留 null。

页面的交付入口仍要求完整成片审核回执路径；准备、合成、交付等准确参数见
[大模型导航的命令表](AI_PROJECT_GUIDE.md#执行入口与副作用)和各脚本 `--help`。

## 异常与额度

- 正常断点与用户停止可按原目录恢复，不清零预算。
- 审核待核实、未决 must_fix、unknown 或预算不足先解决对应原因，不用调试按钮绕过。
- 进程异常留下文本/媒体执行锁时，核对旧进程、原请求 ID 和原回执。当前没有完整的锁接管工具，不能直接删除锁重发。
- 治理源码哈希不符时，旧任务在原冻结环境恢复或只读。导航更新不授权将历史任务改绑 v23。
- 新剧本按既有登记入口建立独立计数；同稿恢复和返修累计失败。缺少真实任务的授权或信息时继续可完成的只读核对。

## 研究与运营

账号绑定、登录健康、授权只读调研、标签趋势、机会排行及发布后复盘继续保留，
可作为创作输入或独立操作。退役视频组合与历史样片不能作为当前默认生成能力。
