# 本地 AI 视频光线控制方案

## 先判断问题类型

| 问题 | 首选工具 | 是否重新生成 |
|---|---|---|
| 原图光线正确，动画后人物色温漂移 | `reference_appearance_lock` | 否 |
| 人物和背景整体色调轻微不一致 | `ColorMatchV2` | 否 |
| 固定镜头只需要来信光、粒子、灯光呼吸 | Pillow / FFmpeg 确定性合成 | 否 |
| 把人物替换到另一段动态背景并继承环境光 | Wan Animate Replacement + Relight LoRA | 是 |
| 整段已有视频需要重新设计光源 | RelightVid / Light-A-Video | 是，研究型流程 |
| 故事板单图在动画前就需要重打光 | IC-Light | 是，只处理静帧 |

## 当前项目默认策略

### 1. 原图已经好看

不要让视频模型重新决定光线。使用：

```text
Wan Animate Move
→ SAM2 人物蒙版
→ 静态背景回贴
→ reference_appearance_lock
→ 质量门禁
→ 30 fps 插值
```

`reference_appearance_lock` 以生成视频首帧为运动锚点，只提取后续帧相对首帧的变化量，再叠加到原始故事板人物上。人物身份、基础色温、方向光和背景因此保持原图状态。

动作增益：

- `0.20–0.35`：强力锁定，输入变化主要是色漂时会接近静帧
- `0.45–0.60`：当前微动作默认区间，实测推荐 `0.55`
- `0.70–0.80`：动作更明显，实测 `0.75` 仍通过门禁
- `>1.00`：容易把生成模型的色漂和形变完整带回来

当前同一镜头实测：

| 增益 | 门禁 | 色度范围 | 人物活动比例 | 手机手部活动比例 |
|---|---:|---:|---:|---:|
| 0.55 | 通过 | 0.159 | 0.0171 | 0.0867 |
| 0.75 | 通过 | 0.243 | 0.0290 | 0.1122 |

默认选择 `0.55`，只有人工认为动作太弱时才升到 `0.75`。

### 2. 真正的人物替换

只有人物要进入另一段背景视频时，才使用 Wan Animate Replacement 和官方 Relight LoRA。ComfyUI 官方文档说明 Mix/Replacement 模式用于保留原视频环境和光色；Move 模式只做动作迁移。

本机已经安装：

```text
D:\IT\AI_vido\ComfyUI\models\loras\Wan22_relight\WanAnimate_relight_lora_fp16.safetensors
```

当前宿舍镜头实测出现红紫色漂移，因此 Relight LoRA 不能作为固定必过步骤，必须经过色度漂移门禁。

## 可选开源工具

- [Wan2.2 Animate 官方 ComfyUI 工作流](https://docs.comfy.org/tutorials/video/wan/wan2-2-animate)：Move 与 Replacement 两种模式。
- [IC-Light](https://github.com/lllyasviel/IC-Light)：适合先重打光故事板静帧，不建议逐帧独立处理视频。
- [RelightVid](https://github.com/Aleafy/RelightVid)：有时间一致性的视频重打光推理代码，但部署和模型链更重。
- [Light-A-Video](https://github.com/bcmi/Light-A-Video)：训练免费的视频重打光研究实现，支持 Wan2.1，但不是当前 ComfyUI 直插节点。

## 验收顺序

1. 先看首、中、尾帧色温是否一致。
2. 再检查人物与背景的方向光是否冲突。
3. 检查手、手机和脸是否变形。
4. 通过后再插值；不要用插值掩盖光线漂移。
5. 所有候选必须写 `video_control/v1` 清单并运行质量门禁。

当前真实测试与推荐视频见：

`data\qa\wan_anti_fraud_relight_v1\README.md`

自动执行和 Hermes/Claude Code 交接规范见：

`docs\VIDEO_RECIPE_MANIFEST.md`
