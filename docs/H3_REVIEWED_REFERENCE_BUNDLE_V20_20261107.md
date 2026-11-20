# 按本镜收集已审核人物与环境参照

实现：`src/content_factory/visual_h3_reference_bundle_v20.py`。

当前旧入口是`visual_asset_pipeline_v3`生成并审核组合首图，再由`visual_h3_handoff_v3`只传首图。新收集接点位于资产PLAN里的分镜之后、组合首图之前，直接读取具名已审资产，保留跨段稳定参照；不会把尾帧当唯一身份或环境来源。

## 接口

```python
from src.content_factory.visual_h3_reference_bundle_v20 import collect, validate

bundle = collect(asset_run, shot_id, expected_book_id=book_id)
current = validate(bundle)  # 返回当前相同证据包；缺失、候选、过期或篡改则报错
```

两个接口均只读。没有注册、导入、审核、图像生成、提示词生成、模型调用或写状态的动作。`ReferenceBundleError`继承`ValueError`。

## 收集范围

按本镜`visible_cast`顺序，为每个角色选择当前设计版本的已审`front`作为稳定身份参照，再选择`character_views`指定的本镜精确视图。两者为front时合并同一角色槽的用途。场景随后选择本镜`place_id`的已审front和`place_view`，既保留稳定房间外观，也保留本镜对应的环境视图。

不按`scene.cast`把所有场内人物加入，不为画外声、内心声或旁白增加演员图，不要求全书所有人物或每人九图全部进入本镜。缺少canonical front时明确拒绝，不能用本镜某张侧面图冒充全局身份。角色无论是否同脸，均按独立entity/view保留槽位，不按像素SHA合并双胞胎。没有“两人＋场景”限制，也没有偷偷裁减超量引用；实际视频模型的槽数和模型权重能力由新适配入口单独验证。

技术layout图不充当已审核摄像机画面；带布局的场景须使用该布局实际定义的机位。若源packet提供scene列表，还核对分镜是否仍在对应物理场景与人物范围内。

## 输出协议

schema为`reviewed_h3_reference_bundle/v20`。`references`是给视频适配入口的有序引用数组：

```json
{
  "reference_id": "character:role_id:front",
  "entity_id": "role_id",
  "display_name": "角色名",
  "kind": "character",
  "view": "front",
  "proof_id": "asset_id:v1",
  "asset_id": "原库资产ID",
  "version": 1,
  "design_version": "v1",
  "identity_group": "稳定身份组",
  "image": {"path": "绝对原图路径", "sha256": "图像SHA"},
  "roles": ["canonical_identity", "shot_character_view"]
}
```

环境角色用途为`canonical_environment`和`shot_environment_view`。顶层`characters`按具名角色关联canonical/shot引用ID；`environment`关联当前scene/place及front/机位引用ID。`source_shot`绑定源分镜ID、scene/place、原分镜摘要、visible_cast和视图选择。`source`绑定原文文件SHA，`asset_plan`绑定原资产PLAN，`packet_sha256`绑定原packet。

`asset_proofs`为每张入参及其传递依赖保留资产版本、输入SHA、图像SHA、具名scope、原资产记录和审核记录文件、accepted审核ID、原审核结果摘要、源manifest/源文绑定以及依赖指纹。传递依赖可能包含双胞胎canonical父角色或同住宅风格母场景；它们只作为证据，不自动成为新的图片输入或新增入镜人物。

全包以`bundle_sha256`绑定。`validate`重新读取当前库、原审核及依赖，旧候选、后续新版本、同图新审核、源文或原图变化均不能继续沿用旧包。收集前后核对INDEX有无并发变化，但不把整个INDEX绑定进结果，因此无关角色新增不会使本镜过期。

## 不授予的资格

返回值的`media_generated/prompt_rewritten/production_approved/publication`均false；`model_capacity_checked=false`。这些字段不否定已审资产的图像资格，而是防止把“证据齐全”偷换成“视频生产或成片审核已通过”。此模块不会输出新的机位、节奏、对白或构图指令。实际原提示词和引用说明的组合由独立v20适配模块负责。

## CPU验证与真实只读样例

用例：`tests/test_visual_h3_reference_bundle_v20.py`。小图与审核回执是明确的CPU协议fixture，不是假称真实视觉审核。覆盖只读、不依赖组合首图、准确视图、canonical强制、候选/审核未知拦截、跨书、SHA/审核篡改、依赖版本过期、源分镜/场景、空镜与画外声、同像素独立角色及无关资产隔离。

实际F0012只读收集结果在`data/qa/h3_reference_bundle_v20_20261107/ACTUAL_F0012_READONLY_BUNDLE.json`，顺序为苏墨front、叶西决front、苏墨房间front、苏墨房间side。它证明当前已有资产和审核数据可被收集，不证明新的ReferenceToVideo检查点或视频结果已验收。本次没有修改生产库、生产PLAN/STATE、原hold或正在渲染的S03。
