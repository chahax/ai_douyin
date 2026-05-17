---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# 一条命令提示词生成与自动归档设计文档

## 1. 目标

提供一种“只输入提示词就能生成结果”的使用方式，减少手工步骤，支持自动把输出文件移动到指定目录。

目标体验：
- 用户只输入一条命令 + 提示词
- 系统自动调用现有主流程（RAG -> 文案 -> TTS）
- 成功后自动归档输出到用户指定目录

## 2. 用户故事

### 2.1 最简使用（只输提示词）

```bash
python main.py quick --prompt "人生迷茫怎么办"
```

预期：
- 自动走 `gpt_sovits`（可配置）
- 生成音频
- 打印最终输出文件绝对路径

### 2.2 指定输出目录

```bash
python main.py quick --prompt "如何坚持长期主义" --output-dir "D:\我的成片\今日"
```

预期：
- 生成文件后自动移动到 `D:\我的成片\今日`
- 目录不存在时自动创建

### 2.3 指定参考音频（可选）

```bash
python main.py quick --prompt "焦虑时如何自救" --voice "D:\ref\my_voice.wav"
```

预期：
- 优先使用 `--voice`
- 未传时用默认参考音频 `data/ref_audio/mature_male_ref.wav`

## 3. 设计范围

### 3.1 本期（MVP）

- 增加 `quick` 子命令
- 将输入参数映射到现有 `generate_video_pipeline`
- 成功后自动归档音频到目标目录
- 控制台输出可复制路径

### 3.2 暂不做

- GUI 页面
- 任务队列与并发批处理
- 自动视频合成（当前仅音频）

## 4. 参数设计

新增命令：

```bash
python main.py quick --prompt "<提示词>"
```

参数草案：
- `--prompt`：必填，主题提示词（映射到 `--topic`）
- `--output-dir`：可选，最终归档目录
- `--tts-provider`：可选，默认 `gpt_sovits`
- `--voice`：可选，参考音频
- `--count`：可选，默认 `1`
- `--keep-temp`：可选，是否保留原始输出位置文件

## 5. 系统设计

### 5.1 总流程

1. 解析 `quick` 参数
2. 构造与 `generate` 一致的内部参数对象
3. 调用现有流水线生成音频
4. 捕获返回的输出路径
5. 执行归档策略（移动或复制）
6. 输出最终文件路径与结果摘要

### 5.2 复用点

