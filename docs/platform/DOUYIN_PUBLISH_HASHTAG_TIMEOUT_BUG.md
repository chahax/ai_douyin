---
doc_status: reference
doc_category: platform
last_reviewed: 2026-05-10
model_usage: 平台功能参考文档；用于抖音发布、数据持久化、自动回复相关实现。
---

> 文档状态：平台功能参考文档；用于抖音发布、数据持久化、自动回复相关实现。

# 抖音发布话题输入超时问题说明

更新时间：2026-04-28

## 问题概述

自动发布流程在“视频上传完成、标题填写完成、描述为空跳过”之后，进入添加话题标签阶段失败。

本次日志中的关键错误：

```text
RuntimeError: Locator.type: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[contenteditable][data-placeholder='添加作品简介']").first
```

失败点位于：

- `src/platform_adapter/publish_workflow.py:134`：调用 `_add_hashtags(page, request.normalized_hashtags())`
- `src/platform_adapter/publish_workflow.py:301-302`：先 `editor.type(" ")`，再 `editor.type(f"#{tag}")`
- `src/platform_adapter/browser_session.py:504`：`_Locator.type()` 将 selector 重新转发给 Playwright 子进程
- `src/platform_adapter/browser_session.py:128-134`：子进程每次执行 `type_text` 时重新用 `page.locator(selector).nth(index)` 查询 DOM

## 触发条件

已观察到的触发输入：

- `title`: 空，由服务层兜底为关键词 `励志`
- `description`: 空
- `hashtags`: `["励志"]`
- `interactive`: `False`

流程表现：

1. 视频上传成功。
2. 标题填写成功。
3. 描述为空，跳过 `_fill_description()`。
4. `_add_hashtags()` 查找简介编辑器。
5. 在简介编辑器中输入话题时，第二次 `type` 等待 `[contenteditable][data-placeholder='添加作品简介']` 超时。

## 根因分析

### 直接原因

`_add_hashtags()` 使用了不稳定 selector 作为后续多次键盘操作的定位依据：

```python
"[contenteditable][data-placeholder='添加作品简介']"
```

这个 selector 依赖 `data-placeholder='添加作品简介'`。简介编辑器一旦获得焦点或被输入内容，前端框架可能会移除、修改或隐藏 placeholder 相关属性。当前实现先输入一个空格：

```python
editor.type(" ")
editor.type(f"#{tag}")
```

由于项目里的 `_Locator` 只是保存 selector 和 index，并不保存真实 DOM 元素句柄，第二次 `type(f"#{tag}")` 会重新按旧 selector 查找元素。如果第一次输入空格后 `data-placeholder` 不再匹配，第二次输入就会等待到 30 秒超时。

### 架构层原因

`src/platform_adapter/browser_session.py` 的 Page/Locator 是自定义跨进程包装器，不等同于 Playwright 原生 Locator。

原生 Playwright Locator 会按 locator 语义重新解析元素，但这里每个动作都通过 JSON 命令发给子进程，子进程再执行：

```python
page.locator(cmd["selector"]).nth(idx).type(cmd["text"])
```

因此，任何“输入后会改变匹配条件”的 selector 都不能安全用于连续 `click/press/type` 操作。

### 误导性现象

日志中描述为空后跳过了 `_fill_description()`，容易误判为“简介框没创建”。但更符合堆栈的解释是：

- `_add_hashtags()` 初始查找简介编辑器时大概率成功，否则会走 `未找到简介编辑器，跳过添加话题标签` 并返回。
- 异常发生在 `editor.type(f"#{tag}")`，说明前面的 `editor.type(" ")` 或焦点操作之后，原 selector 已经不再能定位同一个编辑器。

## 影响范围

高风险场景：

- 描述为空但话题非空。
- 描述非空但简介编辑器填充后 placeholder 属性变化，后续继续添加话题。
- 多个话题连续添加时，第一个话题确认后 DOM 重渲染，后续话题继续复用旧 selector。

用户可见影响：

- 自动发布在话题阶段失败，视频不会进入点击发布步骤。
- 服务层抛出 `RuntimeError: 发布失败: 发布异常: Locator.type: Timeout 30000ms exceeded`。
- 已上传到页面的视频可能停留在未发布草稿状态，需要人工确认。

## 建议修复方案

优先方案：把“添加话题”的多个键盘动作合并成一次在子进程内完成的原子操作。

- 新增 browser command，例如 `type_hashtag` 或 `type_text_sequence`。
- 在子进程里先定位一次更稳定的编辑器 selector。
- 对同一个 locator 连续执行 `click -> press("End") -> type(" #标签") -> press("Enter")`。
- 避免每一步都回到父进程并重新按 placeholder selector 查 DOM。

同时调整 selector 策略：

- 降低 `[data-placeholder='添加作品简介']` 的优先级，或只作为首次发现用。
- 优先使用更稳定的 selector，例如 `div[data-slate-editor='true']`、`.editor[contenteditable='true']`、`[contenteditable='true']`，并结合可见性/文本区域上下文过滤。
- 不要在元素被输入后继续依赖 placeholder 属性。

可选兜底：

- 如果 `description` 为空但 `hashtags` 非空，不先输入单独空格，直接输入 `#标签`。
- 如果 `type` 超时，重新用稳定 selector 查询编辑器并重试一次。
- 添加诊断日志：每次话题输入前记录各候选 selector 的 count，便于确认 DOM 变化。

## 验证用例

建议至少覆盖以下场景：

| 场景 | 输入 | 期望 |
|------|------|------|
| 描述空，单话题 | `description=""`, `hashtags=["励志"]` | 成功添加话题并进入发布按钮步骤 |
| 描述空，多话题 | `description=""`, `hashtags=["励志", "成长"]` | 多个话题均能确认 |
| 描述非空，单话题 | `description="测试简介"`, `hashtags=["励志"]` | 简介和话题都保留 |
| 无话题 | `hashtags=[]` | 跳过话题，不影响发布 |
| 话题已带 `#` | `hashtags=["#励志"]` | `normalized_hashtags()` 后不会重复 `##` |

## 当前结论

这是发布自动化中的 DOM selector 稳定性问题，不是视频上传失败，也不是标题兜底逻辑失败。核心修复点应放在 `publish_workflow._add_hashtags()` 和 `browser_session` 的跨进程输入命令设计上，避免对会随输入变化的 placeholder selector 做连续操作。
