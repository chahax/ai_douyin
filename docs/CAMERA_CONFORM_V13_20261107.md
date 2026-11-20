# 本镜视角校准（2026-11-07）

合法的房内相机不代表景别正确。原生静态计划可能写头肩近景，但 eye/target/fov 在目标处覆盖 3—8 米纵向范围。新 helper 只根据明确的拍摄选择解算镜头，不再让模型猜 FOV。

## API

```python
from src.content_factory import visual_camera_conform_v13 as camera

report = camera.conform_camera(raw_camera, desired_vertical_extent=1.4,
                               width=736, height=1312)
derived = camera.derive_plan(raw_static_plan_path, new_art_plan_path,
                             desired_extents={'F0002': 1.4},
                             width=736, height=1312)
camera.verify_plan(derived)  # 只读重算原始文件及全部计算审计
```

派生文件可直接作为 v13 的新 `first_frame_plan`。配置须绑定新文件真实 SHA。原静态计划、原生模型结果、原 packet、文本、音频与已成功 F1 均不修改。相同输出已存在时只允许内容完全一致；禁止覆盖不同结果或覆盖源文件。

## 计算定义

当前 CPU renderer 使用水平视角。设输出宽高为 W/H，d 为 eye 到 target 的三维欧氏距离，即光轴上的目标距离，V 为目标平面内沿图像纵向的覆盖范围：

```text
horizontal_fov = degrees(2 × atan((V × W/H) / (2 × d)))
achieved_V     = 2 × d × tan(horizontal_fov/2) × H/W
```

V 是明确的拍摄景别选择，不能由它反推演员身高、站位或小说事实。只改变水平 FOV，不平移 eye，不移动 target，也不移动演员。

每份报告保留 raw camera、原纵向覆盖范围、三维距离、尺寸/纵横比、目标 V、精确解和实际回算 V，以及原/新 camera 摘要。派生计划根 `camera_conform` 另外绑定源静态计划绝对路径、物理 SHA、内容 SHA、明确选择的镜头范围和每镜完整计算记录。`verify_plan` 重读源文件后重新计算，拒绝改 target、改静态描述、改审计值或换源文件。v13 每次持久读取含此派生元数据的静态计划时也会执行该只读核验，H3 消费相同；旧无此元数据的 F1 不增加该分支。

## 适用范围

仅 v13 本镜相机允许 12—110 度。canonical 房间 schema 仍为 35—110 度，原房间布局、资产和三机位不改。解小于 12 度或大于 110 度时报告无法在当前相机条件下满足，不钳位、不悄悄移动相机或目标。

v13 guide、可见 anchor 计算和 H3 的静态 guide 验证均使用同一本镜相机；它们不把 shot FOV 再交给 canonical 房间相机的 35 度下限。

## 验证

新 `tests/test_visual_camera_conform_v13.py` 22 项，与原 v13 静态合同 19 项联跑，最终 41 项通过、0 失败/跳过，16.13 秒：`data/qa/visual_camera_conform_v13_persistent_20261107.xml`。包括多种 V、横竖幅与三维距离、不可达范围、源/目标/文本/审计篡改、只改 FOV、保留未选镜头、消费时重核原文件与计算审计，以及真实 CPU 窄角 guide 到 H3 同图只读验证。

没有模型/GPU 调用，没有改现有图片、PLAN 或已审 F1。相机校准证明景别几何条件，不替代人物、姿态与成图视觉审核。
