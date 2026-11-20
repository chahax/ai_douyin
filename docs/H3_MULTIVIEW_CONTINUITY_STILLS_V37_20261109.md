# 多视图身份与真实尾帧连续编辑 v37

这是独立的图片生产器 `visual_multiview_continuity_stills_v37.py`。v36 的代码、图像、视频和失败反馈都保留，不原地升级旧 PLAN。

本轮两项机制变化：一是每个角色实际接入同版本正面＋本镜明确角度的像素，不再只有正面人物图；二是后继首图必须以本轮前一段原生视频实际保存的 last PNG 编辑，不能只记录尾图出处却另造一张独立首图。

## 输入顺序

| 首图 | 正向 ReferenceLatent 输入 |
| --- | --- |
| S01，共 7 张 | 旧 S01 房间/服装布局母图 093d644c…；苏墨、叶南、叶西决正面各一张；三人本镜角度各一张 |
| S02—04，各 8 张 | 本轮前一段 video RESULT.files.last；本轮 S01 实际已保存的新首图；三人正面；三人本镜角度 |

后继第二张参考改用本轮已建立的 S01 现场照片，减少反复输入旧正面合影布局的偏置。这张图给同一演员、房间、材料和服装的上下文，前段实际尾帧才是当前身体位置、动作、朝向的权威。第二参考仍含人物，不是硬性人像隔离或像素锁定；不能保证模型一定按权重执行。

三人 front 与 angle 从 `data/serial_story_assets/INDEX.json` 取确切记录。每对必须一致的字段包括 book_id、entity_id、identity_group、design_version、version，并核实际 PNG SHA 与元数据。角度图只用于从侧向认同一个人，不能把参考图的正面姿态和眼神强加给表演。

| 段 | 苏墨角度 | 叶南角度 | 叶西决角度 |
| --- | --- | --- | --- |
| S01 | right_oblique | left_oblique | right_oblique |
| S02—04 | right_oblique | left_oblique | left_oblique |

这些是已有资产的视图标签和输入选择，不是锁死演员或视频机位的空间命令。根据本段剧情，哥哥主要看弟弟，弟弟由看哥哥转为看父亲，父亲看孩子或面包。下一段编辑只改变源起点确实要求的闭/睁眼、床边姿态、面包归属或必要遮挡，保留实际尾帧已成立的其他状态。

## 接口与真实原件校验

`prepare(spec_path, run, authorization=None)` 纯 CPU 冻结规范和静态顶层 PLAN。初始四段均为 unprepared，不伪造未来尾帧。

`prepare_shot(run, sid, prior_video_result=None)` 每次只准备一段。S01 不传前段。S02—04 必须传 `{path, sha256}`，路径严格是同一 video_run 的 `shots/S前段/RESULT.json`。核验技术 saved、STATE 同原 ID、HISTORY 原 ID 成功、原 graph、四件原文件 SHA、last 实际 PNG 尺寸；还核该 video 的输入首图 SHA 确实来自本 scene 对应图。缺原件、未知、错轮次、错尺寸、改 SHA 都不派生后继图。

生成的 graph 确认全部 7/8 张图经真实 `LoadImage → VAEEncode → ReferenceLatent` 位于当前 sampler 的正向祖先链。S02—04 第一输入必须是实际 prior_video_tail，第二输入必须是 current_run_S01_scene。将尾图只放负向、只存 provenance、断开一张角度图或调换身份槽均拒绝。

每段冻结 `prepared/Sxx/SHOT_PLAN.json`，原生图片任务放 `jobs/Sxx`。顶层静态 PLAN 不因下一段尾图出现而覆写。

`submit_next(run)` 每次至多一个原生图片任务。已有原 ID、未知、失败、尚未准备的下一段均不会重复 POST 或跳过。生产器最多四次新图提交；协调器负责用户本轮总工程额度与全局 GPU 锁。

`collect_known(run)` 只按已知原 ID 收存冻结图与快照，不因外部原照片、授权或前段记录后来变化而重发未知任务。新派发前仍重新核当前绑定原件，避免在不一致输入上继续。`status`、`result`、`complete`、`budget` 与协调器保留小接口。

回执包含实际 PNG、原 jobs RESULT binding、native_id、prior_video、room_context、positive_reference_evidence 和六张身份参考的具体版本。`user_review_pending=true`、`production_approved=false`，没有 VLM、ASR、OCR、正脸或人工内容审核门。测试不会打开生成图作内容评判。

## 技术边界

本层验证输入和原 ID/保存协议，不能保证模型不会偏移身份、添人、重绘房间或烧字幕。测试中的本地 HTTP、纯色 PNG、明确标记的视频协议夹具没有运行模型，不当作生产媒体。实际效果由本轮完整分钟交用户审核。
