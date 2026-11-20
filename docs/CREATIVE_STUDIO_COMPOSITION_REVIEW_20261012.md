---
doc_status: offline_implementation_complete_live_unverified
doc_category: implementation_review
last_reviewed: 2026-10-12
runtime_scope: independent_offline_creative_studio_v1
---

# 可恢复组合工作台：实施与审查交接

用户要求先保存当前内容、持久记录，再由子 agent 开发、主 agent 审查到本轮开发完成；如果后续内容不满意，主动提醒可恢复。开发前范围见[组合计划](CREATIVE_STUDIO_COMPOSITION_PLAN_20261012.md)，后续继续工作的长期上下文见[持久记录](CREATIVE_STUDIO_PERSISTENT_CONTEXT.md)。

本轮交付是独立离线后端：空间合同、真实参考编译接线、SQLite持久任务图、提供者Schema门、完整请求预览和恢复工具。没有安装整套第三方平台，也没有改变MiniMax创作、DeepSeek少量全文审查的分工。新CLI没有真实派发命令；这轮完成不表示整片自动生成或创作质量通过。

最终验收：351项相关离线回归全部通过（293.72秒），实际CLI的prepare、两次status、preview、recover及禁止重复prepare已核对。工作区有1个已完成的本地空间编译claim，0个付费claim；重启不重复编译，原7/7和旧冻结链保持。

## 已保存且可以恢复

开发前基线：`D:\IT\ai_douyin\data\development_checkpoints\creative_studio_baseline_20261012`。

- `BASELINE_CODE_AND_CONTEXT.zip`：1907个代码、测试、文档和选定当前全文/研究文件，SHA256为`9d52278e03b2897b40fd238ebd8fcdf0ae8fbf0f9c094796434bb178967dfa5d`。
- `BASELINE_MANIFEST.json`逐文件校验；3294个原生产文件在开发后仍须保持原哈希。
- `restore_verification_copy`已实际解压并校验。恢复工具只允许新建工作区内的独立目录，不覆盖现有工作区、回执或账本。
- 媒体、凭据、环境和完整旧生产数据保留在原位置，不包含在这个代码/上下文ZIP中。

如果用户认为组合后的内容或效果不合适，后续助手须主动提醒：**可以选择旧入口，或从此基线建立旧版工作副本。** 恢复代码不等于撤销已派发服务请求，不重置消耗或候选数量。

## 实际接线

| 模块 | 本轮已实现 | 实际范围和边界 |
| --- | --- | --- |
| 空间与引用 | `creative_studio_reference_previs_v1.py` | 米制坐标、稳定人物/道具/结构ID、显式存在/离场、当前持有与支撑、镜段/时间、摄影机、跨镜同一空间合同；调用现有v4 reference compiler，真实图像字节可进入导演请求预览 |
| 任务持久化 | `creative_studio_task_store_v1.py` | SQLite事务、派发前唯一claim、原服务ID恢复、revision/attempt隔离、来源变更令下游失效、已知用量不可回退、继承授权改名不清预算 |
| 能力桥 | `creative_studio_provider_bridge_v1.py` | 原始MCP tools/list字节与Schema快照绑定、模型/模式/引用顺序/任务查询/用量/终态字段核验；保守构建离线预览，未接live派发 |
| 整合入口 | `scripts/run_creative_studio_v1.py` | 只读核对实际512/513与518–520冻结链，建立独立DAG、保存完整导演请求和SDK body、status/recover及可选提供者预览 |
| 恢复 | `scripts/restore_creative_studio_baseline_v1.py` | ZIP/逐文件SHA核对，路径与重复文件保护，只向新独立目录解压 |

依赖图已注册为：源全文 → 空间/导演参考 → 整片导演 → 局部表演 → 确定性编译 → 全文制作复审 → 视频 → 用户审核。源导入只代表原证据已核对；空间和参考编译完成只代表各自合同可读，不能写成人工审美采用。

空间预演及原有全文、R01参考全文、返修错误对象进入同一个导演请求与SDK body预览。空间为助手提出的离线样例时显式标注`provisional=true`、`production_adopted=false`，不会改原全文或把位置猜测写成服务原生帧。

选图必须覆盖当前演员和场景，重新读取原素材、原采用记录及当前性别/外观映射。仅编译`media_payload`时会保存媒体参数，但导演参考节点仍未完成；只有`director_messages`实际添加图像后才完成该本地编译节点。头像、全身、场景、原尾帧和声音仍分别核验，图片不能证明声线。

## 主agent审查与独立复验

审查推动修复了空间仅存文件但未进入请求、旧引用未重核对当前选角、MCP快照未完整冻结、SQLite图/来源/节点类型可以被改绑、媒体参数被误计为导演图像，以及本地claim统计写成零等问题。

