# Sonic 数字人接入方案

> 状态：调研完成，待接入
> 更新时间：2026-05-15
> 核心定位：Sonic = 腾讯 PCG + 浙江大学 CVPR 2025 论文，口型最准、速度最快、半身写实数字人

---

## 一、Sonic 项目信息

### 官方信息

| 项目 | 信息 |
|---|---|
| **GitHub** | `jixiaozhong/Sonic` |
| **论文** | CVPR 2025 - "Sonic: Shifting Focus to Global Audio Perception in Portrait Animation" |
| **作者** | Ji Xiaozhong 等，腾讯 PCG + 浙江大学 |
| **开源时间** | 2025 年 1 月 |
| **License** | CC BY-NC-SA 4.0（非商业），商业化需用腾讯云 |
| **项目主页** | https://jixiaozhong.github.io/Sonic/ |
| **在线 Demo** | http://demo.sonic.jixiaozhong.online/ |
| **HuggingFace** | huggingface.co/spaces/xiaozhongji/Sonic |

### 核心模型文件

```
Sonic/checkpoints/
  ├── Sonic/
  │  ├── audio2bucket.pth    # 音频→bucket
  │  ├── audio2token.pth      # 音频→token
  │  ├── unet.pth             # UNet（主要推理网络）
  │  ├── yoloface_v5m.pt      # 人脸检测
  ├── stable-video-diffusion-img2vid-xt/  # SVD 视频生成
  ├── whisper-tiny/            # Whisper 语音识别
  └── RIFE/                    # 光流插帧
```

模型下载：
```bash
# Sonic 主模型
huggingface-cli download LeonJoe13/Sonic --local-dir checkpoints

# SVD（视频生成）
huggingface-cli download stabilityai/stable-video-diffusion-img2vid-xt --local-dir checkpoints/stable-video-diffusion-img2vid-xt

# Whisper tiny（语音识别）
huggingface-cli download openai/whisper-tiny --local-dir checkpoints/whisper-tiny
```

---

## 二、Sonic vs 其他方案对比

| | **Sonic** | SadTalker | EchoMimicV3 | LivePortrait |
|---|---|---|---|---|
| **口型准确度** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **推理速度** | ⭐⭐⭐⭐⭐ 极快 | ⭐⭐ 慢 | ⭐⭐ 慢 | ⭐⭐⭐ 中 |
| **显存需求** | ⭐⭐⭐⭐ 较低 | ⭐⭐ 中 | ⭐⭐ 低 | ⭐⭐⭐ 中 |
| **模型大小** | ~30-60MB | 中 | 大（1.3B） | 中 |
| **输出风格** | 半身写实 | 全身/半身 | 半身/全身 | 半身/全身 |
| **头部动作** | 轻微自然 | 可调 | 自然 | 自然 |
| **支持动漫** | ✅ 支持 | ❌ 一般 | ❌ | ❌ |
| **论文** | CVPR 2025 | - | AAAI 2026 | - |

**Sonic 的核心创新**：不是只关注嘴唇局部，而是把注意力放到整个音频的全局感知上，所以口型更准、表情更自然。

---

## 三、Sonic 的可用版本

| 版本 | 地址 | 说明 |
|---|---|---|
| **官方原版** | `jixiaozhong/Sonic` | 官方 PyTorch 实现 |
| **ComfyUI 版** | `smthemex/ComfyUI_Sonic` | 社区 ComfyUI 节点 |
| **独立运行版** | `vshortt73/sonic-talking-head` | 提取为独立脚本，无 ComfyUI 开销，比 ComfyUI 快 50%+ |

**独立运行版**（`vshortt73/sonic-talking-head`）推荐用于本项目接入，因为它：
- 不依赖 ComfyUI，直接调用模型
- 比 ComfyUI 版本快 50%+
- 提供 Python API 和命令行接口
- 内置 40+ Edge-TTS 音色

---

## 四、快速使用

### 独立版安装（推荐）

```bash
git clone https://github.com/vshortt73/sonic-talking-head.git
cd sonic-talking-head
pip install -r requirements.txt

# 安装 PyTorch（按你的 CUDA 版本）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# 下载模型（见上文模型下载）
```

### 基础调用

```bash
# 从文本生成
python sonic_production.py \
  --image examples/test.png \
  --text "复利是理财中最强大的概念之一。" \
  --output result.mp4

# 从音频文件生成
python sonic_production.py \
  --image examples/test.png \
  --audio examples/test.wav \
  --output result.mp4

# 启动 Web 界面
python sonic_web.py
```

### Python API

```python
from sonic_production import SonicGenerator

generator = SonicGenerator(
    model_dir="~/sonic_models",
    device="cuda"  # 或 "cpu"（更慢）
)

# 生成口型视频
output_path = generator.generate(
    image="path/to/portrait.png",
    audio="path/to/audio.wav",
    output="output.mp4"
)
```

---

## 五、项目接入方案

### 接入位置

```
presenter_pipeline.py
       │
       ├── sadtalker_wrapper.py      # 现有 SadTalker 封装（动漫/写实备选）
       ├── sonic_wrapper.py          # 新增 Sonic 封装（写实首选）
       └── ...
```

### sonic_wrapper.py 设计

