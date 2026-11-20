# 本地 H3 既有一分钟剧本串行续行

用户要求自动派发直到当前剧本结束。本次仅复用已成功的 H3 S01，继续既有一分钟试片的 S02、S03、S04，最后合成完整片。不新增文本、云端模型或发布调用。

独立入口 `scripts/run_h3_six_children_batch_20261102.py`；新目录 `data/video_generation/h3_six_children_60s_20261102`。保持已有 8190 服务和 S01 的 input/output 根，不重启、不改 S01 原记录。新增参考图使用唯一名称，输出使用 `six_children_60s_20261102/S0x/` 前缀。

prepare 冻结三份原 Seedance PROMPT、三张完整 API 图、代码、辅助代码、CPU 原生校验器、模型文件标识及 S01 成功 receipt/history。每段原生 736×1312、362 帧、24fps、12 步，INT8 FL2VA 和原音视频 VAE，不加 LoRA。与 S01 相同图，只变原段提示、确定种子、前段原生尾帧名称、保存前缀。交付中心裁切 720×1280，不放大，H.264 CRF18、原音轨 copy。

根代理审核冻结 PLAN 后写入 PRIMARY_DISPATCH_REVIEW.json：`approved_for_remaining_three_and_assembly=true` 和 `plan_sha256`。运行时持整个 batch 的进程锁：校验前段已知成功历史和所有文件 SHA→复制原生尾帧到服务 input→冻结前代绑定→CPU validate_prompt（不执行节点）→核对服务路径/离线模式/队列为空→持久 claim→一次 POST→原 ID 查询→保存原生音视频和原生首尾图→技术校验及裁切→下一段。

提交响应未知、历史不符、原生执行失败或任何技术校验失败均停止后继段。已知 ID 恢复只查询，不重发；未知 claim 永久保留。单段及 batch 各有 STATE，异常原样记录。不根据空队列推断任务成功。保存阶段发生中断时保留已有输出，未获得本地完成回执的编码文件不会静默覆盖。

最终按每段 362/24 秒设置 concat 时间边界，画面 stream copy；每段声音 apad/atrim 到对应视频时长，再拼接并编码 AAC。完整片应为 1448 帧、24fps、720×1280、约 60.333 秒。检查容器元数据和视频 packet PTS 连续性，不观看、不听音、不 ASR、不从生成视频抽图。技术完成不等于内容通过，始终 awaiting_human_review。

离线测试包含串行三次 POST、尾帧承接、已保存幂等、未知不重发、原 ID 恢复、前代及冻结输入变更、空闲队列、审核门、完整 batch 锁和输出边界。另用本地纯色/静音合成测试检验真实 ffmpeg 的时长、1448 帧、音轨和 PTS 门；不读取生成视频内容。最终测试结果见 data/qa/h3_batch_smoke_20261102.xml。

本文件初稿阶段尚未派发剩余媒体任务；实际执行记录以新 batch 的 STATE、各段 SUBMISSION_CLAIM/RESPONSE、HISTORY 和 receipt 为准。

## 校验启动超时及明确续行

原 batch 在 S02 的 CPU 原生校验启动阶段 180 秒超时，尚无 POST/claim。旧 STATE、PLAN 和 runner 原样保留。缺陷是原 subprocess.run 只在成功返回后保存 stdout/stderr，超时丢失初始化日志；因此不能断言原超时的唯一根因。只读检查没有残留校验进程，RAM 可用约17.5GB；8190原服务正常。

复用原服务的 D 盘缓存环境、明确 ComfyUI cwd，诊断运行同一 S02 图 10.64 秒校验成功。新增独立入口 `scripts/run_h3_batch_validation_resume_20261102.py` 和新根 `h3_six_children_60s_20261102_validation_resume`，CONTINUATION.json 绑定旧失败 STATE/PLAN、旧命令、新入口、包装器及共享缓存记录。不是覆盖旧冻结代码。新入口 stdout/stderr 从启动即写文件，45秒周期保存 Python 栈，300秒上限；超时保留证据且只处理本次启动的确切校验进程树，不触及8190服务。

17项针对回归通过，包含超时日志留存、失败不放行、共享缓存、原ID恢复和实际纯色/静音 ffmpeg 合成。新根 S02 原生校验再次真实通过，约7.5秒，valid=true、无节点执行、无媒体提交。审查需同时绑定 PLAN 和 CONTINUATION 的 SHA；S03/S04 自动使用同一已验证的新校验入口。证据见 data/qa/h3_validation_resume_20261102.xml、新根 S02/VALIDATION_PROCESS.json 和 NATIVE_VALIDATION.json。
