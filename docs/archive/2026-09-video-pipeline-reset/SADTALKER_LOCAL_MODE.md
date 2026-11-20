# SadTalker 本地音频驱动模式

## 结论

SadTalker 已在本机跑通，但能力边界必须固定为：

- 只用于单人、无手入镜的头像或头肩口型视频。
- 输入优先使用正脸或轻微三分之四侧脸。
- 输出是 `256x256` 方形头像源，不得拉伸为全身人物。
- 不得把方形输出直接套用全身 alpha 遮罩。
- 光线和颜色需要经过 `ColorMatchV2`、去闪烁和质量门禁。

无音频的眨眼、表情微动继续首选 LivePortrait；可见手、手机或全身人物继续使用确定性合成、FramePack 或 Wan Animate 分层方案。

## 本机组件

- 程序：`D:\IT\SadTalker`
- Python：`C:\Users\c\.conda\envs\sadtalker\python.exe`
- 主模型：`D:\IT\SadTalker\checkpoints\SadTalker_V0.0.2_256.safetensors`
- 裁剪映射：`D:\IT\SadTalker\checkpoints\mapping_00229-model.pth.tar`
- 人脸对齐：`D:\IT\SadTalker\gfpgan\weights\alignment_WFLW_4HG.pth`
- 人脸检测：`D:\IT\SadTalker\gfpgan\weights\detection_Resnet50_Final.pth`

为兼容当前环境，SadTalker 本地源码做了两处最小修复：

- GFPGAN 改为启用增强器时再导入，普通生成不依赖可选增强器。
- 修复 NumPy 已移除的 `np.float` 和新版数组标量转换。

## 已验证命令

```powershell
$env:TEMP = "D:\IT\SadTalker\.codex_tmp"
$env:TMP = $env:TEMP
C:\Users\c\.conda\envs\sadtalker\python.exe inference.py `
  --driven_audio D:\IT\SadTalker\examples\driven_audio\chinese_poem1.wav `
  --source_image D:\IT\AI_vido\ComfyUI\input\liveportrait_xiaojie_3q.png `
  --checkpoint_dir D:\IT\SadTalker\checkpoints `
  --result_dir D:\IT\SadTalker\results_codex `
  --size 256 `
  --preprocess crop `
  --still `
  --expression_scale 0.6 `
  --pose_style 0 `
  --batch_size 2
```

实测输出：

`D:\IT\SadTalker\results_codex\2026_07_25_16.26.30.mp4`

规格为 `256x256`、`25 fps`、`136` 帧、`5.44` 秒、H.264/yuv420p。首中尾帧光线稳定，人物身份基本保留，动作集中在眼睛和嘴部。

## 自动选型

在 `video_shot_intent/v1` 中增加：

```json
{
  "motion": "micro",
  "framing": "head_shoulders",
  "audio_driven": true,
  "contains_hands": false,
  "contains_phone": false
}
```

该组合推荐 `sadtalker`。只要出现手或手机，推荐器仍强制回到 `deterministic_2d_compositor`，不会因 `audio_driven=true` 放宽物体稳定性要求。

## 验收

```powershell
.\.venv\Scripts\python.exe scripts\video_control_audit.py `
  data\qa\sadtalker_xiaojie_audio_test.control.json `
  --output data\qa\sadtalker_xiaojie_audio_test.control.report.json
```

门禁检查：

- 全局亮度和色度漂移。
- 脸部必须有可见动态且不能大面积变形。
- 左侧背景必须保持静止。
- 技术元数据必须可探测。

