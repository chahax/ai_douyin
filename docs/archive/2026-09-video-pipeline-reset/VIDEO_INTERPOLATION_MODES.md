# 视频插帧模式

## 可用工具

本机现在有两条独立插帧路径：

1. FFmpeg `minterpolate`
2. ComfyUI 核心 `FrameInterpolate` + RIFE 4.26

RIFE 模型位置：

`D:\IT\AI_vido\ComfyUI\models\frame_interpolation\rife_v4.26.safetensors`

可复用 API 工作流：

`D:\IT\ai_douyin\docs\examples\rife426_interpolation.api.json`

## 固定规则

- 插帧不能修复原视频中的手指、手机、脸部或背景变形。
- 原始视频必须先通过动作和光线门禁。
- 插帧完成后必须重新执行 `video_control/v1`。
- FFmpeg 和 RIFE 都通过时，使用 `video_candidate_benchmark/v1` 自动排名。
- 不因为 RIFE 是神经模型就默认优先。

## 本机实测

测试输入：

`D:\IT\AI_vido\ComfyUI\output\liveportrait_test\xiaojie_3q_micro_v3_00001.mp4`

候选结果：

| 候选 | FPS | 门禁 | 分数 |
|---|---:|---|---:|
| FFmpeg minterpolate | 30 | 通过 | 93.835 |
| RIFE 4.26 | 30 | 通过 | 93.040 |
| 原始视频 | 16 | 通过 | 88.008 |

本镜头推荐 FFmpeg 版本。RIFE 的亮度波动略小，但整体画面更暗、参考外观距离更大，因此没有获得推荐。

推荐视频：

`D:\IT\AI_vido\ComfyUI\output\liveportrait_test\xiaojie_3q_micro_v3_smooth30.mp4`

RIFE 备选：

`D:\IT\AI_vido\ComfyUI\output\liveportrait_test\xiaojie_3q_rife426_smooth30.mp4`

统一报告：

`D:\IT\ai_douyin\data\qa\liveportrait_xiaojie_3q_benchmark\liveportrait_xiaojie_3q_fps_compare.benchmark.json`
