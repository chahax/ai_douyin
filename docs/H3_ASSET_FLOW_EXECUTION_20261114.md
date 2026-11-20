# H3 新状态流程的实际视频执行

用户于 2026-11-14 请求“生成视频”，本轮接续前一天的离线输入编排，生成当前一分钟修正版。运行目录为 `data/video_generation/h3_asset_state_revision_minute_20261114_v1`。保留原 S01/S02，重新生成 S03/S04；原媒体、未知任务和旧 PAUSE 不改，不发布。

## 已接入的执行层

`src/content_factory/h3_asset_flow_execution_v1.py` 和 `scripts/run_h3_asset_flow_execution.py` 消费已校验的离线包，提供 `prepare / launch-request / submit / collect / status`。

1. 重算离线工件，读取当前原文、状态、全段角色/环境绑定和真实前段尾帧。
2. 使用固定版本的 `h3_asset_prompt_profiles_v1.apply`，把结构化状态转成自然表演说明；保留每镜视线、同一身体和全部原句，显式加儿童声线描述。只有 `condition.prompt` 改变，技术实例 ID 不渲染成台词或画面标签。
3. 以新运行目录的独立 scope 暂存全部九张原图。逐张校验源和暂存文件 SHA、mtime、RGB；图片标签板只供检查，不送模型。
4. 冻结实际 PLAN、输入清单、staging receipt 和 workflow；保存 Root 技术确认后仅提交一次。REQUEST/CLAIM 先于 POST 写入。
5. 按原返回 UUID 获取 history/queue，校验实际图后保存 video、audio、first、last 四份原件。超时或未知结果不自动重派。

当前执行版限定本地 `127.0.0.1:8190`，与前段原计划的输入/输出目录、GPU 锁和旧 PAUSE 保护一致。没有服务重启、flags 变更或新的模型下载。

## 声音与状态的实际范围

本轮没有已确认的儿童音色样本，因此显式使用 `prompt_only` 和原生音视频。固定文字声线来自 `VOICE_PROFILES_V2.json`，没有 LoadAudio 或参考音频输入，不代表声纹固定。

前一天新增的音色库、固定版本绑定和离线音频参考编译能力仍保留。此执行版没有接入 `voice_required` 的真实音频暂存；它会拒绝音频参考包，不能把这次视频说成音色资产线路已生产验收。

结构化状态保留同一角色实例、身体归属、位置、姿态、视线和持物。当前 run 的尾帧观察与 S04 初态由代理实际查看原图后整理，不冒称已经实现独立于代理的自动视觉状态提取。全局旧后台默认线路没有迁移。

## 本次生产中的窄修正

S03 实际尾帧保存后，才准备 S04。女孩劝阻的镜头改为女孩与同一个蓝衣哥哥合镜，手腕/松手动作仍在后镜，未增加坐立变化或重攥拳动作。

首次 S04 派生源只经过状态模块校验，新增的旧格式 `pose` 注释不是原文精确子串，被完整离线编译拦截，未调用模型。Root 另存修正版，仅将不参与表演渲染的 `pose` 改为原上下文中的“叶东在弟弟身旁”；原文、台词、动作、时窗和状态资料不变。失败候选、通知与后续完整编译结果全部保留。状态 ready 不能代替完整 `compile_spec` 验证。

当前原件目录 `ORIGINALS.json` 在 S04 尚未提交时进行了明确版本更新，原 V1/V2 全字节保存在 `catalog_history`，采用记录为 `CATALOG_V2_ADOPTION.json`、`CATALOG_V3_ADOPTION.json`。S03 已提交输入和原源文件未变；不能通过覆盖旧 source 或 native PLAN 修补记录。

## 收存与交付

- `collect_original.py`：固定原 UUID、30 秒 GET-only、最多六小时；临时 GET 错误留证据后重取，绝不 POST。
- `observe_original.py`：有限 websocket 进度记录；不调度任务。
- `finalize_state_revision.py`：核验原两段与本轮新两段，真实 CPU 抽帧，按 4×362 帧合片，最终 QA 可显式执行仅新两段的 ASR。旧两段不重转录；ASR claim 未结算时拒绝盲重跑。

最终目标文件为 `H3_ASSET_STATE_REVISION_MINUTE_736x1312.mp4`，预期 736×1312、24fps、1448 帧、约 60.33 秒、48k 双声道。以实际 `FINAL_RESULT.json` 和 `FINAL_QA.json` 为完成依据，不能用本文或工程测试代替成片验收。

本次源/执行/收尾代码和工程证据分别保存在 run 及 `data/qa/h3_asset_prompt_profiles_v1_20261114`、`data/qa/h3_asset_flow_execution_v1_20261114`。代码通过测试不保证模型不会增人、串衣、加字幕或偏移对白时序；实际抽样观察与用户审片结果另行记录。
