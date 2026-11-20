# 渡口压缩版10秒首段独立试片

用户“试试第一段”仅授权本次压缩编辑候选S01一次视频提交。候选由主助手编辑，未冒充MiniMax新完整稿或DeepSeek重新验收；旧v10文本与已耗尽10轮campaign不改。新入口是 `scripts/run_compact_ferry_video_trial_v1.py`，提供prepare、submit、query、inspect；不接S02、不自动重试、不发布。

实际输入固定Ark Seedance 2.0 Mini、10秒、720p、9:16、原生音频、返回服务原始尾帧，纯文本无参考图。冻结完整建议稿、PROPOSAL、FIRST_SEGMENT、AUTHORIZATION、PROMPT、实际SDK请求、执行模块与客户端/结构检查辅助模块的文件身份。旧退回视频及原尾帧不作为输入；其他H3故事的参考资产不进入本片。

沿用原渡口来源身份和历史2/10失败，只读绑定原story计数器SHA。新增范围在原registry的 `compact_ferry_20261018_S01` 子目录保存永久一次claim及MEDIA_EVENTS；与旧故事共用 `.registry.lock`，派发前核对继承失败与新增已知失败合计未达10。新增失败只进本范围事件账本，保留旧计数器字节。换目录不重新获得派发机会。

POST前先持久保存唯一claim和submit_outcome_unknown；未知结果不能重派。原生ID已保存而状态写入失败时，可通过query恢复原ID，仅发GET。GET或下载中断可再次查询/保存同一结果。4xx明确拒绝及原生终态失败幂等累计，未知消耗保留null，不写成零费用。

成功后仅保存服务原视频/原尾帧，核对文件SHA、JPEG/PNG编码结构及ffprobe容器/包完整性；10秒容器接受9–11秒、720×1280与非空原生音频流。无抽帧、像素解码、听看、ASR或模型音画审核。技术成功记awaiting_human_review；用户实际反馈后再决定后续。

离线测试覆盖10秒无图实际载荷、跨目录重复POST、源/授权/代码请求绑定、未知POST永久claim、GET-only状态恢复、查询/下载中断、失败幂等和竖屏声音容器门。模拟测试不代表真实视频内容通过，实际命令与结果由主助手另存。
