---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# 方案二实现细节：人物局部 2D 分层动效

> 日期：2026-05-10
> 可行性：高
> 预计工作量：2-4 小时（不含手工拆层）

## 核心思路

把角色 PNG 拆成 3-4 个独立透明层，每层独立做小幅动效：
- 身体层：静止不动
- 头发层：末端轻微摆动（1-2px）
- 头部层：轻微上下（1-2px）
- 袖口/衣摆层：轻微摆动（0.5-1px）

最终在 FFmpeg 或 Python/OpenCV 中逐帧合成。

## 素材准备

### 拆层方式

**方式 A：手工拆层（推荐，最干净）**

用 Photoshop 或 GIMP 把角色 PNG 手工拆成：
- `na1_body.png` — 身体 + 衣服（头部区域用背景填充）
- `na1_hair.png` — 头发（透明背景）
- `na1_head.png` — 头部特写（透明背景）
- `na1_sleeve.png` — 袖口/衣摆（可选，透明背景）

每层都是 RGBA PNG，尺寸与原图一致（1728x2304）。

**方式 B：自动拆层（实验性）**

用 OpenCV 肤色检测 + 轮廓分析辅助拆层：
```python
import cv2, numpy as np
img = cv2.imread('na1_nobg.png', cv2.IMREAD_UNCHANGED)

# 提取 alpha 通道确定人物区域
alpha = img[:,:,3]
body_mask = alpha > 128

# 上 30% 区域定义为"头部+头发"
# 30%-60% 定义为"身体"
# 60%-100% 定义为"下摆"

# 头发：alpha 在上身偏上 + 边缘毛刺区域
# 头部：alpha 在上身中心，圆形/椭圆形
# 身体：剩余躯干区域
```

不推荐方式 B——自动拆层容易在边缘产生裂缝，反而需要手工修。

### 拆层分辨率

建议在原分辨率（1728x2304）拆层，合成时再统一缩放到角色区域（540x960）。

## 逐帧合成实现

### FFmpeg 方案

每层用 `loop=1` 循环成视频流，分别加位移滤镜，再 overlay 叠加：

```python
def compose_layered_character(
    body_png,    # 身体层（静止）
    head_png,    # 头部层（上下 1px）
    hair_png,    # 头发层（轻微摆动）
    output_path,
    total_duration=31.56,
    fps=30,
):
    # 头部位移：sin 波 1px 上下
    head_filter = (
        f"loop=1:size=0:start=0,"
        f"setpts=N/FRAME_RATE/TB,"  # 保持帧率
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0:t=fill,"  # 占位，会被 overlay 覆盖
        f"[head_filter output]"
    )
    # 用 drawtext 做测试路径，实际用 Python 逐帧生成
```

**FFmpeg 限制**：难以做多层独立 sin 波叠加。推荐用 Python。

### Python 方案（推荐）

用 Pillow + OpenCV 逐帧生成：

```python
import numpy as np
from PIL import Image
import cv2

def generate_layered_motion(
    body_png, hair_png, head_png,
    total_frames, fps=30,
    head_amplitude=1.5,   # 头部上下幅度 px
    head_frequency=0.3,    # 头部振荡频率 Hz
    hair_amplitude=0.8,   # 头发末端摆动幅度 px
    hair_frequency=0.5,    # 头发振荡频率 Hz
):
    """
    返回每一帧的 RGBA numpy 数组。
    """
    body = np.array(Image.open(body_png))
    hair = np.array(Image.open(hair_png))
    head = np.array(Image.open(head_png))

    h, w = body.shape[:2]
    frames = []

    for i in range(total_frames):
        t = i / fps
        frame = body.copy()

        # 头部轻微上下位移
        head_offset_y = int(head_amplitude * np.sin(2 * np.pi * head_frequency * t))

        # 头发轻微横向摆动
        hair_offset_x = int(hair_amplitude * np.sin(2 * np.pi * hair_frequency * t))

        # 叠加头发层
        if hair.shape == frame.shape:
            # 头发放在头部上方，用 mask 混合
            hair_y_start = max(0, head_y_min - hair_thickness)
            hair_region = frame[hair_y_start:hair_y_start+hair_h, :]
            hair_layer = hair.copy()
            # 简单叠加（可优化 alpha 混合）
            alpha_mask = hair_layer[:,:,3] > 0
            hair_region[alpha_mask] = hair_layer[alpha_mask]

        # 叠加头部层
        if head.shape == frame.shape:
            head_y_start = max(0, head_offset_y)
            head_region = frame[head_y_start:head_y_start+h, :]
            head_layer = head.copy()
            alpha_mask = head_layer[:,:,3] > 0
            head_region[alpha_mask] = head_layer[alpha_mask]

        frames.append(frame)

    return frames
```

