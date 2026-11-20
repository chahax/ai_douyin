# 隔离安装与真实本地测试结果

日期：2026-10-18。安装并实际跑完 GLiNER 多语模型与 spaCy EntityRuler；当前结果属于候选预检可行性试验，尚未接入生产，不能判定版权或保证 Seedance 通过。

## 实际安装

- 根目录：`D:\IT\ai_douyin\tools\ip_precheck_lab_v1`。
- Python 3.11.15，独立 `.venv`；GLiNER 0.2.29、spaCy 3.8.16、Torch 2.14.1+cpu、Transformers 4.57.6、protobuf 7.36.2；完整 61 包检查无依赖冲突，见 `requirements.lock.txt`。
- 模型 `urchade/gliner_multi-v2.1`（Apache-2.0），revision `443d26d654e0324125a96bebd8e796c14ff2efe6`，safetensors 1155830112 字节；下载 SHA256 与作者官网 pointer 一致。底层 mdeberta 配置/分词器冻结为 `a0484667b22365f84929a935b5e50a51f71f159d`。
- 官网直连超时，镜像仅作传输；下载阶段没有发送项目正文。推理开启 HF 离线和 Python socket 禁网，仅使用本地文件，未调用付费模型或新增视频。
- 只安装本轮文本工具；PaddleOCR 因本次无参考图未安装，火山云防火墙没有开通或接入。

## 固定样例结果

18 条中文人工样例在首次推理前固定，三种配置使用相同样例、词库、真实提示词和阈值 0.4，按顺序本地运行。NER 金标28个，词库候选金标25个，目的不同；以下是原文跨度和标签均一致的严格评分，不能互相冒充。

| 配置 | 找对 TP | 多报 FP | 漏报 FN | 精确率 | 召回率 |
|---|---:|---:|---:|---:|---:|
| GLiNER 默认分词 | 8 | 9 | 20 | 47.1% | 28.6% |
| GLiNER 中文分词（原始空白错位配置） | 20 | 16 | 8 | 55.6% | 71.4% |
| GLiNER 中文分词＋过滤空白词 | 20 | 16 | 8 | 55.6% | 71.4% |
| spaCy 演示别名词库 | 22 | 0 | 3 | 100.0% | 88.0% |

最终配置只比较实体位置、不比较类别时 TP25/FP11/FN3，精确率69.4%、召回率89.3%。严格类别仍有混淆，例如阿迪达斯被识别人名、哈利·波特被识别为地点、周杰伦被识别为虚构角色；Coca-Cola 被拆成两个实体，并有普通代词误报。因此不能直接作为自动版权阻断器。

演示词库包含已知别名，22/25命中、此组无误报；漏掉未收录的“岚星盒、月港清单、林舟”。这是人工演示库对这组样例的覆盖结果，不代表真实业务达到100%精确率。苹果水果/小米粥在本组未触发品牌规则，但启发式仍需业务样例验证。“红蓝紧身衣、吐蛛丝”的描述没有明确名称，实体预检无法据此完成IP相似性判断。

## 实际 S1A 提示词

完整原提示词1961字符，17个重叠窗口，结果和原文位置全部保存；无人工金标，所以不计算准确率。最终配置能抽取周明、周禾和渡口地点等，演示词库没有品牌/IP候选命中。模型同时把内部段号 `S1-A`、`S1`识别为作品，把 `scene_ledger`、`value`识别为人名，这是实际误报例子，不能据此说提示词有知名IP或找到Seedance的拦截原因。

## 已定位和修复的问题

1. 初次固定 revision 下载没有生成 `main` 缓存引用，旧模型按基础 repo 名离线读取失败；显式绑定本地缓存引用到已下载冻结 revision，原失败保留。
2. 分词器转换缺 `protobuf`，补装到独立环境并纳入 setup，原错误保留。
3. 默认正则把连续中文当整块，导致句中实体无法定位；使用中文 splitter 后样例召回提高。
4. 包内 spaCy splitter 含纯空白 token，但 Transformer 不产生对应子词，GLiNER连续编号令真实提示词实体错位。独立最小复现后，在试验适配器中过滤纯空白词、保留其他词原始字符位置，修复了原文映射。原始中文配置、源码快照和全部结果仍保留。见 `WHITESPACE_TOKENIZER_REVIEW.json`。短句样例成绩不变，实际提示词位置恢复。

模型原生 byte fallback 转换、Torch弃用及异常 Mistral regex 提示保留在原始日志，未静默隐藏，也未因这次小样例运行擅自改第三方权重或包源码。160字符窗口降低长文风险，不宣称对任意输入普遍无截断。

## 隔离审查与结论

子 agent 开发评估器与样例，主 agent 审查/安装/实际运行/中文适配修复；另一子 agent 独立只读核对隔离与空白索引问题。实际加载为已安装 Transformers 内置 DebertaV2 类，下载缓存没有远程Python文件或pickle权重。

独立包位置均在本目录 `.venv`，模型/缓存/临时目录独立；这是依赖/缓存隔离及 Python 网络门，不是OS沙箱。`ISOLATION_VERIFICATION.json`核对30个受保护文件及主项目包列表。BASELINE 是依赖安装后、推理前捕获，不能声称有安装前后全量环境比对；安装命令的显式独立 `--python` 及包位置另行保留证明。主生产入口、原提示词、账本和旧冻结未修改。

建议使用“词库明确匹配＋模型补充候选＋上下文/来源授权复核”，先输出名称、类别、位置和证据。当前不自动删除人名、不改原稿、不把无命中写为版权通过；未增加视频重试或生产调用。

## 证据与复跑

- `SUMMARY.json`：三种配置及真实提示词摘要。
- `benchmark_03_default.json/.log`：默认分词真实运行。
- `benchmark_04_chinese.json/.log`：中文原始配置及错位证据。
- `benchmark_05_chinese_nonspace.json/.log`：最终中文空白适配结果。
- `benchmark_01.json`、`benchmark_02_default.json`：安装调试中的原加载失败。
- `MODEL_DOWNLOAD.json`、`OFFLINE_CACHE_BINDING.json`：下载版本、哈希和离线绑定。
- `WHITESPACE_TOKENIZER_REVIEW.json`：独立最小机制复现。
- `ISOLATION_VERIFICATION.json`：环境和受保护文件验证。
- 上级 `README.md`、`setup.ps1`、`requirements.lock.txt`：安装、复跑与版本。

在试验根目录执行（新文件名，避免覆盖旧证据）：

```powershell
.\.venv\Scripts\python.exe -I -X utf8 lab.py run --splitter spacy-zh-nonspace --output results/my_trial_01.json
```