Blender会给重名显示标签追加`.001`。导出现在额外保存`entity_id`/`structure_id`/`camera_id`及`scene_id`/`segment_id`，后续不按显示名认人物。新旧失败测试回执都保留，不删除首次失败记录。

专属任务库66项与独立组合4项通过；包含真实多进程竞争、进程中断、数据库重启、原ID查询、迟到结果、用量冲突、7/7范围保持及媒体人工审核门。能力桥48项加已有能力预检/SDK回归147项通过。空间专属补强后63项通过。整合和恢复独立20项通过，媒体载荷不能领取导演claim的定向补强1项通过。最终合并回归结果和实际CLI存证以[最终验收JSON](../data/qa/creative_studio_composition_20261012/FINAL_VALIDATION.json)为准，不将重复运行数量相加成独立质量样本。

独立任务库审查报告：[INDEPENDENT_TASK_STORE_REVIEW.md](../data/qa/creative_studio_composition_20261012/INDEPENDENT_TASK_STORE_REVIEW.md)。所有测试使用离线夹具；新服务调用、媒体调用和发布均为0。

本地Blender 4.5.14已实际保存同一会议室两个静态机位，逐项复核每镜25个稳定对象的位置、尺寸、朝向、单位和摄影机。目录：`data/qa/creative_studio_composition_20261012/local_previs_r2`，内有两张PNG、`.blend`、声明、实际对象导出及`GEOMETRY_VERIFICATION.json`。这是空间白模；第1机位裁切人物代理顶部，需要未来正式机位重设。没有脸、服装、表演、运动、碰撞或生成视频遵循的验收结论。

## 入口和产物

当前工作区：`D:\IT\ai_douyin\data\creative_studio_workspaces\legal_scene_20261012_v1`。

本轮新代码、文档、验收与工作区快照另存`data/development_checkpoints/creative_studio_release_20261012_v1`；这份开发后副本与开发前基线分别保留。不是独立可部署的完整运行环境，凭据和原生产历史仍按原位置绑定。

重要文件：`SOURCE_SNAPSHOT.json`、`SOURCE_PROOF.json`、`DAG.json`、`SCENE_SEQUENCE.json`、`PREVIS_SEQUENCE.json`、`FULL_MODEL_REQUEST_PREVIEW.json`、`SDK_WIRE_BODY_PREVIEW.json`、`TASKS.sqlite3`、`WORKSPACE_MANIFEST.json`、`INITIAL_STUDIO_STATUS.json`。

```powershell
.\.venv\Scripts\python.exe scripts\run_creative_studio_v1.py inspect
.\.venv\Scripts\python.exe scripts\run_creative_studio_v1.py status
.\.venv\Scripts\python.exe scripts\run_creative_studio_v1.py preview
.\.venv\Scripts\python.exe scripts\run_creative_studio_v1.py recover
.\.venv\Scripts\python.exe scripts\restore_creative_studio_baseline_v1.py verify --check-protected
```

默认工作区已建立时不能再次`prepare`覆盖；后续输入或代码变化应使用新工作区，原工作区的输入、源码哈希及原回执保持原身份。原未知任务恢复只建议查原ID或对账，不允许重新派发。

## 当前剧情与未解决问题

仍是512《桌面那张纸》：公司让小林离开，纸上却写“个人原因”；小林问明公司立场并两次拒签，周姐改为请他帮自己交差仍未成功。周姐收回未签纸笔放进文件夹，独自离开；小林留坐，争议未结束。此次没有手改正文、没有重写对白或结尾。

最新生产累计520次/7,964,215 reported tokens；518–520均是完整且用量已知的排时合同拒绝。导演候选7/7、剩余0，没有可采用的新整片导演、表演或制作交接。历史70/160未知及93,117预留保持。新工作区只记录本地编译，不给导演增加候选。

后续主要缺口：

1. 正式空间与现有实际人物/场景素材、声线绑定仍未完成，白模不能代替角色资源；几何约束也不能保证Seedance逐帧遵循。
2. 导演排时的15秒限制与源内容分组仍需真实新计划验证；目前诊断传递已离线修复，当前7/7不能因新目录重新计数。
3. LibTV live工具Schema、实际账号及精确模型能力尚未取回。现在提供的是能力门和预览，不能声称LibTV生产接通。
4. 任务库记录外部授权和normalized结果；真实派发前仍需可信SDK适配器把原始响应、实际出站证明、用量和源身份接入。没有以普通正文关键词判断任务完成。
5. 这是后端CLI，不含新的画布UI；默认v23和旧冻结入口未迁移。完整作品的文本质量、实际视频表演及自动运营效果还没有通过本轮验证。

下一次继续时先读本交接和持久记录，再核对当前范围与原账本。正常代码/文本审核和范围内MiniMax调用不逐次申请；视频仍由用户审核，保存成功仅为`awaiting_human_review`。