### 输出视频流

把每帧数组写成视频：

```python
import imageio

writer = imageio.get_writer(output_path, fps=30, codec='libx264', pixelformat='yuv420p')
for frame in frames:
    writer.append_data(frame)
writer.close()
```

或者用 OpenCV：

```python
out = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
for frame in frames:
    out.write(cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR))
out.release()
```

## 关键参数参考

| 动效 | 幅度 | 频率 | 备注 |
|------|------|------|------|
| 头部上下 | 1-2px | 0.2-0.4Hz | 模拟呼吸/点头，自然感强 |
| 头部左右 | 0.5px | 0.3Hz | 轻微摇头，可选 |
| 头发摆动 | 0.5-1.5px | 0.4-0.8Hz | 横向摆动，边缘细节 |
| 袖口摆动 | 0.3-0.8px | 0.5-1Hz | 纵向摆动，幅度要小 |

**原则**：幅度越小越好，>2px 就会开始显得"飘"。

## 与现有 video_composer.py 的集成

方案二生成的是**完整角色视频流**，而非静态 PNG。

集成方式有两种：

### 集成方式 A：生成角色视频片段后传入

```python
# 先生成带局部动效的角色视频（无背景）
role_a_video = generate_layered_motion(
    body_png='data/png/na1_body.png',
    head_png='data/png/na1_head.png',
    hair_png='data/png/na1_hair.png',
    total_frames=int(31.56 * 30),
)

# 用 FFmpeg 把角色视频叠加到背景
cmd = [
    'ffmpeg', '-y',
    '-i', 'data/videos/bg_loop.mp4',       # 背景
    '-i', role_a_video,                      # 角色（含动效）
    '-i', role_b_video,                      # 角色B（含动效）
    '-i', audio_a_path,
    '-i', audio_b_path,
    '-filter_complex', '[0:v][1:v]overlay=0:480[outv]',
    '-map', '[outv]', '-map', '[1:a]', '-map', '[2:a]',
    '-c:v', 'libx264', '-preset', 'fast',
    '-t', '31.56',
    'data/videos/dual_v11_layered.mp4'
]
```

### 集成方式 B：提供生成器函数接口

在 `video_composer.py` 中新增参数：

```python
def compose_dual_character_video(
    ...,
    layered_generator_a=None,  # callable，返回 (total_frames, generate_frame_func)
    layered_generator_b=None,
):
    # 如果提供了 layered_generator，用它生成角色帧
    # 否则退化为当前静态 PNG 方案
```

## 产出清单

- [ ] 角色 A 拆层素材：`na1_body.png`、`na1_head.png`、`na1_hair.png`
- [ ] 角色 B 拆层素材：`n3_body.png`、`n3_head.png`、`n3_hair.png`
- [ ] `src/content_factory/layered_motion.py` — 分层动效生成器
- [ ] 测试视频：`dual_v11_layered.mp4`
- [ ] 参数调优：头部幅度/频率，验证观感

## 风险点

1. **拆层不干净**：手工拆层耗时，边缘处理不好会有裂缝
2. **层间裂缝**：叠加时需要精确对齐位置，否则出现黑色缝隙
3. **计算量**：逐帧生成 30fps × 30秒 = 930 帧，Python 逐帧较慢，建议用 Cython 或直接生成视频流

## 推荐实施步骤

1. 先用 GIMP/Photoshop 手工拆 1 个角色（na1）的 3 个层
2. 用 Python 脚本只生成头部层 3 秒测试片段，验证效果
3. 确认效果后批量处理两个角色的所有层
4. 集成到 video_composer 生成完整视频
