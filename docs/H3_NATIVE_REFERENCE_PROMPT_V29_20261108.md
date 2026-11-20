# H3 官方 Ref2VA 提示格式试验 v29

这是 B 路线的独立 CPU 编译器，不修改 A 的中文原稿、v24 执行器、旧 `B_speech_r2` 或任何冻结 PLAN。当前仅产出待 root 逐稿审查的提示词，未请求媒体或外部语言模型，不能视为成片验收。

官方依据：[Ref2VA 提示规范](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt)、[通用规范](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt)。本实现没有复制官方长示例，使用本项目原稿及显式说话人记录。

## 输入与输出

`INPUTS.json` 绑定四段原稿；`B_speech_r2/INPUT_SPEC.json` 提供经确认的逐句 `quote_index / quote_sha256 / speaker_id / mode`；`B_CANDIDATE_SPEC.json` 提供真实五个参考槽。新 `B_native_v29/INPUT_SPEC.json` 将英文视觉事件与原段位置、UTF-8 字节位置、原文及 SHA 绑定。

`B_native_v29/READING.md` 同时展示四份完整提示与逐镜原文对照，`AUDIT.json` 包含引用与编译回执。中文台词只从原稿引号范围提取，不由模型补写；四段共十处，原词及标点保持。英文视觉动作是本次显式翻译设计输入，需 root 语义审查，SHA 绑定不能证明翻译语义正确。

六节顺序为 `subject_definitions → summary → retention_analysis → detailed_description → overall_soundscape → non_diegetic_music`。除了 `<d>[Mandarin Chinese] “原句”</d>` 内的台词，正文均为英文。

固定视觉身份：Subject 1 苏墨、Subject 2 叶南、Subject 3 叶西决、Subject 4 房间。Picture 1—3 是三张人物参考；Picture 4—5 是新 Klein 同房间正侧视图。AddGuide 首尾帧是独立 latent 输入，不能冒称 Picture 6。未提供的音视频参考不产生 Audio/Video 标签。

每段声音编号从实际首次发声顺序重新编号：S01 弟弟为 S1、哥哥为 S2；其余段父亲为 S1、弟弟为 S2。Subject 身份号与声音号不同。每句心声使用 `says in an off-screen voiceover`，紧接该句 `</d>` 后写同一 Subject 嘴唇完全闭合。对白仍保留动作，未锁定全段面部构图。

首 Shot 不写时间戳，其后使用原稿各段起点 `MM:SS.mmm`，0—15 秒动作窗不压缩改序。S01 末尾父亲闭眼近景，S04 末尾父亲心声近景。S03 最后两秒在手部/脸部递接后退至三人站立全身图，是为末帧状态锚作出的显式构图取舍，保存在 audit 中；不能声称与原中近景设计完全相同。

## CPU API 与待接线边界

`validate_native_prompt(text, expected_quotes=None)` 是不访问文件、不调用模型的纯文本校验器。检查六节、五图标签、四个 Subject、对白精确顺序、首镜无时间、后续时间递增，以及每个心声后的具名闭嘴说明。

`compile_segment(source, source_binding, records, events, refs, summary_en, tradeoff=None)` 做 CPU 编译与只读 SHA 校验，不写文件、不发 HTTP。`make_spec(...)` 和 `prepare(spec_path, out)` 才会在新目录冻结输入与结果；已有不同字节的输出拒绝覆盖。prepare 会回读原可信 speaker map 和 reference spec，不能靠在新 spec 中自行修改人物/模式或图片绑定绕过。

实际命令：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/run_spatial_native_prompt_v29.py
```

**B 执行 spec 必须显式使用 `prompt_format='official_ref2va_v29'`。** 稳定 v24 当前仍会添加中文“参考身份与环境”尾注，因此目前不应直接把此稿当已接线媒体输入。root 需在 A 结束且原 worker 真正退出后增加 opt-in 分支：该 format 先校验完整官方正文，再按正文原字节输入；没有该 format 的旧调用继续使用原逻辑，默认输出字节不变。本次没有改动 v24。

建议接线测试：默认图的 CLIP 输入与旧构图字节相同；opt-in 的实际 CLIP 输入与 v29 文件逐字节相同；不存在中文旧尾注；五 reference 槽实际图 SHA 不变；心声及十句原句在实际 HTTP payload 中各自保持；拒绝坏格式与第六参考槽。HTTP 边界测试仍不能代替真实新 B 原生视频。

## 验证范围

独立测试 `tests/test_visual_spatial_native_prompt_v29.py` 共 33 项，通过实际四源 CPU prepare 与独立 CLI 子进程验证文件边界；包含引用 SHA/位置/时间篡改、错误人物/模式、重复/遗漏句索引、来源映射修改、格式与素材标签及冻结输出拒绝覆盖。证据在 `data/qa/spatial_v29/release_r1.xml` 与 `CPU_ACCEPTANCE.json`。

`dry_prepare_01` 是初步 CPU 草稿；正式 root 待审稿仅在新 `B_native_v29`。本模块没有生成视频、没有更新生产批准，也没有给失败视频补写通过标记。
