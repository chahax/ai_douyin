# LivePortrait 本地头肩动画模式

## 适用范围

LivePortrait 只用于无手、无手机入画的头肩镜头，例如眨眼、视线轻移、轻微点头和表情变化。可见手或手机时，优先使用确定性合成；不要依赖提示词要求生成模型锁住手部。

## 本机安装

- ComfyUI 节点：`D:\IT\AI_vido\ComfyUI\custom_nodes\ComfyUI-LivePortraitKJ`
- 模型目录：`D:\IT\AI_vido\ComfyUI\models\liveportrait`
- 检测器：MediaPipe CPU
- 运行模式：`micro_motion`
- 后处理：FFmpeg `minterpolate` 到 30fps

当前 Python 3.14 环境使用 MediaPipe Tasks API。节点内已做最小兼容修改：

`D:\IT\AI_vido\ComfyUI\custom_nodes\ComfyUI-LivePortraitKJ\media_pipe\mp_utils.py`

不要执行节点原始 `requirements.txt` 的 NumPy 降级。当前环境保留 NumPy 2.x，只补装 `pykalman` 和 `scikit-base`。

## 固定参数

| 参数 | 值 |
|---|---|
| 源图 | 轻微三分之二侧脸，头肩构图 |
| 手/手机 | 必须完全出画 |
| 驱动帧数 | 49 |
| 原始 FPS | 16 |
| `dsize` | 512 |
| `scale` | 2.3 |
| `lip_zero` | `true` |
| `stitching` | `true` |
| `delta_multiplier` | 0.35 |
| `relative_motion_mode` | `relative` |
| `driving_smooth_observation_variance` | 0.00001 |
| 发布 FPS | 30 |

如果动作过大，只调整 `delta_multiplier`，推荐范围 `0.20–0.45`。不要同时换驱动视频、检测器和裁剪参数。

## 本机通过样例

原始输出：

`D:\IT\AI_vido\ComfyUI\output\liveportrait_test\xiaojie_3q_micro_v3_00001.mp4`

30fps 输出：

`D:\IT\AI_vido\ComfyUI\output\liveportrait_test\xiaojie_3q_micro_v3_smooth30.mp4`

门禁清单：

`D:\IT\ai_douyin\data\qa\liveportrait_xiaojie_3q_micro_v3.control.json`

门禁报告：

`D:\IT\ai_douyin\data\qa\liveportrait_xiaojie_3q_micro_v3.control.report.json`

可复用 ComfyUI API 工作流：

`D:\IT\ai_douyin\docs\examples\liveportrait_headshot_micro.api.json`

验收结果：

- 704×1248
- 30fps
- 89 帧
- 2.967 秒
- 全局亮度范围：0.543
- 全局色度范围：0.357
- 背景活动像素比例：0
- 质量门禁：通过

## 调度规则

1. 先检查构图是否有手或手机。
2. 无手、无手机的头肩镜头选 LivePortrait。
3. LivePortrait 只生成脸部运动，再合成回原图。
4. 原始 16fps 通过画面门禁后，才允许插值到 30fps。
5. 30fps 成片重新执行 `video_control/v1`。
6. 任一光线跳变、背景活动或脸部漂移超限时拒绝，不进入配音和总合成。
