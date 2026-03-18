# GPT-SoVITS 纯命令快速集成（Windows）

## 1) 准备环境（在 GPT-SoVITS 仓库）

```bash
cd /d D:\IT\GPT-SoVITS-main\GPT-SoVITS-main
pip install -r requirements.txt
pip install fastapi uvicorn python-multipart
```

## 2) SDK 冒烟测试（无需启动服务）

```bash
cd /d D:\IT\GPT-SoVITS-main\GPT-SoVITS-main
set PYTHONPATH=D:\IT\GPT-SoVITS-main\GPT-SoVITS-main
python sdk/examples/basic_synthesize.py
python sdk/examples/batch_example.py
```

## 3) 启动 HTTP 服务（仅在需要 HTTP 时）

```bash
cd /d D:\IT\GPT-SoVITS-main\GPT-SoVITS-main
set PYTHONPATH=D:\IT\GPT-SoVITS-main\GPT-SoVITS-main
python api_v2.py
```

看到 `Uvicorn running on http://127.0.0.1:9880` 说明启动成功。

## 4) 在 ai_douyin 项目调用 GPT-SoVITS

新开一个终端执行：

```bash
cd /d D:\IT\ai_douyin
set PYTHONPATH=D:\IT\ai_douyin
set GPT_SOVITS_SDK_ROOT=D:\IT\GPT-SoVITS-main\GPT-SoVITS-main
python main.py generate --topic "人生迷茫" --tts-provider gpt_sovits
```

如果你想显式指定参考音频：

```bash
python main.py generate --topic "人生迷茫" --tts-provider gpt_sovits --voice "D:\IT\GPT-SoVITS-main\GPT-SoVITS-main\output\slicer_opt\35902128404-1-192.mp4_0000172800_0000417280.wav"
```

## 5) 常用排障命令

检查默认参考音频是否存在：

```bash
cd /d D:\IT\ai_douyin
powershell -Command "Test-Path 'D:\IT\ai_douyin\data\ref_audio\mature_male_ref.wav'"
```

检查服务是否可访问：

```bash
powershell -Command "Invoke-WebRequest http://127.0.0.1:9880/docs -UseBasicParsing | Select-Object -ExpandProperty StatusCode"
```