```python
"""
sonic_wrapper.py — Sonic 数字人口型封装
"""

import subprocess
import os
from pathlib import Path

class SonicWrapper:
    """Sonic 写实数字人口型视频生成"""

    def __init__(self, sonic_home: str = None):
        self.sonic_home = sonic_home or os.environ.get("SONIC_HOME", "./Sonic")
        self.script = Path(self.sonic_home) / "sonic_production.py"

    def generate(self, image_path: str, audio_path: str, output_path: str) -> bool:
        """
        生成口型视频

        Args:
            image_path: 角色图路径（支持 PNG/JPG）
            audio_path: 配音音频路径（WAV/MP3）
            output_path: 输出视频路径（MP4）

        Returns:
            bool: 生成是否成功
        """
        if not self.script.exists():
            raise FileNotFoundError(f"Sonic 脚本不存在: {self.script}")

        cmd = [
            "python", str(self.script),
            "--image", image_path,
            "--audio", audio_path,
            "--output", output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Sonic 生成失败: {result.stderr}")

        return os.path.exists(output_path)

    def generate_from_text(self, image_path: str, text: str, output_path: str, voice: str = "zh-CN-YunjianNeural") -> bool:
        """
        从文本直接生成（自动 TTS + 口型）

        Args:
            image_path: 角色图路径
            text: 要说的文字
            output_path: 输出视频路径
            voice: Edge-TTS 音色，默认为男声
        """
        # 1. TTS 生成音频
        import edge_tts
        audio_path = output_path.replace(".mp4", ".wav")
        asyncio.run(self._tts_generate(text, audio_path, voice))

        # 2. Sonic 生成口型视频
        return self.generate(image_path, audio_path, output_path)

    async def _tts_generate(self, text: str, output: str, voice: str):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output)
```

---

## 六、presenter_pipeline 扩展

### 支持两种口型引擎

```python
# video_mode 选项扩展
VIDEO_MODES = {
    "single_template": "单人口播模板（旧格式）",
    "dual_framepack_active": "双角色 FramePack 主动说话正式版",
    "presenter_realistic": "写实数字人主讲（Sonic）",  # 新增
    "presenter_anime": "动漫数字人主讲",                # 新增
}
```

### PresenterPipeline 扩展

```python
class PresenterPipeline:
    def __init__(self, driver: str = "sonic"):
        """
        Args:
            driver: "sonic" | "sadtalker" | "liveportrait"
        """
        self.driver = driver
        if driver == "sonic":
            self.talking_head = SonicWrapper()
        elif driver == "sadtalker":
            self.talking_head = SadTalkerWrapper()
        # ...

    def generate_segment(self, segment: dict) -> str:
        """生成单段口型视频"""
        return self.talking_head.generate(
            image=self.character_image,
            audio=segment["audio_path"],
            output=segment["talk_video_path"]
        )
```

---

## 七、输入输出

```
输入：
  - 主题/关键词
  - 写实角色图（1张，正面，半身）
  - 口型引擎：Sonic（写实）/ SadTalker（动漫备选）

Sonic 角色图要求：
  - 半身照（胸以上），正面或3/4侧脸
  - 脸部清晰，光照均匀
  - 背景简单（纯色或无杂物）
  - 建议尺寸：512x512 或更大
  - 格式：PNG / JPG

输出：
  - 最终视频：data/videos/presenter_{timestamp}.mp4
  - 分段素材：data/presenter/{timestamp}/segments/
```

---

## 八、技术栈完整版

| 环节 | 写实版（推荐） | 动漫版 |
|---|---|---|
| 口型引擎 | **Sonic** | SadTalker / LivePortrait |
| 背景图 | ComfyUI + 写实模型 / 预设图库 | ComfyUI + anime模型 / 预设图库 |
| 文字叠加 | PIL | PIL |
| 配音 | Edge-TTS / GPT-SoVITS | Edge-TTS / GPT-SoVITS |
| 合成 | FFmpeg | FFmpeg |
| BGM混音 | FFmpeg | FFmpeg |

---

## 九、实施步骤

**第一阶段：Sonic 验证（1-2小时）**
1. 安装 `vshortt73/sonic-talking-head` 独立版
2. 下载模型文件到 `~/sonic_models/`
3. 用角色图 + 音频测试生成
4. 验证输出质量和速度

**第二阶段：Sonic Wrapper（1小时）**
1. 写 `sonic_wrapper.py` 封装类
2. 处理输入输出路径约定
3. 错误处理和日志

**第三阶段：PresenterPipeline 集成（2-3小时）**
1. 扩展 `presenter_pipeline.py` 支持 `driver="sonic"`
2. 对接脚本分段 → 音频生成 → Sonic口型 → 背景叠加 → 拼接
3. 添加 `--driver sonic` 命令行参数

**第四阶段：发布集成**
1. 集成到 `auto_publish_service.py`
2. 新增 `python main.py presenter-publish --driver sonic --keywords "..."`
3. Streamlit 后台支持选择口型引擎

---

## 十、注意事项

1. **License**：Sonic 是 CC BY-NC-SA 4.0（非商业）。商业使用需通过[腾讯云 Video Creation 大模型](https://cloud.tencent.com/product/vclm)
2. **显存**：官方测试用单卡 32G；独立版对显存要求更低
3. **ComfyUI vs 独立版**：独立版快 50%+，推荐使用
4. **角色图**：半身写实图，脸部清晰，光照均匀效果最好
