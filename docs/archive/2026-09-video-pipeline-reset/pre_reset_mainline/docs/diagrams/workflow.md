# 端到端工作流

用户输入一条消息，到最终结果展示的完整路径。包含正常路径和异常路径。

```mermaid
sequenceDiagram
    autonumber
    actor U as 👤 用户
    participant Chat as 💬 Streamlit<br/>聊天页
    participant Ag as 🧠 Agent
    participant Mem as 💭 Memory
    participant LLM as ☁️ LLM
    participant SR as 📋 Skill<br/>Registry
    participant Sk as 🔧 Skill<br/>实现
    participant DB as 💾 SQLite

    Note over U,DB: 用户消息进入系统
    U->>Chat: "帮我生成一个关于'自律'的动漫数字人视频"
    Chat->>Ag: chat(message, session_id)
    Ag->>Mem: add_message() 同步快路径分类
    Mem-->>Ag: memory_type (normal/preference/problem)
    Ag-)Mem: fire-and-forget LLM 精分类<br/>(intent / sentiment / humane_summary)
    Note right of Mem: 异步不阻塞对话

    Ag->>Mem: get_user_context()
    Mem-->>Ag: 偏好 + 最近对话 (20 条)

    Ag->>LLM: chat(messages)<br/>system: Skill 列表 + 用户上下文
    LLM-->>Ag: 响应 + ```plan {...}``` 块

    alt LLM 返回计划（写操作）
        Ag->>DB: save_pending_plan()
        Ag-->>Chat: 显示计划 + ✅确认 / ❌取消 按钮
        U->>Chat: 点击"确认"
        Chat->>Ag: chat("确认")
        Ag->>SR: call(target_skill, kwargs)

        alt Skill 执行成功
            SR->>Sk: 实际执行<br/>(e.g. generate_presenter_video)
            Sk->>DB: 写产物 + 记录
            Sk-->>SR: {success: true, video_path: ...}
            SR-->>Ag: result
            Ag-->>Chat: "✅ 执行完成：data/videos/xxx.mp4"
        else Skill 执行失败
            SR-)ER: ErrorReviewer<br/>(LLM 异步诊断)
            Note right of ER: 落 ErrorReview 表<br/>severity/category/fix
            Ag-->>Chat: 兜底回复 +<br/>可选错误诊断 expander
        end

    else LLM 直接回复（读操作 / 闲聊）
        Ag->>DB: append_message(assistant, ...)
        Ag-->>Chat: 直接展示回答
    end

    Note over Ag,DB: 任何异常都被 catch
    Note over Ag,DB: → 写 ProblemMemory
    Note over Ag,DB: → fire-and-forget ErrorReviewer
    Note over Ag,DB: → 返回兜底文本（绝不抛 traceback 到 UI）
```

## 关键设计

- **写操作必须确认**：发布 / 生成视频 / 自动回复 / 养号 等需要 `requires_confirmation=True`，LLM 输出 `​```plan ```​` 块，用户回复"确认"才执行
- **LLM 分类异步化**：同步快路径用关键词规则拿 `memory_type`（不阻塞），后台 enrich 拿 `intent` / `sentiment` / `humane_summary`
- **错误全兜底**：Agent 任何异常被 `_handle_chat_failure` 拦截 → ProblemMemory + ErrorReviewer，UI 永远拿到兜底文本
- **计划持久化**：pending plan 存 SQLite，刷新页面 / 重启不丢，下次能续上"确认"
