# 静态首图 v13（2026-11-07）

F0001 首图实际只输入了 guide、苏墨站立全身图和三张风格裁片，却生成两个卧躺人物及画边站人。原请求同时要求宽房 guide、文字中近景和多时刻动作，还把两个画外孩子的名字放进图像提示。这里记录输入污染和构图冲突的程序修复，不把 CPU 测试当作模型视觉已修好。

## 新显式入口

旧配置和旧 PLAN/packet 保持。新运行增加：

```python
config['first_frame_contract'] = 'static_start_identity_roi/v13'
config['first_frame_plan'] = {'path': absolute_still_plan, 'sha256': physical_file_sha}
```

要求同时使用 `geometry_materials_only/v1`。外部计划结构：

```json
{
  "schema": "first_frame_static_plan/v13",
  "source": {"path": "与原 packet 完全相同", "sha256": "原文文件 SHA"},
  "packet_sha256": "fingerprint(当前单镜 scope packet)",
  "shots": [{
    "shot_id": "F0001",
    "shot_sha256": "fingerprint(原动态 shot)",
    "visible_cast": ["su_mo"],
    "static_start_prompt": "English description of one still instant, containing only the visible subject.",
    "camera_override": {"eye": [1.4, 2.05, 1.15], "target": [0.65, 2.8, 0.6], "fov": 38},
    "camera_design_note": "A shot composition choice, not a source-novel measurement."
  }]
}
```

`camera_override` 和 `camera_design_note` 可省略。根级可保存原生 `planning_provenance`。entry 其余字段拒收，防把整段动态材料串进图像请求。原 shot、音频和原动态 `visual_prompt` 不重写；H3 继续使用它们。静态计划的物理 SHA、原 packet/shot SHA、实际资产 binding SHA 全部进入新作业与首图回执。

## 人物和空间输入

每个入镜人物只从其当前正式 reviewed canonical front 裁一张连续头肩/上胸图。沿已审 face ROI 通用扩展为横向 2.5 倍脸宽、顶部向上 0.25 脸高、底部到 2.25 脸高；裁片若可能包含过大身体范围则停止。不是从未审核 face/clothing candidate 取图，也不把脸图与全身图同时输入。

苏墨真实 face ROI 为 x307/y30/w139/h165，对应新裁片 x203/y0/w347/h401。只复制真实源像素；不补画、提亮、拼接或把候选升级。CROP.json 独立绑定原 front 身份/版本/图 SHA、原 source_review 与事件 SHA、脸 ROI、实际像素 ROI 和 crop SHA；每次复用重新裁原图比对。

首图仍输入本镜 guide 和兼容风格裁片。新相机只在同一房间合法范围内取 eye/target/fov，检查非退化及镜头不落入家具实体。它不改 canonical 房间或已审三机位资产。新 CPU guide 的 source-place/layout/renderer/camera/static-plan/binding/PNG 均冻结。相机正向说明和视觉审核的可见 anchors 同时由该相机计算；画外桌、灯、窗不作为必须看见的下界。

`visual_first_frame_static_v13.preview_guide(entity, view, camera, path, width=736, height=1312)` 可生成纯 CPU 构图预览。实际生产 guide 会另建本 run 的正式绑定。生成、审核和 H3 读取同一 guide，不在只读 H3 验证阶段生成或修复缺失文件。

## 验证与边界

最终针对性测试 `tests/test_visual_first_frame_static_v13.py`：19 项通过，0 失败/跳过，18.78 秒，XML `data/qa/visual_first_frame_static_v13_targeted_20261107_r3.xml`。包含实际像素裁切比对、临时 HTTP 原生作业、动态与画外材料不进静态 graph、H3 原动作/音频保留、camera/plan/guide/crop 篡改拒绝和只读验证不重建。

本模块开发没有模型/GPU 请求，没有覆盖旧生产运行。guide 仍通过图像 reference 输入模型，不能当成硬性人体姿态控制；实际首图须再次核对人数、身份、躺姿和房间，再进入 H3。
