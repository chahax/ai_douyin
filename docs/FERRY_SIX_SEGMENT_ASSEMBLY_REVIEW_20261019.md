# 《渡口的单程票》六段合成审片版与费用

用户明确要求“多少成本合成下所有视频”，按[本次计划](FERRY_SIX_SEGMENT_ASSEMBLY_PLAN_20261019.md)将当前新标准S01—S06顺序合成。唯一来源为`SERIES_DELIVERY_MANIFEST_20261019.json`，未混入旧退回版本、失败试片或其他故事。

交付[完整审片版](../data/video_generation/novel_ferry_timing_v2_trial_20261018/assembly_20261019_v1/deliverables/full_ferry_review.mp4)：49.250秒，720×1280/24fps，32873588字节，SHA256=`096ac582ef710e08937b1446acee40f02931028c185fdb42d6b9291e3ffcd357`。

六段1182个原始H.264压缩包按序逐包SHA完全相同，画面未重编码。concat关闭自动码流改写，每段显式按视频duration_ts/time_base接续；主agent独立重算所有视频PTS恰为0起每512 tick连续网格，五处接点无时间空隙，各轨DTS严格递增。音轨只做时间对齐，以32000Hz累计画面边界取整差分为225333、225334、193333、353333、321334、257333样本，合1576000样本，编码为连续AAC192kbps/1541包；处理各源AAC起始延迟，音视频起点均0、各轨和容器时长均49.250秒，ffmpeg无警告。

此前49.568秒为六个独立文件的容器时长之和，含每段略长的AAC尾部；实际视频1182/24=49.25秒。本次按画面接续，没有增加静帧或改变语速。声音接缝、对白完整感、口型和实际观感仍由用户审片，技术检查不证明内容通过。

子agent编写独立合成脚本，主agent审完整代码及实际来源/时间轴后执行一次本地合成；主agent重新ffprobe并核所有原始包、PTS/DTS、SHA和261份旧保存基线。新授权、实际命令/日志、源与输出探针、原始包hash、主审及独立审计均在`data/video_generation/novel_ferry_timing_v2_trial_20261018/assembly_20261019_v1`。原六段、原回执、原尾和当时的未合成索引不改；新回执表达此次合成完成。

六份真实usage共1063800视频tokens。按2026-10-19核实的[官方模型原价](https://docs.volcengine.com/docs/ark/model-pricing?lang=en&redirect=1)23元/百万tokens估算，合24.4674元，约24.47元；仅图片首帧仍属于无视频输入。[四折活动](https://docs.volcengine.com/docs/ark/seedance-2-0-mini-fast-limited-time-discount)已于2026-10-07结束。本次本地合成0新模型/媒体服务调用，不新增模型API费用。原cost:null保留，账户合同折扣/抵扣及实扣未知；不含旧试片、文本创作或本机电费。明细保存于新目录`COST_ESTIMATE.json`。

合成状态`awaiting_human_review`，视觉、声音、口型及接缝评分null。助手未观看、听音、抽帧、ASR或调用内容审核模型；未新增生成或发布，历史失败2/10及文本20次/383259停止保持。
