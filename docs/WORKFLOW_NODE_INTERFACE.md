---
doc_status: current
doc_category: workflow_contract
last_reviewed: 2026-09-04
---

# 工作流节点接口与人工切换规范

## 目标

业务工作流只依赖稳定的功能节点和版本化数据契约，不直接依赖某个模型或工具。
同一节点未来可以登记多个实现，由管理员在“工作流节点”页面切换；运行记录必须固化
实际实现，不能只记录 `current`。

## 统一分层

1. `src/workflow/contracts.py`：端口、请求、结果、健康状态和执行器协议。
2. `src/workflow/catalog.py`：当前允许选择的实现目录。
3. `src/workflow/selection_store.py`：profile、revision 和原子保存。
4. `src/workflow/runtime.py`：业务入口解析当前实现。
5. provider adapter：实现 `NodeExecutionRequest -> NodeExecutionResult`。

```text
NodeExecutionRequest
  run_id / node_id / stage / implementation_id
  inputs       稳定的阶段输入制品
  parameters   实现专属参数
  context      trace、账号范围、缓存和审核上下文

NodeExecutionResult
  success / status
  outputs      稳定的阶段输出制品
  metadata     模型、seed、耗时、hash 和来源
  error_code / error_message / retryable
```

同一 stage 的全部实现必须拥有完全一致的输入和输出端口。注册表在启动和测试时拒绝
契约不一致、重复 ID 或多默认实现。

## 当前模块状态

| 功能节点 | 当前选择 | 状态 |
|---|---|---|
| 热门样本采集 | 抖音授权页面采集 | 可切换，受来源策略约束 |
| 视频获取 | 页面元数据 | 可切换；授权本地媒体为候选 |
| 内容分析 | 轻量元数据分析 | 可切换；本地视觉/语音分析为候选 |
| 机会排行 | 可解释规则 | 可用 |
| 大模型 | OpenAI compatible | `.env` 管理，Ollama/Mock 已登记 |
| 配音 | Edge-TTS | 可与 GPT-SoVITS 切换，但输出只算音频制品 |
| 背景 | `disabled_pending_redesign` | 已重置 |
| 成片主流程 | `disabled_pending_redesign` | 已重置 |
| 人物驱动 | `disabled_pending_redesign` | 已重置 |
| 镜头生成 | `disabled_pending_redesign` | 已重置 |
| 插帧 | `disabled_pending_redesign` | 已重置 |
| 合成 | `disabled_pending_redesign` | 已重置 |
| 平台发布 | Douyin Playwright | 只允许人工发布已存在且已审核的 MP4 |

旧 Provider 不在当前候选列表中。任何显式请求旧实现都会解析失败；占位执行器统一返回
`VIDEO_PIPELINE_DISABLED`，且不会初始化模型、浏览器或账号环境。

## 视频 V2 接入顺序

1. 先确认法律号和小说号的目标样片、禁止样片及验收标准。
2. 冻结 `VideoProject/v2`、`ShotSpec/v2`、`ShotCandidate/v2`、`FinalVideo/v2`。
3. 以镜头为单位接入一个 Provider 候选，不能直接恢复旧整链路。
4. 完成可重复生成、输入输出 hash、自动质检和人工逐镜头审核。
5. 法律号与小说号分别通过样片验收后，才把实现加入目录供人工切换。
6. 合成与发布保持独立；生成测试不得访问抖音账号。

完整门槛见 [视频流程 V2 空白基线](VIDEO_PIPELINE_V2_BASELINE.md)。

## 约束

- 网页切换只影响新任务，不改变已运行任务。
- Provider 失败时不得静默换实现或输出占位素材。
- Provider 专属参数放在 `parameters`，不得污染通用端口。
- 输出至少记录实现 ID、版本、输入/输出 hash、耗时、错误码和审核状态。
- 账号相关节点必须通过 `AccountRuntimeContext`；纯生成节点不得请求账号上下文。
- profile 保存不修改 `.env`，密钥与外部运行时仍由环境配置管理。
