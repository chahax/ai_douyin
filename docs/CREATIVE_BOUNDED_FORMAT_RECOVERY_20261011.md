# 完整缺工具响应的单次格式恢复（2026-10-11）

用户授权：“可以采用修改测试生产”。本次只恢复选定487稿第二段的文本准备；第一段已获明确批准，第二段仍只允许一次视频提交，保存后等待人工审核。

## 原故障与证据边界

501收到HTTP 200、服务业务码0、完整响应、finish_reason=stop及6240 reported tokens，却没有指定工具调用。因此旧结果为 `interface_rejected / REQUIRED_TOOL_MISSING`，不能把普通正文转成已验收的原生文档。旧回执、原始字节、用量和整稿质量失败结论全部保留。服务端为什么未提交工具结果仍未知。

MiniMax[官方工具调用示例](https://platform.minimax.cn/docs/guides/text-m3-function-call)提供 `tools`，未给出强制 `tool_choice` 的保证。新入口保持MiniMax-M3、服务地址、thinking、温度、工具与内部合同，Writer省略 `tool_choice`，Director沿用原策略。这是一次兼容性试验，不是已证实的根因修复。

## 最小实现

- `creative_format_recovery_contract_v1.py`独立校验原回执、冻结账本身份、来源、原始响应和用量。只有完整且已知结果的缺工具故障可进入一次新身份请求；未知、截断、证据不完整、已恢复或已有媒体提交均阻断。旧正文保持不透明。
- `creative_bounded_format_role_clients_v1.py`保存SDK最终序列化的出站正文及哈希，独立保存入站正文，沿用严格响应验收。仅保存请求正文，不保存鉴权头。出站保存失败在发送前阻断；SDK重试为0。发送前Hook证明本地最终请求字节，不单独证明服务收到。
- `run_selected_script_continuation_v3.py`为独立入口，继承501次调用、7,701,556 reported tokens和既有未知记录。来源/阶段/前段视频组成全局恢复身份，不可变CLAIM登记防止换目录或重启再领一次；同阶段重复执行复用原回执。

新恢复不是采用501正文、手动拼接演法或重新派发未知任务。再次缺工具、结构失败、审查失败或结果未知均停在当前阶段，不自动再补一次。既有默认入口与旧冻结任务不迁移。

## 当前创作与视频边界

当前仅处理B1.S03/B1.S04：周姐说“流程都备好了，这张申请你照着签一下。”；小林看清原因栏“个人原因”。这几个字来自纸面视觉，不是周姐对白。纸笔保持周姐一侧，不提前推动、不加入质问或拒签，给识别冲突留出自然反应时间。

MiniMax须提交完整当前方向与表演新稿，确定性编译后由DeepSeek检查八项：源文、对白、起止状态、动作/对白时序、表演/机位、未来隔离、刺激来源通道、当前源事件完成。八项全过后才准备一次480p Seedance Mini原尾帧续段。接口成功、文本有效、文本审查、视频人工质量分别记录；不会据此宣称整片导演或创作质量完成。

## 验证与产物

集中离线验证记录：`data/qa/creative_bounded_format_recovery_20261011/OFFLINE_VALIDATION.json`。生产准备/调用账本：`data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v3`。实际视频（仅接口与保存成功后存在）：`data/video_generation/legal_script487_trial_20261011/second_v3`。本记录不提前表示生产成功；生产结论以该目录原回执和后续结果记录为准。

## 本次实际结论

22项集中离线验证通过；提交门补充兄弟旧段回执检查后，4项运行器回归通过。真实502调用正确返回工具，消耗6998 reported tokens，但新稿在`performance.actor_goals[1].reception_of_current_stimulus`和`performance.delivery`复写B1.S03原对白，遭本地合同拒绝。未进行DeepSeek审查、未提交第二段视频，恢复剩余次数0。详见[生产结果](../data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v3/PRODUCTION_RESULT.md)。本次未复现缺工具，不证明调用参数因果，也不构成创作质量通过。
