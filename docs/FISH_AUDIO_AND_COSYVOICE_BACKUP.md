# Fish Audio 与 CosyVoice 语音方案

更新时间：2026-07-29

## 1. Fish Audio 官方入口

- 中文生成页：https://fish.audio/zh-CN/
- 中文声音库：https://fish.audio/zh-CN/discovery/
- 声音设计：https://fish.audio/zh-CN/blog/voice-design/
- 声音克隆：https://fish.audio/zh-CN/voice-clone/
- 变声器：https://fish.audio/zh-CN/voice-changer/
- 价格：https://fish.audio/zh-CN/plan/
- 开发者入口：https://fish.audio/zh-CN/developers/
- API 快速开始：https://docs.fish.audio/developer-guide/getting-started/quickstart
- TTS API：https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
- API 价格：https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits

### 《完美恋人》推荐试音方法

先在中文生成页固定两个音色，不要每句更换音色。

- 林小雨：年轻中国女性、自然口语、轻柔但不是播音腔。
- 陈默：年轻中国男性、温和、可信，施压时降低音量并加快语速。

建议把对白按情绪拆开生成，并在文本中加入方向标签：

```text
[soft][warm] 晚安，陈默。你也早点休息……今天和你聊天，我真的很开心。

[hesitant][near-whisper] 那个理财软件……真的靠谱吗？

[hurt][breathy][long pause] 你照片里的手机倒影不对。陈默，你到底还有多少事在骗我？

[reassuring][warm] 小雨，你相信我。等这一单结束，我就飞过去见你。

[urgent][emphasis] 机会月底就没有了。你现在不转，我们两个人都要亏。
```

试听阶段可使用免费额度。正式发布前要确认所选音色及账户方案的商业许可；不要克隆没有明确授权的真人声音。

## 2. CosyVoice 本地备选

官方仓库：https://github.com/QwenAudio/CosyVoice

官方当前推荐模型：

- ModelScope：`FunAudioLLM/Fun-CosyVoice3-0.5B-2512`
- Hugging Face：https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512

本机可用状态（2026-07-30）：

- 独立环境：`C:\Users\c\.conda\envs\cosyvoice310`
- 旧环境：`C:\ProgramData\miniconda3\envs\cosyvoice` 曾在 Conda
  事务失败后丢失 `python.exe`，不要使用；模型不在该环境中。
- Python：3.10.20
- Pynini：2.1.6
- PyTorch / Torchaudio：2.8.0 + CUDA 12.8
- GPU：RTX 5070 Ti 16GB，CUDA 已验证可用
- 项目位置：`D:\IT\CosyVoice`
- 模型位置：`D:\IT\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B`
- 模型：`Fun-CosyVoice3-0.5B-2512` 已完整下载并成功加载
- FP16 加载显存约 3.28GB；固定缓存后冷启动约 31 秒

重新检查或补齐环境时运行：

```powershell
powershell -ExecutionPolicy Bypass -File D:\IT\ai_douyin\scripts\setup_cosyvoice_windows.ps1
```

Windows 下必须把 Numba 缓存指向可写目录，否则 `librosa` 首次导入可能
长时间停在 `tempfile.NamedTemporaryFile`。项目的生成脚本会自动设置：

- `NUMBA_CACHE_DIR=D:\IT\ai_douyin\data\cache\numba`
- `HF_HOME=D:\IT\ai_douyin\data\cache\huggingface`
- `TEMP/TMP=D:\IT\ai_douyin\data\cache`

命令行合成示例：

```powershell
& C:\Users\c\.conda\envs\cosyvoice310\python.exe `
  D:\IT\ai_douyin\scripts\cosyvoice_generate.py `
  --text "小雨，你相信我。我什么时候让你失望过？" `
  --instruct "低沉温柔、循循善诱，但不要夸张，语速稍慢。" `
  --output D:\IT\ai_douyin\data\audio\cosyvoice\sample.wav
```

### 使用原则

- CosyVoice与ComfyUI、GPT-SoVITS使用不同Conda环境。
- 不安装vLLM；单卡16GB先使用官方普通PyTorch推理。
- RTX 5070 Ti使用PyTorch 2.8.0/CUDA 12.8；安装脚本会过滤官方
  `torch 2.3.1/cu121`固定项，避免Blackwell显卡无法运行。
- Windows安装会固定`setuptools 80.9.0`，并单独安装
  `openai-whisper 20231117`，避免新版Setuptools移除
  `pkg_resources`导致构建失败。
- 首次只下载`Fun-CosyVoice3-0.5B-2512`，不同时下载全部旧模型。
- 先生成五段情绪试听，确认后才接入整片对白。
- 克隆真人音色必须取得声音所有者授权。
