---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# 方案四实现细节：ComfyUI / AnimateDiff 轻动画

> 日期：2026-05-10
> 可行性：中（取决于 ComfyUI 是否已部署）
> 预计工作量：1-2 小时（不含 ComfyUI 部署）

## 核心思路

把角色图送入图生视频模型（ComfyUI / AnimateDiff），生成 3-5 秒轻微动态片段，循环使用。适合效果：
- 轻微呼吸起伏
- 眨眼
- 头发微动
- 衣服轻摆
- 轻微镜头运动

片段可复用：同一切片可以循环使用多次，不需要每次重新生成。

## 前置条件

### ComfyUI 已部署

如果还没有部署 ComfyUI，建议先安装：

```bash
# 克隆 ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI.git

# 安装依赖
pip install -r requirements.txt

# 下载官方模型（AnimateDiff 或 SVD）
# AnimateDiff: civitai.com 模型
# Stable Video Diffusion: stability.ai 模型
```

### 必要模型

| 模型 | 用途 | 文件大小 | 推荐 |
|------|------|---------|------|
| `sd_xl_base_1.0.safetensors` | 基础文生图模型 | 6.5GB | 必需 |
| `sd_xl_refiner_1.0.safetensors` | 精炼（可选） | 6GB | 可选 |
| `v3_sd15_mm/mm-StoryTellaer.safetensors` | AnimateDiff 运动模块 | 140MB | 推荐 |
| `svd_xt.safetensors` | SVD 图生视频（14帧） | 5GB | 推荐 |
| `svd_xt_025.safetensors` | SVD 快速版（10帧） | 5GB | 替代 |

## 工作流设计

### 整体流程

```
角色全身 PNG（1728x2304）
        ↓
① 裁剪为角色区域（540x960）
        ↓
② 送入 ComfyUI 图生视频节点
   生成 3-5 秒轻度动画片段
        ↓
③ FFmpeg stream_loop 循环
   延长到配音时长（18s / 13s）
        ↓
④ 叠加到背景视频 + 配音
        ↓
⑤ 最终视频输出
```

### ComfyUI 工作流节点

```
LoadImage (角色 PNG)
    ↓
ImageScale (缩放到 768x768 或 1024x1024)
    ↓
CheckpointLoader (SDXL Base)
    ↓
CLIPTextEncode (正面提示词)
    ↓
CLIPTextEncode (负面提示词：低质量、变形、模糊)
    ↓
ADE_AnimateDiffLoader (AnimateDiff 运动模块)
    ↓
KSampler (采样器，steps=20, cfg=7)
    ↓
VAEDecode (解码)
    ↓
Guide → VideoCombine (合成视频)
```

### 提示词模板

**正面提示词（适合全身角色）**：
```
(masterpiece, best quality, 1girl, standing, full body, realistic photo,
light breathing motion, subtle cloth movement, gentle hair sway,
cinematic lighting, upper body focus, from behind slightly angled camera)
```

**负面提示词**：
```
(low quality, worst quality, blurry, deformed, disfigured, bad anatomy,
extra limbs, floating, disconnected limbs, jitter, watermark)
```

**AnimateDiff 运动参数**：
```
motion_scale: 0.8  (低于默认值1.0，减少运动幅度)
```

### Python 调用 ComfyUI 工作流

ComfyUI 提供 HTTP API，可以从 Python 调用：

```python
import requests, json, time, os

COMFYUI_HOST = "http://127.0.0.1:8188"

def queue_prompt(workflow_path, client_id):
    """把工作流传入 ComfyUI 并等待完成"""
    with open(workflow_path, 'r') as f:
        workflow = json.load(f)

    # 替换输入图片路径
    # 找到 LoadImage 节点，修改 image 字段
    workflow["3"]["inputs"]["image"] = "na1_portrait.png"

    # 提交任务
    response = requests.post(
        f"{COMFYUI_HOST}/prompt",
        json={"prompt": workflow, "client_id": client_id}
    )
    prompt_id = response.json()["prompt_id"]

    # 轮询直到完成
    while True:
        history = requests.get(f"{COMFYUI_HOST}/history/{prompt_id}").json()
        if prompt_id in history:
            status = history[prompt_id].get("status", {})
            if status.get("completed"):
                # 获取输出文件路径
                output_images = history[prompt_id].get("outputs", {})
                # 解析输出，下载视频文件
                return True, output_images
            elif status.get("failed"):
                return False, status.get("error")
        time.sleep(2)

def get_video_output(outputs):
    """从 ComfyUI 输出中提取视频文件"""
    for node_id, data in outputs.items():
        if "gifs" in data or "videos" in data:
            # 下载视频文件到本地
            video_url = data.get("gifs", [None])[0] or data.get("videos", [None])[0]
            if video_url:
                r = requests.get(f"{COMFYUI_HOST}/view?filename={video_url}")
                local_path = f"data/videos/comfyui_output/{video_url}"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(r.content)
                return local_path
    return None
```

### 更简单的方式：使用 ComfyUI 的 Python 启动脚本

ComfyUI 自带 `main.py`，可以直接命令行调用：

```bash
cd ComfyUI
python main.py --help
# 常用参数：
# --input-directory: 输入图片目录
# --output-directory: 输出目录
# --preview-method: 预览方法
```

