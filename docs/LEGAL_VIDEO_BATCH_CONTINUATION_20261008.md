
# 本次法律片整批尾帧续段（2026-10-08）

用户原请求“继续直接生成完”，明确答复：“本次改为原始尾帧连续生成，全部完成后统一人工审核”。
仅本次《那张纸今天先留在这儿》的剩余 B1.S05–B4.S06 采用这一例外。SH03B 仍待人工审核，授权允许使用其服务返回的原始尾帧；不伪造内容批准。冻结导演交接、历史任务、账本和默认逐段批准规则不修改。

实际授权和源绑定：[BATCH_USER_AUTHORIZATION.json](../data/video_generation/legal_trend_20261008/remaining_batch_v1/BATCH_USER_AUTHORIZATION.json)。
完整请求说明：[ALL_PROMPTS.md](../data/video_generation/legal_trend_20261008/remaining_batch_v1/ALL_PROMPTS.md)。
来源仍为已采用全文、完整导演与实际表演的 d1 交接。

剩余19个源步骤、197秒源窗口，确定性投影为21次请求、206秒服务时长。四句长对白在原句标点处拆分，全部字符顺序不变，发话前后窗口只在对应首/末部分出现；中间发话时长按字符比例分配。这是接口投影假设，实际语速、口型和表演节奏待人工审核。整数上取整产生的额外时间不能解释为新事件。

沿用 ark_api / doubao-seedance-2-0-mini-260615 / 480p / 9:16 / 同期声音 / 返回原始尾帧。每次提交前验证原稿、批次定义、相邻前段视频和原始尾帧哈希，以及实际提示词。按原同稿失败账本登记，默认10次失败上限，不重置。创建结果未知且没有ID时停止，已有ID仅续查，实际失败停止且不自动重生成。

34项相关离线检查通过（pytest缓存路径警告不影响检查）。检查覆盖全文及各窗口无丢失、长动作与跨状态对白禁止机械拆分、未经批准的尾帧仅在本片显式批授权内可用、替代尾帧/换片/换模型/改提示词/错序被拒绝，以及既有未知结果不重提交门。离线通过不表示接口完成或创作质量通过。

完成后仅技术合成原始视频和声音，不抽帧、听看、ASR或自动内容审核。全部新片段与完整审片文件均记 awaiting_human_review；发布未授权。



## 实际请求范围修正

LG01提交后读回实际请求，发现整镜new_information混入下一步催签对白。本地派发器暂停，LG01保留原ID、原请求和来源，不重生成。
后续请求使用v2渲染：整镜新增信息与未来对白不进入当前发话指令，当前原句在实际提示词中只出现一次。修复后14项离线检查通过；不是对LG01内容的质量判定。
查看 [原请求问题记录](../data/video_generation/legal_trend_20261008/remaining_batch_v1/PROMPT_SCOPE_REPAIR.md)、[后续提示词v2](../data/video_generation/legal_trend_20261008/remaining_batch_v1/ALL_PROMPTS_v2.md) 和 [实际批次进度](../data/video_generation/legal_trend_20261008/remaining_batch_v1/PROGRESS.json)。v1提示词保留作为历史。

