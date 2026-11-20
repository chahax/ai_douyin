---
doc_status: offline_implementation_complete_live_unverified
doc_category: implementation_plan
last_reviewed: 2026-10-12
---

# 可恢复的空间、参考与任务编排组合开发

用户授权：先保存目前内容、持久记录，再按工具研究建议组合开发；子 agent 开发、主 agent 审查直到本轮开发完成。如果随后内容不满意，主动提醒可恢复基线。本轮完成目标是新独立离线生产工作台后端，实际接线与故障验证；不以开发指令重新授予已耗尽导演候选或媒体调用。

完成结果：独立后端已实施，主agent审查及独立复验完成；351项最终相关离线回归通过，实际CLI工作区已建立并验证重入不会新增claim。本地Blender两个机位的稳定ID、对象位置/尺寸/朝向和摄影机已实际核对。详情、具体接入边界、当前7/7及恢复入口见[实施交接](CREATIVE_STUDIO_COMPOSITION_REVIEW_20261012.md)。此状态只代表本轮开发范围完成，live服务、有效导演/表演与创作质量仍未通过。

## 保存与长期导航

基线：`data/development_checkpoints/creative_studio_baseline_20261012/BASELINE_CODE_AND_CONTEXT.zip`，1907 个代码/文档/测试及选定当前全文和研究文件，SHA256 `9d52278e03b2897b40fd238ebd8fcdf0ae8fbf0f9c094796434bb178967dfa5d`。`BASELINE_MANIFEST.json`逐文件校验，并保护3294个原生产文件。不是全盘备份：媒体、凭据、环境与旧生产数据留在原处。

持久记忆采用本文件、AGENTS.md入口和最终交接文件；不声称存在额外账户永久记忆。恢复默认解压到新独立目录，不删除/覆盖账本和冻结回执。旧入口保持可选择。开发开始前已经校验ZIP所有文件与哈希。

## 组合方式与范围

从公开实现借机制，独立编写小型适配模块，不部署整个第三方画布，不复制受限源码。研究身份和许可见 `data/qa/libtv_ecosystem_fit_20261012/FIT_ANALYSIS.json`。MiniMax创作、DeepSeek少量全文复审、确定性编译和用户视频审查继续由本项目控制。

1. 参考 Open Storyboard/DirectorDesk：统一米制坐标、稳定人物/道具/场景ID、显式起态与摄影机、跨镜空间关系。实现本项目自己的可移植空间合同与Blender预演导出，不冒充已兼容`.director`或物理模拟。未提供的位置不得从文本猜成事实；可用明确标注的离线样例测试。
2. 参考 Open Storyboard/infinite-canvas：引用按实际请求顺序编号、主体角色映射、首尾帧与一般参考模式互斥，已有原生资格/人工批准单独绑定。接现有reference compiler，不把三视图/几何代理当合格人像。
3. 参考 TapCanvas：SQLite持久执行图、节点revision与attempt、派发前唯一claim、重启读取原任务ID、迟到结果隔离、来源变更向下游失效。已提交/结果未知禁止再次派发；已知结果的内容返修仍需原范围和新身份。保留旧结果及用量，不转写旧生产账本。
4. LibTV官方Remote MCP：只实现实际schema/能力证据导入和资格门，未发现live工具时明确不可派发。session自然语言客户端与Pro完成关键词不作为可靠媒体提交/完成协议。
5. 主agent新增独立CLI，完成上述模块的同一工作区接线、请求预览、只读现有源导入、模拟服务故障和恢复验收；旧冻结`.py`文件不修改。默认v23和既冻结v5不自动迁移。

## 模块任务与接口

空间/引用模块：`src/content_factory/creative_studio_reference_previs_v1.py`。提供`validate_scene(scene, manifest)`、`build_previs_bundle(scene, manifest)`、`compile_reference_projection(binding_contract, selected_asset_ids, *, mode, **kwargs)`。场景输入自己的`creative_studio_scene/v1`合同，显式实体pose、场景bounds、camera及来源状态。导出白模脚本/结构，不需要付费服务。参考接口返回原编译结果与按序角色清单，不自己制造资格。

持久任务模块：`src/content_factory/creative_studio_task_store_v1.py`。`TaskStore(db_path)`；注册冻结DAG、读取状态、claim、记录原服务task ID、接受完整原回执、重启恢复建议、revision失效。详细签名由实施agent写模块docstring，主agent集成。所有操作事务化；完整未知或known failure保留原回执，迟到结果只能进入历史，不写当前有效输出；unknown taskID建议reconcile，unknown无ID停止。不能操作旧账本或擅自新增额度。

能力桥模块：`src/content_factory/creative_studio_provider_bridge_v1.py`。实际MCP工具snapshot与资格声明按SHA绑定；构建请求时必须明确model/mode/reference/task查询/终态/用量/原尾帧能力，否则返回具体缺口。无需网络，不构造凭据，不硬编码不存在的LibTV工具名。原模型客户端继续走已有preflight。

主agent入口：`scripts/run_creative_studio_v1.py`（inspect/prepare/preview/status/recover；默认不提供真实生成dispatch）；接真实冻结512/513源与既有只读失败诊断。输出`STUDIO_STATUS.json`、空间/引用预览、DAG及继承范围摘要；当前7/7不得伪装可开始导演/视频。有资格的未来阶段以接口扩展，不在本轮假造成功。

## 完成判据

- 保存、校验并试解压恢复基线到独立目录；不覆盖旧数据。
- 同一入口真实调用新模块；不能只交互不接线。
- 离线模拟验证唯一claim、提交断线、未知无重派、原ID恢复、迟到结果、来源失效、并发claim、SQLite重启、schema不全、参考次序和空间缺失。
- 真实当前源导入仍保持7/7和原文/旧冻结哈希；失败520仅诊断展示、不采用为导演；本轮新增付费0。
- 主agent审查修复后，独立agent复验；记录明确测试范围、仍未接的live MCP、真实视频遵循与创作质量。
- 更新长期导航、交接、默认恢复提醒。开发完成不等于完成可用整片导演/视频，当前故事不人工拼接。
