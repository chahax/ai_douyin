# 前端页面设计规范

## 设计方向

后台采用“AI 创作工作台”而不是传统数据库管理页的视觉语言。结构参考即梦 AI 当前工作台的创作入口、功能卡片和模型选择层级，但保留本项目对生产状态、人工审核和错误诊断的要求。

参考入口：[即梦 AI 一站式创作平台](https://jimeng.jianying.com/ai-tool/home)。

核心原则：

1. 左侧是稳定、暗色的工具导航；主工作区使用石墨黑背景与低对比面板。
2. 每页只有一个一级标题、一个主任务和一个主要操作。
3. 功能模块使用圆角工作面板，不用连续的水平线分割整页。
4. 当前模型、实现和运行状态使用短标签，不混在长说明文字里。
5. 危险操作与主要操作不能并列成相同视觉权重。
6. 技术字段只在详情层出现，首页和流程概览优先显示业务名称。

## 设计令牌

| 类型 | 取值 |
|---|---|
| 页面背景 | `#101114` |
| 主工作面 | `#191B20` |
| 侧边导航 | `#141519` |
| 主文字 | `#F0F1F3` |
| 次文字 | `#A1A5B0` |
| 分隔线 | `#2B2E36` |
| 品牌主色 | `#BCF56B` |
| 品牌渐变 | `#BCF56B` → `#91D94C` |
| 成功状态 | `#17A673` |
| 警告状态 | `#D98A18` |
| 危险状态 | `#DD4B5F` |
| 页面最大宽度 | `1480px` |
| 卡片圆角 | `16px` |
| 控件圆角 | `12px` |

令牌和全局 Streamlit 覆盖集中在 `src/web/components/studio.css`，由 `src/web/components/ui.py` 加载，页面文件不得再注入独立 `<style>`。仅当业务组件无法用公共样式表达时，才扩展公共组件。

## 页面结构

标准业务页面：

```text
Page header
  eyebrow / title / one-sentence description

Primary status
  3-5 metrics or one focused action panel

Working area
  filters → content/table/cards

Secondary details
  logs / raw JSON / diagnostics in tabs or expanders
```

创作或工作流页面：

```text
Page header
Current profile / model / quota
Visual workflow or feature cards
Tabs: create/configure | catalog/history | management
One primary submit action
```

审核页面：

```text
Page header
Queue status
Media preview
Checklist
Approve (primary) / Reject (danger)
Audit evidence in expander
```

## 公共组件

- `inject_app_theme()`：全局主题，只在认证入口安装。
- `page_header()`：统一页面头部；不得再使用带 emoji 的裸 `st.title()`。
- `section_header()`：章节标题和一句说明。
- `node_card_header()`：工作流节点名称与接线状态。
- `workflow_overview()`：三阶段工作流概览。
- 原生 `st.metric`、`st.form`、`st.dataframe`、`st.expander` 由全局主题统一外观。

## 文案规则

- 页面标题使用业务名词，如“视频管理”，不写“视频管理控制台页面”。
- 页面说明控制在一句话，解释用户在这里完成什么。
- 按钮使用动作加对象，如“保存方案”“设为当前方案”。
- 状态使用短词：当前使用、热切换、待适配、失败、待审核。
- 技术说明放 caption、详情表或 expander，不占用主标题层级。

## 交互规则

- 选择 profile 只预览；“设为当前方案”才改变运行配置。
- 保存与激活分开，避免编辑动作隐式影响生产。
- 页面切换后的当前状态必须有一个权威显示位置。
- 表单提交后显示明确 revision、任务 ID 或结果状态。
- 需要人工审核的流程不得因为 UI 重设计而减少检查项或确认步骤。

## 验收清单

- 页面在 1280px 宽度下无需横向滚动。
- 首屏能识别页面用途、当前状态和主要操作。
- 同类指标、表单、表格和展开面板外观一致。
- 主按钮每个工作面最多一个。
- 标签颜色不能成为状态的唯一表达，必须同时显示文字。
- 空状态提供原因或下一步，而不是只显示“暂无数据”。
- 浏览器控制台无前端异常，Streamlit AppTest 无 exception。


## 2026-09-06 创作工作台改版

- 默认进入创作工作台；OAuth 回调仍优先进入热门选题。
- 导航分为创作空间、内容运营、资源与工具、管理设置，按原角色权限显示。
- 首页使用三个真实页面入口、最近三项制作记录与真实运营指标。最近制作按 production.json 修改时间排序，缺图显示占位，不制造样片。
- 制作卡片只在审核标记通过且报告存在时显示通过；点击详情保留对应批次。
- 登录页采用品牌介绍与紧凑表单双栏，小屏自动堆叠；登录、注册、Cookie 行为不变。
- 深色原生组件主题由 .streamlit/config.toml 配置；焦点使用可见绿框，支持减少动效偏好。
- 本次参考即梦官方公开页面的创作入口组织；其交互首页在检查期间加载超时。


## 交互能力图（2026-09-06）

技能中心采用中文能力目录与集中详情设置。涉及流程与 AI 模型的页面使用本地交互组件 `src/web/components/flow_graph/`；Python 包装位于 `flow_graph.py`。节点展示用途与状态，连线展示关系、输入输出与衔接约束。普通对象列表继续使用表格。

所有状态必须注明是配置、历史记录还是操作指引。点击只返回节点或边的合法标识，不能执行模型或业务动作。所有动态文本按纯文本渲染，节点与连线需支持键盘，小屏允许画布内滚动。

逐页处理、自评与验收范围见 [本次验收记录](FRONTEND_FLOW_REDESIGN_REVIEW_2026-09-06.md)。
