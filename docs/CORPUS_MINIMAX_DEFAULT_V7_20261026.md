# 新小说流程固定 MiniMax-M3.1-Flash（2026-10-26）

用户要求：“再换minimax哪个可以用直接后续固定使用”。已将新版完整章节生产入口和番茄 corpus 工作流的新任务固定为 **MiniMax-M3.1-Flash**。不是只改实验脚本，也没有把旧失败任务改成新模型运行记录。

| 工作 | 新任务使用模型 |
| --- | --- |
| 完整原章与完整邻章 → 分类材料；必要材料返修 | MiniMax-M3.1-Flash |
| 材料独立复核 | 本机 Qwen3.5 9B |
| 跨章框架、本集人物与状态细化、场景视觉设计、事实合同、完整编剧 | MiniMax-M3.1-Flash |
| 框架、快照、设计的前序复核及责任定位 | 本机 Qwen3.5 9B |
| 最终全文内容与时长审查 | DeepSeek，沿既有配置 |

材料阶段仍先分类，不要求提前输出人物实体表或知情、持物状态数组。细节进入本集快照之后再组织。模型换新没有取消任何原文来源、完整性、语义复核或时长门。

## 接入范围与兼容

- 新增 `src/content_factory/corpus_production_v7.py`、`corpus_scope_v7.py` 和 `minimax_production_client_v1.py`；材料、快照和内容合同沿用已冻结 v6。
- `scripts/run_corpus_production.py prepare` 和 `scripts/run_fanqie_corpus_workflow.py` 新 JOB 默认 v7。原 v3—v6 PLAN/JOB 仍按自己的版本派发。
- 新分类阶段明确记为 `materials`，来源外发授权检查移到首次分类之前。CLI 新增 `materials` 命令；`local` 仅保留兼容别名，v7 下实际模型以冻结计划为准，不再暗示本地分类。
- M3.1 固定 adaptive thinking、medium 思考、16384 输出上限（包含思考），不发送不支持的关闭思考或 JSON 模式；原生响应、实际模型、实际有效参数完整入账。零自动网络重试，无供应商回退。
- 全局旧配置与旧网页生产入口未迁移；不能把这次新 corpus/Fanqie CLI 默认接线称为所有旧入口统一升级。没有重启账号后台。
- 接口行为已核对 [MiniMax 官方文档](https://platform.minimax.cn/docs/api-reference/text-chat-openai)：M3.1 不接受关闭思考，支持 reasoning_effort。使用现有已验证端点，账单未独立核验。

## 本轮真实结果

使用此前已共享的合成《两把钥匙》完整三章、399 字符。不是实际小说69章。调用通过永久 v7 路由和生产账本执行；第一章 messages 与上一轮失败 Qwen 请求逐字相同，输出上限与模型思考策略不同，不是严格单变量对照。

**真实 MiniMax 3 次，38.687 秒，11116 reported tokens；全部 stop、pending=null，无格式返修。** 三章均通过格式和原文绑定；16 项事实、16 条精确引文、15 个自然段均保留。亲属关系、黄铜/木钥匙、未说出口的计划、实际交接、父亲原先不知情、孩子第一次发现信与父亲后来获知均有材料依据。

主助手逐条对照原文审查，仍发现需要语义修正的部分：

1. CH2-F003 将“现在说话”和“明早开柜子的计划”合在一项，整项标为 plan/later，时间范围不够明确。
2. CH3-F004 描述“阿禾现在告诉父亲”，却以话中“昨天交钥匙”为依据标 earlier；CH3-F005 已另外正确保留父亲当前获知，不能说知情事实完全遗漏。
3. CH2-F001 的临时场景信息附带 world 标签偏宽。

因此结论是：**M3.1 已可作为新任务固定生成模型，接口与引用小样通过；这批材料语义仍需复核修正，完整自动产稿尚未验收。** 本次没有运行 Qwen 材料语义复核或 DeepSeek 终审，没有生成快照、完整剧本或视频。没有手改模型输出冒充返修成功。

## 验证与证据

404 个不同测试通过，覆盖适配器原生请求、错误/用量记录、首次外发范围、旧版本分流、未知不重派、完整章节保存、状态与全文合同，以及使用模拟原生响应的全链集成。模拟全链不等于实际模型完整产稿。

第一次测试因临时目录环境失败而未执行用例，原 XML 保留；改用项目内测试目录后验证通过。69 份旧源码及旧实测文件 SHA 不变，完成后的重复读取无新调用或改写。

- 实测目录：`data/corpus_production_trials/20261026_v7_minimax_default`
- 原生请求/响应：该目录 `run/materials/CALL_*.json`、`RESPONSE_*.json`
- 主审：该目录 `PRIMARY_REVIEW.json`
- 验收：`data/qa/corpus_m31_default_20261026/ACCEPTANCE.json`
- `RUN_TRIAL.py` prepare/execute 和源码迁移脚本均已一次执行，不重跑；旧失败和旧真实小说外发审批记录保持。
