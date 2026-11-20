# 新生成输入空间隔离（2026-11-06）

显式策略 `geometry_materials_only/v1` 用于新的生产运行。旧运行、旧 H3 暂停和原生未知记录不改。

## 原因与输入

实际多机位试片曾把正面照片中的床与新机位 guide 的床合并成两床。相同房间完整照片仍有身份和审核价值，但不能同时承担新机位的空间生成模板。

新背景图只输入：本房本机位 CPU 几何 guide，加原已审 appearance bundle 的兼容裁片（最多 wall/floor/wood 三张）。裁片必须有独立的 `layout_free=true` 审核。完整 front 继续是版本/SHA 依赖及视觉审核参考，不进入生成 workflow 的 LoadImage。

新首图只输入：本镜 guide、实际入镜人物参考（原有最多两个人物语义上限）、兼容裁片。完整环境图仍在 SHOT_BINDINGS 中，供审核、版本失效和来源核验；只从生成输入中移除。

审核的家具实例上界由独立 v11 审核门从当前 layout 取值，盲观察只看实际目标图与类名。此文件的输入隔离证明与家具计数证明分别核验，两者都不能由模型自称通过替代。

## 显式继承与版本

`visual_generation_reference_v7.bind(origin_run, new_run, packet, base_config=None)` 是只读配置构造 API。新运行须是原运行的不同同级目录。返回配置包含策略和 `generation_reference_origin`。该 proof 精确绑定原三房 front 的 ID/版本/图片 SHA/审核 SHA/guide、完整组/源文/bundle/READY/crop，不绑定会随新图登记而变化的全库 INDEX 摘要。

原三张 front 只有精确身份、设计版本和审核/provenance 均吻合时可继承。所有新 view/首图必须保存新策略的输入角色/路径/文件 SHA、原生 PLAN SHA；持续复用时重新读取 PLAN/workflow/RESULT/STATE/HISTORY，并核实际 LoadImage 集合、原 native completion、输出 SHA。旧多机位图没有此证明，不获得新策略资格。默认无此显式策略的运行保持原行为。

带人物/镜头的新包须通过 `visual_continuous_stage_v6.validate_packet`，不能仅添加一个 stage_contract 字符串扩大源权限。借用原 style root 只读取已接受 bundle，不重新 source 审核、不复制修改旧 bundle、不对旧 front 贴新布局。

## 源文确认的桌子修订

固定稿 F0025 明确把面包放到旧木桌上，而旧苏墨房间 layout 没有 table。`add_source_table`/`validate_place_revision` 产独立 `source_bound_place_revision/v1`：核原文文件 SHA、精确字符区间、逐字 quote SHA；仅允许在原 table=0 的房间增加一个 table，全部原物件、门窗、房型及相机不动；新对象尺寸/位置单列为美术选择，完整碰撞检查后换新 design_version。

实际修订：`data/visual_asset_revisions/su_mo_table_20261106/REVISION.json`。来源 `CH01_SC02_P005_U01`，2703:2758，quote SHA `96a63b5ffa0c803d314fe4a19af6ca70770d82d5949a2705c515bf9d02ca1b6f`。桌子尺寸 0.90×0.55×0.74m、中心 [3.35,1.70] 是明确美术设计。苏墨旧 front 因新设计版本失效，须新生成；孩子房/厨房和作为 style master 的孩子房保持精确继承。

adapter 用 `asset_revision` 层绑定原 stage packet 与修订 artifact 的物理 SHA；原 27 个 native staging 及原稿不覆盖。这不是冒充 native planner 新返回。

## 验证边界

`tests/test_visual_generation_reference_v7.py` 使用临时 HTTP 原生协议夹具和 CPU guide，测试真实 workflow 输入隔离、fullfront 保留依赖、首图人物保留、旧图失效、原生记录/文件篡改拒绝、source revision 精确范围和碰撞拒绝。它证明代码/来源门，不能替代新图或新视频的实际视觉验收。真实 GPU 生成由主代理独立执行和核图。