或者用 `comfyui-cli`：

```bash
comfyui-cli generate \
  --input data/png/na1_nobg.png \
  --model svd_xt \
  --motion-scale 0.7 \
  --num-frames 25 \
  --fps 8 \
  --output data/videos/na1_anim_5s.mp4
```

## 循环复用机制

生成 3-5 秒片段后，用 FFmpeg `stream_loop` 循环延长：

```python
def loop_video_to_duration(input_mp4, target_duration, output_mp4):
    """
    用 stream_loop 把短片段循环延长到目标时长
    """
    input_dur = get_duration(input_mp4)
    repeat_count = int(target_duration / input_dur) + 2

    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', str(repeat_count),
        '-i', input_mp4,
        '-t', str(target_duration),
        '-c:v', 'libx264', '-preset', 'fast',
        '-crf', '20',
        output_mp4
    ]
    subprocess.run(cmd, print(f"循环完成: {output_mp4}"))

# 示例：为角色A生成循环视频
loop_video_to_duration(
    input_mp4='data/videos/na1_anim_5s.mp4',
    target_duration=18.55,  # role_a 音频时长
    output_mp4='data/videos/na1_anim_looped.mp4'
)
```

**重要**：生成片段的时长要和配音匹配，否则需要循环。5 秒片段循环 3 次 ≈ 15 秒，接近 18.55 秒配音。

## 片段质量判断标准

从生成结果中选取最优片段的标准：

1. **脸部保持**：脸没有变形、五官清晰
2. **运动幅度**：<2px 边缘位移
3. **无明显闪烁**：连续帧之间差异平滑
4. **循环接缝**：片段首尾衔接自然（loop 点无缝）

如果接缝不自然，可以生成 10 秒片段，只取中间 5 秒作为循环部分。

## 与 video_composer.py 的集成

生成循环角色视频后，直接传入：

```python
compose_dual_character_video(
    background_path='data/videos/bg_loop.mp4',
    clip_a_path='data/videos/na1_anim_looped.mp4',   # 角色A 动画视频
    clip_b_path='data/videos/n3_anim_looped.mp4',    # 角色B 动画视频
    audio_a_path='data/ref_audio/role_a_concat.wav',
    audio_b_path='data/ref_audio/role_b_concat.wav',
    # 位置和 v10 相同
    role_a_x=0, role_a_y=480,
    role_b_x=540, role_b_y=480,
)
```

## 可选：混合 ComfyUI + FFmpeg 做局部动效

如果 ComfyUI 生成的全身动效太大胆，可以**只生成局部动效片段**，然后用 FFmpeg overlay 到静态角色图上：

```
ComfyUI 输出：na1_anim_5s.mp4（全身轻微动）
       ↓
FFmpeg 提取上半部分（头部+肩部）作为动效层
       ↓
叠加到静态角色全身图（na1_nobg.png）
       ↓
组合出最终角色层
```

```python
def blend_static_and_animated(static_png, animated_mp4, output_mp4, top_fraction=0.6):
    """
    把静态全身图和动画片段混合
    - 下半部分用静态图（稳定）
    - 上半部分用动画片段（轻微动效）
    """
    # 1. 提取动画片段的上半部分
    h, w = 960, 540
    top_h = int(h * top_fraction)

    cmd = [
        'ffmpeg', '-y',
        '-i', static_png,          # 静态全身 PNG
        '-i', animated_mp4,         # 动画视频片段
        '-filter_complex',
        f'[0:v]scale={w}:{h}[static];'
        f'[1:v]scale={w}:{h},crop={w}:{top_h}:0:0[anim_top];'
        f'[static][anim_top]overlay=0:0[out]',
        '-map', '[out]',
        output_mp4
    ]
    subprocess.run(cmd)
```

这样既有轻微动效，又不会让整个角色看起来不稳定。

## 产出清单

- [ ] ComfyUI 工作流 JSON：`workflows/character_anim_svd.json`
- [ ] 角色 A 动画片段：`na1_anim_5s.mp4`
- [ ] 角色 B 动画片段：`n3_anim_5s.mp4`
- [ ] 角色 A 循环视频：`na1_anim_looped.mp4`
- [ ] 角色 B 循环视频：`n3_anim_looped.mp4`
- [ ] 最终视频：`dual_v11_comfyui.mp4`

## 风险点

1. **脸部变形**：AI 生成视频可能在多帧后出现脸部漂移，生成后需要逐帧检查
2. **循环不自然**：片段首尾接缝需要目测验证
3. **计算资源**：SVD 或 AnimateDiff 需要 6GB+ 显存，每次生成 5-30 秒
4. **风格一致性**：两个角色用同一个工作流生成，风格可能不一致

## 推荐实施步骤

1. 确认 ComfyUI 已安装，运行 `python main.py` 验证可启动
2. 下载 SVD 或 AnimateDiff 模型
3. 用角色 A 图测试生成 5 秒片段，检查脸部质量
4. 如果质量 OK，写成 Python 调用脚本
5. 循环到配音时长，集成到 video_composer 出最终视频
6. 如果脸部变形，尝试降低 motion_scale 或改用局部混合方案
