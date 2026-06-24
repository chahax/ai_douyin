---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-10
model_usage: 当前主线文档，可以作为当前项目状态或实施依据。
---

> 文档状态：当前主线文档，可以作为当前项目状态或实施依据。

# GPT-SoVITS 调用方式文档

更新时间：2026-04-24

## 两种调用方式

| 方式 | 是否需要启动服务 | Python 版本要求 | 推荐场景 |
|------|----------------|----------------|---------|
| **SDK 直调** | ❌ 不需要 | conda Python 3.9 | 优先使用，延迟更低 |
| **HTTP 服务** | ✅ 需要启动 | 任意 | 方便调试 |

---

## 方式一：SDK 直调（推荐，不需要启动服务）

### 关键要求

- **Python 版本**：必须使用 **conda Python 3.9**
  ```
  C:/Users/<your-user>/.conda/envs/GPTSoVits/python.exe
  ```
- **不能**用系统 Python 3.14（SDK 有 C 扩展兼容性限制）

### 调用方法

在项目 `ai_douyin` 中，SDK 调用通过 **subprocess** 启动 conda Python 3.9 来执行：

```python
import subprocess, os

conda_python = "C:/Users/<your-user>/.conda/envs/GPTSoVits/python.exe"
sdk_root = "./GPT_SoVITS"  # 或使用绝对路径如 <your_gpt_sovits_install_path>
script = """
import sys, os
os.chdir(r'{}')
sys.path.insert(0, r'{}')
sys.path.insert(0, r'{}/GPT_SoVITS')
sys.path.insert(0, r'{}/GPT_SoVITS/eres2net')
sys.path.insert(0, r'{}/GPT_SoVITS/BigVGAN')

from sdk.tts_client import ClientConfig, TTSClient
config = ClientConfig(
    gpt_weights='GPT_weights_v2ProPlus/xxx-e10.ckpt',
    sovits_weights='SoVITS_weights_v2ProPlus/xxx_e12_s192.pth',
    default_ref_audio_path='output/ref_audio_denoised/ttsmaker-file-2026-3-14-16-10-15.mp3',
)
client = TTSClient(config=config)
result = client.synthesize('测试文字生成配音')
print(result['audio_path'] if result['success'] else '')
"""
result = subprocess.run(
    [conda_python, "-c", script.format(sdk_root, sdk_root, sdk_root, sdk_root, sdk_root)],
    capture_output=True, text=True, cwd=sdk_root
)
print(result.stdout)
```

### 验证 SDK 可用性

```bash
"C:/Users/<your-user>/.conda/envs/GPTSoVits/python.exe" --version
# 输出应该是: Python 3.9.23

# 然后测试 import
"C:/Users/<your-user>/.conda/envs/GPTSoVits/python.exe" -c "from sdk.tts_client import ClientConfig, TTSClient; print('SDK OK')"
```

### 常见错误

| 错误信息 | 原因 | 解决 |
|---------|------|------|
| `No module named 'sdk'` | 未切换到 SDK 目录 | `os.chdir(sdk_root)` |
| `No module named 'ERes2NetV2'` | eres2net 未加入 path | 添加 `sys.path.insert(0, 'GPT_SoVITS/eres2net')` |
| `No module named 'ffmpeg'` | ffmpeg 未安装 | 在 conda 环境中 `pip install ffmpeg-python` |
| `_IncompatibleKeys` | 权重文件与模型不匹配 | 确认 gpt_weights 和 sovits_weights 对应正确版本 |
| CUDA provider error | GPU 相关 | 忽略，会自动回退到 CPU |

---

## 方式二：HTTP 服务

### 启动服务

```bash
# 假设 GPT_SoVITS 目录在项目根目录下
cd ./GPT_SoVITS
set PYTHONPATH=./GPT_SoVITS
python api_v2.py
```

看到 `Uvicorn running on http://127.0.0.1:9880` 说明启动成功。

### 在 ai_douyin 项目调用

```bash
# .env 配置
GPT_SOVITS_USE_SDK=false
GPT_SOVITS_ENABLE_HTTP_FALLBACK=false
GPT_SOVITS_API_URL=http://127.0.0.1:9880
```

然后正常调用即可：
```bash
python main.py quick --keywords "励志" --tts-provider gpt_sovits
```

---

## 当前 ai_douyin 项目的配置

```env
# .env
GPT_SOVITS_SDK_ROOT=./GPT_SoVITS  # 或 <your_gpt_sovits_install_path>
GPT_SOVITS_CONDA_PYTHON=C:/Users/<your-user>/.conda/envs/GPTSoVits/python.exe
GPT_SOVITS_USE_SDK=true
GPT_SOVITS_ENABLE_HTTP_FALLBACK=false
```

**注意**：当前项目运行在 Python 3.14，SDK 直调通过 subprocess 启动 conda Python 3.9 来执行。代码层已实现 subprocess 包装，SDK 调用时会自动切换到正确的 Python 环境。

---

## 验证 TTS 是否可用

```bash
cd D:\IT\ai_douyin
python -c "
from src.content_factory.tts_engine import TTSEngine
tts = TTSEngine(provider_type='gpt_sovits')
result = tts.generate_audio('测试文字', 'test.wav')
print('OK' if result else 'FAILED')
"
```

如果失败，检查：
1. `.env` 中 `GPT_SOVITS_SDK_ROOT` 是否正确
2. conda Python 3.9 环境是否可用
3. 权重文件是否存在
