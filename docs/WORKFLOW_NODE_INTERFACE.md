# 工作流节点接口与人工切换规范

## 目标

同一功能允许存在多种实现，但工作流只依赖稳定的“功能节点”，不直接依赖 Edge-TTS、LTX、WAN、SadTalker 等具体工具。具体实现由工作流配置选择，网页保存后由运行时解析。

当前配置文件是 `config/workflow_nodes.json`，管理页是“工作流节点”。配置使用 profile、revision 和原子写入，避免两个网页会话互相覆盖。

## 统一分层

1. `src/workflow/contracts.py`：定义端口、请求、结果、健康状态和执行器协议。
2. `src/workflow/catalog.py`：登记项目已有实现及其真实入口。
3. `src/workflow/selection_store.py`：保存多个 profile，并指定当前 profile。
4. `src/workflow/runtime.py`：业务入口只通过 stage 解析当前实现。
5. provider adapter：把旧函数/脚本转换成统一的 `NodeExecutionRequest -> NodeExecutionResult`。

节点返回值必须使用统一结果信封：

```text
NodeExecutionRequest
  run_id / node_id / stage / implementation_id
  inputs       稳定的阶段输入制品
  parameters   实现专属参数
  context      trace、缓存、审核等运行上下文

NodeExecutionResult
  success / status
  outputs      稳定的阶段输出制品
  metadata     模型、seed、耗时、hash 等可追溯信息
  error_code / error_message / retryable
```

同一 stage 的所有实现必须拥有完全一致的输入、输出端口。注册表会在启动/测试时拒绝接口不一致的实现。

## 当前模块盘点

| 功能节点 | 已登记实现 | 当前接入状态 |
|---|---|---|
| 大模型 | OpenAI compatible、Ollama、Mock | 已盘点；当前仍由 `.env` 选择并在重启后生效 |
| 配音 | Edge-TTS、GPT-SoVITS | 已支持热切换 |
| 背景 | ComfyUI/Flux、本地兜底 | 已支持热切换 |
| 成片主流程 | Presenter、双角色 FramePack、旧单人模板 | 已支持热切换 |
| 头像/口型 | Sonic、SadTalker、LivePortrait、MuseTalk | 已统一登记，专项脚本待 adapter 化 |
| 视频生成 | LTX、WAN、FramePack、Seedance 即梦、Seedance BytePlus | 已统一登记，专项脚本待 adapter 化 |
| 插帧 | RIFE、FFmpeg minterpolate | 已统一登记，专项脚本待 adapter 化 |
| 合成 | FFmpeg composer | 已登记，当前只有一个正式实现 |
| 发布 | Douyin Playwright | 已登记，当前只有一个正式实现 |

## 选择优先级

运行时按以下优先级解析实现：

1. 本次请求明确指定的实现；
2. 当前 active profile 的选择；
3. 注册表默认实现。

显式值 `workflow_default`、`current` 或空值表示跟随当前 profile。专项任务如果要保证可复现，应在运行清单中固化最终解析后的 `implementation_id`，不能只记录“current”。

## 后续迁移顺序

1. 把 LTX/WAN/FramePack 的提交、等待、产物发现统一为 `video_generation_request/v1 -> video_artifact/v1`。
2. 把 Sonic/SadTalker/LivePortrait/MuseTalk 统一为 `portrait_animation_request/v1 -> video_artifact/v1`。
3. 把 RIFE/minterpolate 的输入门禁和质量报告统一放入插帧 adapter。
4. 让 `video_control_plan` 输出逻辑节点与约束，让 runner 在执行时解析 profile；运行报告记录实际实现、版本、模型 hash 和参数。
5. 增加节点健康检查与网页试运行；健康检查不得自动切换生产实现，回退必须由工作流策略明确声明。

## 约束

- 网页切换只影响新任务，不改变已运行任务。
- 不允许 provider 在失败时静默换实现；回退必须写入结果 metadata 和审核报告。
- provider 专属参数不得进入通用端口；放在 `parameters` 中并带 schema 版本。
- 输出至少记录实现 ID、版本、输入 hash、输出路径/hash、耗时和错误码。
- profile 保存不修改 `.env`；需要密钥或模型服务变更的节点仍由环境配置管理。
