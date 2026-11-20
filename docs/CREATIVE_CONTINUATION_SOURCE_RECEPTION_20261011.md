# 来源引用表演修订（2026-10-11）

用户要求直接开始，MiniMax调用不逐次确认。本次针对完整502工具原生稿的内容失败，修订独立表演合同并生成整份当前段新稿，保留原稿和实际消耗。不是重新申请格式恢复或采用手工删句后的502。

## 已验证原因与修改

502在小林的刺激接收、说话方式两个自由说明字段复抄B1.S03原对白。旧编译器同时从源文注入正式对白，因此严格拒绝有依据。502还要求先抬眼再读纸，与前段文字计划中目光已在申请附近的终态冲突；助手未检查像素，不把文字计划当作实际尾帧观测。

新 `creative_continuation_probe_contract_v3` 用 `source_reception.stimuli` 保存来源/通道，`response`只写接收反应；`dialogue_delivery`按当前对白来源写语气与听者反应。确定性编译保留完整模型原生稿及映射，不改写模型表演文字，正式对白仍只从源文插入一次。复制台词、错误类型、自己的对白当听觉刺激、未来来源或投影篡改仍拒绝。自由表演文字与通道的真实语义仍须独立八项审查，结构校验不证明创作质量。

## 入口与范围

`scripts/run_selected_script_continuation_v4.py`从502完整已知失败继承502次调用、7,708,554 reported tokens、500次已知用量、93117历史未知预留及70/160待核记录。新入口只登记一次完整内容修订，原内容修订序号从1承接到2；已耗尽的格式恢复次数为0。相同请求重放用原回执，不因改目录再领调用。

当前只做B1.S03/B1.S04：周姐请签，小林看清纸面“个人原因”；不给纸面文字配成周姐对白，不提前推纸笔或质问。文本通过后只允许一次480p Seedance Mini第二段，输入为已批准首段服务原始尾帧。视频及尾帧保存后待用户人工审核，助手不抽帧、听看、ASR或媒体审核。

## 结果定位

离线验证：`data/qa/creative_continuation_source_reception_20261011`。新冻结文本/账本：`data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v4`。视频目录：`data/video_generation/legal_script487_trial_20261011/second_v4`。这些地址不提前表示生产成功；以实际回执和结果记录为准。

## 本次文本与提交结果

集中离线13项通过。实际MiniMax503提交完整新结构演法，编译有效，7514 reported tokens；DeepSeek504同源八项审查全pass，8105 reported tokens。两次最终SDK请求正文均已保存，参考全文与冻结输入相同。8秒当前段只含请签与读到纸面“个人原因”；没有提前移动纸笔或进入质问。机器文本审查不等于实际视频通过，助手没有检查原尾帧像素。

已一次提交第二段，服务任务`cgt-20261011223449-wsn9f`；首帧实际字节SHA与批准原始尾帧一致。实际视频保存结论见[本次结果记录](../data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v4/PRODUCTION_RESULT.md)，提交时检查点见[提交证据](../data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v4/VIDEO_SUBMISSION_CHECKPOINT.json)。原502失败、格式恢复耗尽、旧未知记录保留，累计504次/7,724,173 reported tokens，不重置账本。
