# 全流程质量 v8 实施合同

用户2026-10-18要求“改造重新输出一版给我”，承接[全流程计划](NARRATIVE_VIDEO_WORKFLOW_QUALITY_PLAN_20261018.md)。本轮实施新版本、测试并真实输出完整新稿/导演/最终提示词；没有新的媒体或发布调用。

## 模块边界与接口

1. 通用规则、角色提示与导演/编译：`narrative_quality_v1.py`、`novel_agent_roles_v8.py`、`novel_director_handoff_v8.py`。角色和导演公开API兼容v7运行器已有调用签名；新director整份原生稿可在segments中增加逐拍互动/摄影信息，完整保留原文。新增纯函数 `compile_video_requests(director)`，输出覆盖所有导演段的实际Seedance SDK请求与可读自然语言prompt（不调用API、不带凭据、不自动选第一条表演）；审核build/verify/make_handoff消费同一编译结果。共用规范由`quality_policy()`返回可冻结内容/版本/哈希，writer/director/review均消费同一规范。新增 `validate_handoff_for_dispatch(handoff)` 只核对同源规范、语义审核、完整请求映射和实际请求一致性，不授权POST。
2. 新运行器：`novel_agent_pipeline_v8.py`、`novel_agent_graph_v8.py`。保留v7实际派发、原生响应/用量/未知停止、LangGraph、同稿审查、场记和预算链，接入v8角色及导演/最终请求审核。支持 `prepare(..., source_kind='novel'|'original', ...)`、`prepare_quality_revision(run_dir, parent_run=...)`、execute/preview/inspect/recover_projection。旧v5/v6/v7任何模块和冻结不改。
3. 新默认入口：`scripts/run_novel_agent_v8.py`、`src/web/novel_agent_panel_v8.py` 和主导航必要接线。新小说/原创剧情入口走同一v8规范和最终交接；旧v7 CLI/面板源码保持，旧任务仍可只读/原ID恢复。不修改已冻结通用v23生产源码以覆盖旧任务。具体网页入口范围如有差距须如实报告。

子agent分别拥有上述三组及各自独立tests；主agent审查实际接线、派发前请求和跨故事证据。共享API如需改变必须先通知其余模块负责人。

## 新导演与编译要求

服务生成段按完整互动规划，当前选定Ark Seedance 2.0 Mini能力4–15秒，720p/9:16/原生音频；时长由内容决定，不固定15秒，不靠字数或每秒动作作语义质量判定。逐拍包含参与者、刺激、动作对白、听者反应、目光对象与转移、头身朝向、构图/可见性及信息变化。合理沉默/避视/单人或画外音可成立。程序核对引用、覆盖、时间和编译一致性，DeepSeek判断实际表达。内部证据留本地，不能把scene_ledger/evidence_refs JSON拼进视频表演文本。

同源整包导演审核必须包含源文、完整新稿、导演、全部最终请求文本；只审导演不审最终请求不合格。返回major/blocking则按责任层有界返修，不能改原生判词或通过手工文本包装放行。

## 本次真实续修与继承

本次从已完成v7父运行 `data/novel_agent_production/20261018_original_trial_v7/run` 重新完整创作，不复用已被用户拒绝的视频/尾帧。保留父5次/88362 reported tokens、原总上限20次/500000以及原导演返修1/1已耗尽记录。

用户本轮新要求授权独立质量修订：最多新3份完整writer稿（初稿＋2轮明确内容返修）、最多新2份完整director候选（初稿＋1轮明确内容返修），及范围内必要同稿审核；新阶段用量单列并累计，不把旧director_revisions_used归零或改旧上限。本次所有新调用仍限制在父链剩余15次/411638 reported tokens，未知结果/用量或截断停止，SDK无自动运输重试。新续修永久claim按父来源/原稿/质量版本绑定，不能换目录重领。

跨故事开发和留出样例在运行前冻结；离线真实链条与不同题材入口先验证，再在文本有效授权内做必要真实验收。当前故事的新输出优先交付；跨故事未完成不能宣称普遍质量通过。

本轮完整文本与最终请求预览不是视频通过，不自动POST视频。历史媒体2次提交、失败2/10（1服务拒绝＋1用户拒绝）继续保留；任何后续视频仍需有效单段范围和用户人工审片。
