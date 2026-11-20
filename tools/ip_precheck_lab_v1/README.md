# 专有名词、品牌与 IP 引用预检隔离试验

本目录包含独立 Python 3.11 虚拟环境、CPU 模型、缓存、18 条中文样例、演示别名词库及真实提示词评估。仅做本地实体识别，不给出侵权结论，也不预测 Seedance 输出版权审核是否通过。

隔离范围是 venv/site-packages、模型/缓存/临时目录和推理时 Python socket 禁网。基础解释器只读复用已安装的 Python 3.11；不是容器或操作系统沙箱。主项目 `.venv`、依赖清单、视频任务及冻结记录保持原入口。

## 安装与下载

在本目录 PowerShell 中执行；无需激活环境。安装只操作本目录 `.venv`，默认无 GPU/CUDA 包。

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe -I -X utf8 lab.py download --endpoint https://hf-mirror.com
```

模型为 `urchade/gliner_multi-v2.1`，固定 revision 与 safetensors SHA256；镜像用于传输，权重哈希来自作者 Hugging Face 页面。模型及 Microsoft 基础分词器的实际下载版本/文件位置保存在 `results/MODEL_DOWNLOAD.json`。GLiNER 请求基础分词器时使用默认 `main`，本地 `refs/main` 显式绑定到已下载冻结 revision，详见 `results/OFFLINE_CACHE_BINDING.json`。

不下载 `.bin` 权重或远程 Python 模型代码；本次 DebertaV2 使用已安装 Transformers 内置实现。首次安装过程中发现并补装了分词器转换所需 `protobuf`，已纳入 setup。完整实际依赖见 `requirements.lock.txt`。

## 本地试跑

`lab.py` 在导入模型之前设置独立缓存、离线变量与 socket 禁网。只读取原 S1A 提示词，不加载项目 `.env`、项目创作模块或视频接口。

```powershell
.\.venv\Scripts\python.exe -I -X utf8 lab.py run --output results/my_trial_01.json
.\.venv\Scripts\python.exe -I -X utf8 lab.py verify
```

每次使用新的结果文件名；旧结果/错误不覆盖。默认是修复空白索引后的 `--splitter spacy-zh-nonspace`；`default` 与 `spacy-zh` 仅用于复现前两种配置，后者已知在含空白文本上错位。`benchmark.py` 单独提供 `--prompt`、`--model-dir`、`--cases`、`--dictionary`，仍有离线门；建议通过 lab 入口运行以同时设置缓存位置。

本次完整结果见 [results/REPORT.md](results/REPORT.md)，可用系统 Python 只读取已保存结果重新生成报告：`python -I -X utf8 summarize.py`。

## 结果解释

- GLiNER 候选和 EntityRuler 演示词库分别评分，严格标签及仅跨度指标同时保留。
- 金标在首次推理前固定；真实提示词没有人工金标，不计算“准确率”。
- 160 字、40 字重叠窗口降低长文截断风险，并保存每块和全局偏移；它不能证明任意输入绝不发生子词截断，应同时查看运行警告。
- 普通虚构人名、地名不自动算品牌/IP；“苹果/小米”启发式可误报或漏报，保留拒绝和命中明细。
- 描述性模仿、画面形象、授权关系不在这个小型实体识别试验的能力范围。
- `BASELINE.json` 在独立依赖安装后、模型推理前捕获，因此只证明其后的受保护文件/主环境包列表不变；安装隔离由显式安装路径和包位置证明。

原始提示词、视频原始错误和完整文本冻结文件均只读。本目录未连接生产派发，没有新增视频请求。
