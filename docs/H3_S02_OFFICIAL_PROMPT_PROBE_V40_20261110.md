# v40：官方 I2VA 发音结构单段测试

新根 `data/video_generation/h3_s02_official_prompt_probe_20261110_v1`，源为已保存的 v39 S02。只新生成一个 S02，不改 v39；first SHA、seed `45905597282583733`、736×1312、362帧、24fps、12步及原图参数保持，只换 Root 的官方格式 PROMPT 和新 namespace。

格式依据 [MiniMax-H3 官方 I2VA 提示规范](https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/references/base-en.txt)：I2VA 首行后为三个有序 core fields；首镜无 cut 时间，后镜 cut 时间递增；角色 ID 放在发音块外，`<d>` 内是语言标签和逐字台词。心声使用官方 voiceover 表述，之后紧跟闭嘴说明。

校验从 `<d>[Chinese] 原句</d>` 中提取、只 trim 边界空格，再与旧 S02 两个中文正文逐字比较；不再要求新提示有引号，也不为旧 quote 计数加回引号。只有格式被验证，没有声明无字幕已实现。本机独立 CPU 证据 `data/qa/h3_official_prompt_format_20261110/TOKENIZER_FORMAT_EVIDENCE.json` 记录发音专用 token 151669/151670；不改 tokenizer、模型、CFG 或 API。

```text
python scripts/run_h3_s02_official_prompt_probe_v40.py prepare
python scripts/run_h3_s02_official_prompt_probe_v40.py execute
```

Root 技术启动 schema 为 `h3_s02_official_probe_technical_launch/v40`，绑定 PLAN、授权、`_sources()` 和 CPU 验收。只有这一个新视频工程额度，来源是用户“继续修啊”，次数是工程边界。未知不重 POST，不自动重拍，不生成图片、不加载音频 guide、不加负向 CFG、不操作依赖/服务、不新建 observer。

标准 native 四件保存在 `shots/S02`，单 `FINAL_RESULT.json` 直接指向原 native MP4，`postprocessing=[]`。格式是否减少烧字由本次真实输出比较决定，不用后期擦字冒充模型修复。
