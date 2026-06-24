# 系统架构

四层架构 + 横切关注点（Memory / Scheduler / LLM）。

```mermaid
graph TB
    subgraph UI["📱 UI 层"]
        Web[Streamlit 管理后台<br/>12 个页面]
    end

    subgraph AGENT["🧠 Agent 编排层"]
        A[Agent.chat]
        SR[SkillRegistry<br/>18+ Skill]
        P[Prompt 构建器]
    end

    subgraph MEM["💭 Memory 横切"]
        MLM[MemoryLayerManager<br/>preference/problem/discarded]
        MM[MemoryManager<br/>profile/session/messages]
        HR[HumaneRecorder]
        PC[ProblemMemory]
    end

    subgraph SCH["⏰ Scheduler 横切"]
        CRON[APScheduler]
        TQ[TaskQueue Worker<br/>SQLite SKIP LOCKED]
        ER[ErrorReviewer<br/>LLM 异步诊断]
    end

    subgraph SVC["⚙️ Service 编排层"]
        GS[GenerationService]
        APS[AutoPublishService]
        VS[VideoService]
        CS[CommentService]
        RHS[ReplyHistoryService]
    end

    subgraph CF["🎬 Content Factory"]
        RAG[RAG / Chroma<br/>向量检索]
        SC[ScriptGenerator]
        TTS[TTS Engine<br/>Edge-TTS / GPT-SoVITS]
        PR[PresenterPipeline<br/>动漫数字人主讲]
        FF[FFmpeg]
    end

    subgraph PA["🌐 Platform Adapter"]
        DA[DouyinAdapter<br/>发布/同步/评论]
        FA[FanqieAdapter<br/>番茄推广]
        DW[DouyinWarmup<br/>多账号养号]
        SEL[Selenium / Playwright]
    end

    subgraph STORE["💾 Storage"]
        S1[(wisdom_ai.db<br/>Agent / Memory / Schedule)]
        S2[(douyin.db<br/>业务数据)]
        S3[(chroma_db<br/>向量索引)]
        V[data/videos/<br/>生成视频]
    end

    subgraph EXT["☁️ External"]
        ELLM[Ollama / DeepSeek<br/>OpenAI 兼容]
        ETTS[Edge-TTS / 微软<br/>云端 TTS]
        ECOM[ComfyUI<br/>SDXL 背景生成]
    end

    Web -->|用户消息| A
    A --> SR
    A --> P
    A --> MLM
    A --> MM

    SR -->|调度| GS
    SR -->|调度| APS
    SR -->|调度| VS
    SR -->|调度| CS
    SR -->|调度| RHS

    GS --> RAG
    GS --> SC
    GS --> TTS
    APS --> PR
    PR --> FF
    PR --> TTS
    PR -.可选.-> ECOM

    DA --> SEL
    FA --> SEL
    DW --> SEL

    A -.诊断.-> ER
    CRON --> TQ
    TQ -->|执行 Skill| SR

    TQ -->|状态 / 结果| S1
    ER -->|诊断记录| S1
    A -->|对话/计划| S1
    MLM -->|分类| S1
    MM -->|会话/用户| S1
    PC -->|问题跟踪| S1

    DA --> S2
    VS --> S2
    CS --> S2

    RAG --> S3
    PR --> V

    A -->|调用| ELLM
    TTS -->|调用| ETTS
    ER -->|调用| ELLM
    P -->|调用| ELLM

    classDef ui fill:#e3f2fd,stroke:#1976d2
    classDef agent fill:#f3e5f5,stroke:#7b1fa2
    classDef memory fill:#fff3e0,stroke:#e65100
    classDef scheduler fill:#e8f5e9,stroke:#2e7d32
    classDef service fill:#fce4ec,stroke:#c2185b
    classDef factory fill:#e0f7fa,stroke:#00838f
    classDef platform fill:#f3e5f5,stroke:#6a1b9a
    classDef store fill:#eceff1,stroke:#455a64
    classDef ext fill:#fff8e1,stroke:#f57c00

    class Web ui
    class A,SR,P agent
    class MLM,MM,HR,PC memory
    class CRON,TQ,ER scheduler
    class GS,APS,VS,CS,RHS service
    class RAG,SC,TTS,PR,FF factory
    class DA,FA,DW,SEL platform
    class S1,S2,S3,V store
    class ELLM,ETTS,ECOM ext
```

## 关键模块

| 层 | 模块 | 职责 |
|---|---|---|
| UI | Streamlit | 12 个页面：看板 / 视频 / 评论 / 自动回复 / 规则 / 违禁词 / 知识库 / 用户 / 对话 / **我的记忆** / **任务调度** / 设置 |
| Agent | `Agent.chat()` | LLM 决策 + 计划生成 + 用户确认拦截 + 失败兜底 |
| Agent | `SkillRegistry` | 18+ Skill 统一注册：内容 / 平台 / 养号 / 番茄 / 知识库 / 记忆 / 系统 |
| Memory | `MemoryLayerManager` | 自动分类 preference/problem/discarded + 滑动窗口 + 问题去重 |
| Memory | `MemoryManager` | 用户画像 + 会话/消息 + 待确认计划持久化 |
| Scheduler | `APScheduler` | cron / interval 触发 → 入队 |
| Scheduler | `TaskQueue` | 后台 Worker 抢任务 → 调 Skill → 重试 / 错误诊断 |
| Service | `GenerationService` | 脚本 / TTS / BGM 编排 |
| Service | `AutoPublishService` | 一键生成并发布 |
| Factory | `PresenterPipeline` | 动漫数字人主讲：Edge-TTS + Sonic + ComfyUI + FFmpeg |
| Platform | `DouyinAdapter` | Selenium 浏览器自动化：发布 / 同步 / 评论 / 回复 |
| Platform | `DouyinWarmup` | 多账号养号：随机观看 + 评论区浏览 + 可控点赞 |
| Platform | `FanqieAdapter` | 番茄小说推广 MVP |

## 数据流

```
用户消息
  ↓
Memory 分层入库 (preference / problem / normal)
  ↓
Agent 加载上下文
  ↓
LLM 决策
  ↓
Skill 执行（写操作前先确认）
  ↓
结果 → 写入视频文件 + DB
  ↓
异常 → ProblemMemory + ErrorReview (LLM 自动诊断)
```