- 复用 [main.py](file:///d:/IT/ai_douyin/main.py) 的主流程能力
- 复用 [tts_engine.py](file:///d:/IT/ai_douyin/src/content_factory/tts_engine.py) 的音频生成
- 复用当前 RAG 和文案模块，不重复造轮子

### 5.3 归档策略

默认策略：
- 当 `--output-dir` 不为空时，执行 `move`
- 文件名格式建议：`{日期时间}_{topic简写}_{provider}.{ext}`

失败回退：
- 移动失败时，自动改为 `copy`
- 仍失败时保留原文件并输出错误原因

## 6. 代码改动方案

### 6.1 main.py

- 新增 `quick` 子命令
- 新增一个轻量包装函数：将 `quick` 参数映射到 `generate_video_pipeline`
- 让 `generate_video_pipeline` 返回最终 `audio_path`（当前仅日志输出）

### 6.2 新增工具模块（建议）

新增：`src/shared/output_manager.py`

职责：
- 创建目录
- 生成归档文件名
- 执行 move/copy
- 统一返回最终路径

## 7. 兼容性与风险

### 7.1 兼容性

- 不改变现有 `generate` 命令行为
- `quick` 是新增入口，不影响旧脚本

### 7.2 风险

- GPT-SoVITS 运行环境不稳定（精度冲突/依赖缺失）会导致 `quick` 失败
- Windows 路径中包含空格时需保证参数带引号

## 8. 验收标准

- 命令 `python main.py quick --prompt "人生迷茫"` 可以执行到生成阶段
- 成功时输出“最终文件路径”
- 指定 `--output-dir` 后，目标目录出现音频文件
- 旧命令 `python main.py generate ...` 行为不变

## 9. 里程碑

### M1（半天）

- `quick` 命令打通
- 返回并打印最终文件路径

### M2（半天）

- 归档策略与失败回退
- 命令参数补齐

### M3（可选）

- 增加 `--dry-run` 与 `--json-output`
- 为自动化平台输出结构化结果

## 10. 详细实施方案

### 10.1 实施总原则

- 优先复用现有主流程，不拆散 RAG/文案/TTS 逻辑
- 保持 `generate` 行为完全不变，新增 `quick` 入口
- 每一步都可单独回归，避免一次性大改
- 先打通可用链路，再加归档与增强参数

### 10.2 分阶段实施步骤

#### 阶段 A：改造主流程返回值（低风险）

目标：
- 让当前主流程函数可返回 `audio_path`，便于 `quick` 做后处理

改动点：
- [main.py](file:///d:/IT/ai_douyin/main.py)

具体操作：
1. `generate_video_pipeline(args)` 由“仅日志”改为“返回值”模式
2. 失败时返回 `None`
3. 成功时返回 `audio_path`
4. 保留现有日志文本，避免影响已有排障习惯

验收：
- `python main.py generate --topic "人生迷茫"` 行为不变
- 命令输出与之前一致

#### 阶段 B：新增 quick 子命令（核心功能）

目标：
- 支持“只输入提示词”的入口

改动点：
- [main.py](file:///d:/IT/ai_douyin/main.py)

具体操作：
1. 新增 `quick` 子命令
2. 参数：
   - `--prompt`（必填）
   - `--output-dir`（可选）
   - `--tts-provider`（默认 `gpt_sovits`）
   - `--voice`（可选）
   - `--count`（默认 `1`）
   - `--keep-temp`（可选）
3. 增加 `run_quick_pipeline(args)` 包装函数：
   - `prompt -> topic`
   - 构造内部参数并调用 `generate_video_pipeline`
4. 打印最终输出：
   - 生成成功：绝对路径
   - 生成失败：可读错误摘要

验收：
- `python main.py quick --prompt "人生迷茫怎么办"` 可执行到主流程

#### 阶段 C：输出归档模块（增强体验）

目标：
- 自动把结果移动到指定目录，支持失败回退

改动点：
- 新增 [output_manager.py](file:///d:/IT/ai_douyin/src/shared/output_manager.py)
- 在 [main.py](file:///d:/IT/ai_douyin/main.py) 的 `quick` 流程中调用

`output_manager.py` 建议接口：

```python
def finalize_output(source_path: str, output_dir: str | None, topic: str, provider: str, keep_temp: bool) -> str | None
```

职责：
1. 规范化目标目录与文件名
2. 执行 move（默认）
3. move 失败自动 copy 回退
4. 返回最终文件路径

验收：
- 指定 `--output-dir` 时，文件出现在该目录
- 不指定时保持原输出目录行为

#### 阶段 D：参数透传增强（可选）

目标：
- 为 GPT-SoVITS 场景提供更可控的命令入口

可选新增参数：
- `--ref-audio-path`
- `--prompt-text`
- `--request-version`
- `--tts-config`
- `--is-half`
- `--device`

改动点：
- [main.py](file:///d:/IT/ai_douyin/main.py) 参数定义与透传
- [tts_engine.py](file:///d:/IT/ai_douyin/src/content_factory/tts_engine.py) 调用参数原样向下传递

### 10.3 关键实现细节

#### 10.3.1 文件命名规则

归档文件命名建议：
- `{yyyyMMdd_HHmmss}_{topicSlug}_{provider}.{ext}`

示例：
- `20260312_214500_人生迷茫_gpt_sovits.wav`

#### 10.3.2 topicSlug 规则

- 只保留中英文、数字、下划线
- 超长截断到 20 字符
- 空值回退为 `untitled`

#### 10.3.3 keep-temp 行为

- `false`：归档后删除源文件（move）
- `true`：保留源文件并在目标目录复制一份

### 10.4 测试方案（详细）

#### 功能测试

1. 最简命令
   - `python main.py quick --prompt "人生迷茫"`
2. 指定输出目录
   - `python main.py quick --prompt "长期主义" --output-dir "D:\out"`
3. 指定参考音频
   - `python main.py quick --prompt "焦虑" --voice "D:\ref.wav"`
4. 多次生成
   - `python main.py quick --prompt "成长" --count 2`

#### 回归测试

1. 原命令不变
   - `python main.py generate --topic "人生迷茫"`
2. 随机模式不变
   - `python main.py generate`

#### 异常测试

1. `--output-dir` 无权限
2. `--voice` 路径不存在
3. TTS 服务不可用
4. RAG 检索为空，是否正确回退随机模式

### 10.5 风险应对

- TTS 环境不稳定：`quick` 只做参数编排，不隐藏底层报错
- 路径兼容：统一使用 `os.path.abspath` 和 `os.path.join`
- 文件冲突：同名时自动附加 `_1`, `_2` 序号

### 10.6 实施清单（可直接执行）

1. 修改 [main.py](file:///d:/IT/ai_douyin/main.py) 支持返回 `audio_path`
2. 修改 [main.py](file:///d:/IT/ai_douyin/main.py) 增加 `quick` 子命令
3. 新建 [output_manager.py](file:///d:/IT/ai_douyin/src/shared/output_manager.py)
4. 接入归档逻辑并打印最终绝对路径
5. 运行命令级回归测试
6. 更新使用文档与快速命令文档

### 10.7 交付产物

- `main.py`（新增 quick 入口 + 返回值改造）
- `src/shared/output_manager.py`（新增）
- `docs/ONE_COMMAND_PROMPT_AUTOMATION_DESIGN.md`（本设计）
- `docs/GPT_SOVITS_QUICKSTART.md`（命令说明）
