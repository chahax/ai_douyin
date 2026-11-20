# 项目定位

本 Skill 创建并更新于 2026-10-26。以下为定位线索，执行时以当前代码和任务证据为准。

## 最新开发结果（v5）

独立入口 `scripts/run_story_first_production.py` 新 prepare 默认v5；核心为 `src/content_factory/story_first_contract_v5.py`、`story_first_production_v5.py`，测试 `tests/test_story_first_v5.py`，旧版本仍保持。

已实现逐场生成、输入及前态绑定的场次复用/依赖失效、原生结果及SHA核对后的显式前缀采纳、硬伤独立核验。模型只输出introductions和动作changes，程序保留原生delta并计算前后状态，不要求模型抄写已知前态；新槽位不能覆盖既有id/身份。prop关联人不必参与动作，知识与位置主体须参与。自动跨进程恢复未实现。

本轮144项回归通过，v3/v4/v5合计32次MiniMax真实调用、441492 reported tokens，DeepSeek实际0。完整60秒候选仍needs_revision：过去场景与当下回忆者意识混用，审核把两个时间线当同一时点，主线进入偏慢。没有整链内容通过，不能据此生成视频。当前任务均已结束pending=null，不重跑。

最新说明：`docs/STORY_SCENE_V3_20261026.md`；验收：`data/qa/story_scene_v3_20261026/ACCEPTANCE.json`；原始输入输出与独立复核：`data/corpus_production_trials/20261026_story_scene_v5/`。真实69章外发阻塞保持。

后续优先区分：过去画面里人物当时的状态、当下回忆者的知情、当下配音的发言时点。不同时间线不能仅因剪辑相邻就要求状态值完全一致。审核要求补信件来历时，先检查原文是否已提供；未交代不等于事实矛盾。

## 创建时的历史线索（v2，已被上述状态取代）

项目根目录：`D:/IT/ai_douyin`。

- `scripts/run_story_first_production.py`：独立 story-first CLI；创建时新 prepare 默认 v2，旧 corpus/Fanqie 网页没有全部切换。
- `src/content_factory/story_first_contract_v2.py`：Schema、提示、验证、证据目录与渲染。
- `src/content_factory/story_first_production_v2.py`：模型调用、账本、阶段生成与返修。
- `tests/test_story_first_v1.py`、`tests/test_story_first_v2.py`：相关回归；在项目 data/qa 下创建独立临时目录后执行，避免影响业务数据库。
- `docs/STORY_FIRST_PRODUCTION_20261026.md`：最近真实失败说明。
- `data/corpus_production_trials/20261026_story_first_v2/PRIMARY_REVIEW.json`：助手独立复核。
- 对应 `run/PLAN.json`、`STATE.json`、`CALL_*.json`、`RESPONSE_*.json`：真实输入输出及终态。

创建时状态：78 项相关程序测试通过，真实合成三章《两把钥匙》生成60秒候选，但调度整稿返修 length，尚未通过内容验收，DeepSeek未实际进入终审。前序使用 MiniMax-M3.1-Flash，Qwen不参与；DeepSeek仅终审。逐场调度、精细依赖失效、完善跨场状态表及审核有效性裁决仍待实现，不能因本 Skill 存在就宣称已经部署。

已结束的v1/v2试验不得重跑；真实69章小说仍有既有外发审批阻塞。使用既有合成材料进行新测试也应沿当前任务授权及记录，不默默复用旧任务预算。

此 Skill 不内置密钥、账号环境或服务启动操作。项目迁移时先定位等价模块，不假定这些历史路径总是当前入口。
