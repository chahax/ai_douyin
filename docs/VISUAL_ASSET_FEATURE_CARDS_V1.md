# 素材特点卡与首版绑定

这层读取已有全局素材注册库，按精确ID和版本建立项目绑定。它不生成素材、不改旧INDEX/资产、也不派发媒体。

## 数据

- `BINDING_INDEX.json`：书籍、素材库根目录、明确选择、各角色/场景的特点卡与图片版本绑定。
- `cards/<entity_id>.json`：`description`、`features`、`wardrobe`、年龄依据、来源、每个view的asset_id/version/SHA。
- 人物特点是既有CAST_PLAN中精确摘取的脸型、发型、眼睛、体型与服装文字。`fact_age`与`visual_design_age`分开；原casting的灰背景、站姿、朝向相机等制图指令不进入`description`。
- 场景特点取所选版本注册记录中的`layout_design/spatial_layout/static_materials`，不套用别版本布局。
- 卡片是视觉设计资料，不冒称逐像素身份认证。Registry原candidate/reviewed状态原样保留。

## API

`prepare_binding(output_dir, *, library, book_id, cast_plan, selection, feature_terms=None)`

`selection`的`characters/places`均为实体ID到view选择的映射，每项明确`asset_id`与整数`version`。不会回退到latest或同名人物。返回`binding_prepared`及index绑定；缺素材/描述则返回`missing_notice`，并保存通知记录。

`resolve_segment(binding_index, *, actor_ids, place_id, angle_by_actor, place_views=('front','side'), approval_path=None, reference_limit=8)`

`actor_ids`须由调用者使用本段所有镜头的角色合集，不能只是首镜可见人物。返回顺序为各角色front+选定angle，随后场景图；包含独立图片与对应特点卡。调用者再追加真实首/尾帧及状态说明，并检查实际模型接线与总参考容量。当前默认给8张资产保留1个动态Guide槽。

缺失返回：`status=missing_notice`、`notification_required=true`、`model_dispatch_allowed=false`，以及实体/view、原因和补齐动作。调用方负责展示/持久化通知，不能收到缺失后继续派发或偷偷换人。

## 初版绑定确认

确认文件schema为`visual_library_binding_approval/v1`，需精确`binding_index={path,sha256}`、`approved_by`、非空文字列表`evidence`、完整`confirmed_entities`与`production_approved=false`。

候选角度须在`allow_candidate_assets`中逐个绑定`asset_id/version/sha256`作本轮选定确认。此确认不修改全局审核状态，不把候选改为生产通过。后续角色和素材版本未变时沿用该绑定；新角色需先在库中有对应图片和来源明确的特点资料。

## 本次数据入口

`scripts/prepare_visual_library_binding.py --output data/visual_asset_feature_cards/novel_canonical_20261112_v1 --default-novel-test`

本次默认绑定苏墨/叶南/叶西决的front、左右oblique（每段选择一侧），以及苏墨房间front v4、side v2。每段角色需求与剧情状态仍由新视频协调器负责。
