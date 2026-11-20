# 本轮由主助手直接改稿与H3首段重生成

用户在上一轮候选追加问题中明确答复：“只要你修不要用其他模型修，你是不是让deepseek和miniamx修了”。本轮直接由主助手编写、核查完整稿；不再把修稿或文本复审发给MiniMax、DeepSeek或其他外部文本模型。没有获得新增两份外部候选的批准，也不需要以新增外部候选名义登记助手自己编写的文件。

此前637、638、639、640是MiniMax调用；这几次修订没有派发DeepSeek复审。历史结果保留，累计640次、13544245 reported tokens及历史未知不变。旧634/638/640三份完整稿容量已用完，原导演7/7不变。此次不把助手自查写成模型原生结果、机器全文审查或用户采用。

## 实际产物

完整稿：`data/video_generation/h3_project_script_20261015/revision_02/assistant_authored/FULL_SCREENPLAY.md`。12段，每段15秒，共180秒；先交代世界、人物关系、同一清晨时间、空间和道具，再逐段写两人的动作神情、视线、对白时窗、刺激反应与因果衔接。

首段结构源：同目录`FIRST_SEGMENT.json`，标注`primary_assistant`。桂芳已在屋内核库存，经理跨门即说话；当提出店里减人而要求填个人原因时，她停笔抬眼追问；经理回避而未解决疑问。

同目录`PRIMARY_TEXT_REVIEW.json`仅是主助手的文字自查；`USER_DIRECTION.json`保存本次指令与范围。结构提取与哈希由本地程序绑定，不是外部模型调用。

## 实际媒体接线

`revision_02/media/prepare_media.py`增加`assistant_authored_primary_v1`独立分支，保留旧native及machine分支。主助手审查实际源、工作流与参考映射后，单次提交`a7b8c0d5-8ec7-4763-adaa-4cbeacd7a0f1`，graph SHA `b17945cf1589a4ec5685776b29b19d3187a55ece8f6b74cbb53c7c7903fdc672`。

目标：H3 REF2VA，原生1280×704、24fps、362帧，约15.083秒，20步，无turbo、无放大节点。Picture1固定背景，Picture2固定桂芳身份，Picture3固定经理身份；不使用此前拒绝片尾帧。ComfyUI原生参数验证成功；这只证明图可提交，不证明高分辨率实际生成或内容符合要求。

本轮只授权这一个修订首段。接口未决时查询原ID，不自动重试、降档或续段。全部文件与缓存在D盘。视频、音频、原生首尾帧只做接口及保存完整性检查，状态`awaiting_human_review`，由用户看片；不能把接口成功写成内容通过。

## 本次离线核对

主助手运行10项来源、时序、预算门与派发约束检查通过；实际原生图验证`valid:true`、`node_errors:{}`，提交门`eligible:true`。新增源分支不要求伪造机器全文通过；演员身份图SHA、固定场景SHA、完整稿SHA和首段SHA进入实际提交证据。

后续实际结果以`revision_02/media/RUN_STATUS.json`及`TECHNICAL_RESULT.json`为准；有submit回执不等于视频已保存。旧回执、未知历史与同故事一次用户拒绝保留，不重置。
