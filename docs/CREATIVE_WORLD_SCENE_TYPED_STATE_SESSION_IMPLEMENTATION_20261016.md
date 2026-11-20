# 独立类型化源状态核查入口

本实现依据 `CREATIVE_WORLD_SCENE_TYPED_STATE_TRACE_PLAN_20261016.md`，只接第20轮的一次必要DeepSeek诊断。旧663、原80项拒绝、八份失败正文、四格接口诊断和导演7/7完整保留；新入口不修旧路径、不复用旧模型pass作为验收。

新模块为 `scripts/creative_world_scene_source_state_audit_session_v2.py`，公共接口沿独立v1入口的 `Config`、`Session.preview/authorization_template/prepare/run` 和CLI四动作。新原生合同固定为 `scripts.creative_world_scene_source_state_audit_v2.prepare/validate`；父证明固定为 `scripts.creative_world_scene_source_audit_spend_anchor_v1.verify_anchor`。未知版本不能动态选择其他验证器。测试可注入有明确离线标记的假父证明，不能当真实祖先核验。

新scope、runtime policy、successor binding、RUN、intent、STATE和SUMMARY均明确标v2。公共冻结容器/TaskStore/原SDK证据沿既有v1存储格式，锁内有效额度独立限制为 `goal_plan=0, goal_audit=1, complete_script=0, full_review=0`，总调用上限1。没有 `TEXT_HANDOFF`、新规划、正文、媒体或发布入口。原source-audit1/1已耗尽作为历史显式继承，本次新授权不把它清零。

父663证明核实原始输入与645规划/650开场身份。新请求只取原规划、原开场和当前authority投影，完整R01仍按纯构建器携入一次；663原审查和主agent的失败分析仅作为冻结证据，不进入出站payload。新字段目录与类型化链由A的纯v2构建器产生，Session不重写其目录或模型输出。

模型与参数保持原663审查profile逐值、文件SHA和canonical SHA相同：DeepSeek、temperature 0.4、thinking disabled、goal_audit输出上限32000。与原创作profile的唯一历史差异仍为goal_audit 16000→32000，不是本轮再提高参数。

每次请求先登记TaskStore并领取，再由共享锁内检查当前计轮、冻结依赖、真实来源鲜度、精确配置、唯一父后继和重建request。SDK重试为0。原生完整且本地状态链明确冲突时保存完整原报告、合同决定、SDK raw/wire、SQL和实际成本，终态为已知内容失败；不能把原生语义pass覆盖本地拒绝。结构合同拒绝、未知/截断、缺工具或语义未知均结束本运行，不能触发第二次请求。

最小离线验收只有两条：实际安装SDK的MockTransport提交一个合同完整但本地状态链失败的合成报告，核完整保存和停止；另一个模拟运输未知，核单次发送、保留预留、无原生采用且RUN不能重启。合成报告不证明真实645的语义或事实抽取可靠；真实派发由主agent完成实际预览、冻结和单次运行。
