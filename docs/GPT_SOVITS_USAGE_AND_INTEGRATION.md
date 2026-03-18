# GPT-SoVITS 使用与接入说明

本文档说明：
- 当前项目中 GPT-SoVITS 的使用方式
- 你在本机需要完成的接入步骤
- 常见报错与排查顺序

## 1. 当前项目里的接入方式

项目中的语音合成入口：
- `TTSEngine` 统一调度 TTS Provider
- `GPTSoVITSProvider` 负责 GPT-SoVITS 生成

关键行为：
- 优先走 SDK（`sdk.tts_client`）
- SDK 初始化失败时，自动回退 HTTP API
- HTTP 默认优先尝试 `http://127.0.0.1:9880/tts`，再尝试根路径

相关文件：
- `src/content_factory/tts_engine.py`
- `src/content_factory/tts_providers/gpt_sovits_provider.py`

## 2. 我建议你怎么使用

推荐使用顺序：
1. 先在 GPT-SoVITS 仓库里单独验证 SDK 示例
2. 优先使用“无需服务”的 SDK 直调模式
3. 如有 HTTP 集成需求，再启动 GPT-SoVITS 的 API 服务
4. 最后在本项目里调用 `--tts-provider gpt_sovits`

原因：
- 先验证底层可用，能快速定位问题是在模型环境还是在业务项目
- 避免在主项目里同时排查“模型+接口+业务”三层问题

调用模式说明：
- 模式 A（推荐）：SDK 直调，不需要先运行 `api_v2.py`
- 模式 B（可选）：HTTP API 调用，需要先启动 `api_v2.py`

## 3. 接入指南需要完成的细节（必须项）

### 3.1 环境与依赖

在 `D:\IT\GPT-SoVITS-main\GPT-SoVITS-main` 中安装依赖：

```bash
pip install -r requirements.txt
pip install fastapi uvicorn python-multipart
```

如果遇到缺包，按报错补装（常见）：

```bash
pip install pytorch-lightning matplotlib x_transformers peft jieba fast-langdetect split-lang cn2an pypinyin inflect g2p-en wordsegment jieba-fast addict
```

### 3.2 模型与配置

确认 `GPT_SoVITS/configs/tts_infer.yaml`：
- `device` 与你的机器一致（CPU 就 `cpu`）
- `is_half` 与 device 一致（CPU 建议 `false`）
- `t2s_weights_path` / `vits_weights_path` 指向有效权重
- 默认参考音频路径已设置为 `data/ref_audio/mature_male_ref.wav`

### 3.3 先跑 SDK 示例

```bash
python sdk/examples/basic_synthesize.py
python sdk/examples/batch_example.py
```

说明：
- 示例能触发模型加载，验证 SDK 路径是否正确
- 返回 `success: false` 时，先看 `error_msg`
- 若未显式传 `ref_audio_path`，SDK 将优先使用 `data/ref_audio/mature_male_ref.wav`
- 这一步不依赖 HTTP 服务，可直接验证“方法调用 + 参数传入”链路

### 3.4 启动 API 服务

本节仅在你需要 HTTP 接入时执行（可选）：

```bash
python api_v2.py
```

启动成功标志：
- 出现 `Uvicorn running on http://127.0.0.1:9880`

### 3.5 在本项目调用

在 `D:\IT\ai_douyin`：

```bash
set GPT_SOVITS_SDK_ROOT=D:\IT\GPT-SoVITS-main\GPT-SoVITS-main
python main.py generate --topic "人生迷茫" --tts-provider gpt_sovits --voice "D:\路径\参考音频.wav"
```

## 4. 当前已支持的参数约定

`GPTSoVITSProvider` 已支持这些参数（可由业务层透传）：
- `text_lang`, `prompt_lang`
- `prompt_text`, `ref_audio_path`
- `request_version`（默认 `v2ProPlus`）
- `tts_config`（默认指向 GPT-SoVITS 的 `tts_infer.yaml`）
- `top_k`, `top_p`, `temperature`, `sample_steps`, `repetition_penalty`, `seed`
- `device`, `is_half`
- `gpt_weights`, `sovits_weights`

## 5. 常见报错与处理

### 5.1 `Input type (FloatTensor) and weight type (HalfTensor)`

原因：
- 推理输入精度与模型权重精度不一致

处理：
1. `tts_infer.yaml` 里先统一 `device: cpu` + `is_half: false`
2. 重启 `api_v2.py`
3. 若仍报错，确认加载的实际版本与权重（`request_version`、权重路径）一致

### 5.2 SDK 初始化失败 `No module named xxx`

原因：
- GPT-SoVITS 运行依赖未完整安装

处理：
- 在 GPT-SoVITS 环境中按缺失模块逐个补装
- 优先确保示例脚本可运行

### 5.3 HTTP 404

原因：
- 端点路径不对，或服务未启动

处理：
- 检查 `api_v2.py` 是否运行
- 手工访问 `http://127.0.0.1:9880/docs`
- 本项目已自动尝试 `/tts` 与根路径

## 6. 最小验收清单

你可以按以下顺序打勾验收：
- [ ] `sdk/examples/basic_synthesize.py` 可执行（无需服务）
- [ ] `sdk/examples/batch_example.py` 可执行（无需服务）
- [ ] （可选）`python api_v2.py` 正常启动
- [ ] （可选）`http://127.0.0.1:9880/docs` 可访问
- [ ] `python main.py generate --topic "人生迷茫" --tts-provider gpt_sovits ...` 成功产出音频
- [ ] 输出文案末尾不包含“关注/点赞/评论”引导语

## 7. 推荐下一步（可选）

为了更稳定地复现，你可以在 `main.py` 增加这些命令行参数并透传给 TTS：
- `--ref-audio-path`
- `--prompt-text`
- `--request-version`
- `--tts-config`
- `--is-half`
- `--device`
