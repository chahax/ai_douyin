# 游戏与H3并发实测

用户询问当前占用能否跑模型，确认游戏很小后要求“试一试”。本轮一次真实15秒档位测试，768×416、12步、24fps、362帧、FL2VA及原生音轨保持，使用固定旧双人开场图作为负载夹具。不是故事S05或旧段自动重试，不修改旧稿/回执/账本/失败3/10，不关闭或改动游戏、驱动、服务或模型环境，无新模型/图像/外部文本调用。

独立根`data/local_media_tests/h3_game_concurrent_20261018`。3项必要guard测试通过（1.95s），原生校验valid=true/node_errors={}；主助手已读完整新runner/CLI/telemetry、必要测试、实际图/参数/固定图身份，并修核线程CPU首样本未知及慢采集不追赶规则。图仅变prompt/固定图输入/seed/保存前缀，实际图SHA `f31359857cc66e9543dc7f2c78096caf8d1e276a548d2385bc041101b2b0493b`。单次主审门SHA `93224071142324d3ad38bbeb47f0e0a7324fe48bf20bb4d03984a15cfaf600fd`。

游戏PID37860、name/create_time绑定并在派发前复核。baseline先采再POST，每10秒只读nvidia-smi/psutil/Windows提交量、游戏存活/RSS/CPU，保留JSONL及错误/未知null，不把未知写0。只记录采样峰值，不能证明瞬时峰值或以进程存活代替FPS。用户在采样初始化阶段反馈“正常可玩，没明显变化”，单列真实用户反馈，未测FPS或把反馈外推到未来所有负载。

唯一原ID `65e54e4a-5aa7-4aa4-b58b-e86e040158c0`，21:54:03受理，日志offset53775。本段新永久claim独立，未知不重派，有ID只查原任务；实际完成以receipt/HISTORY为准。最终收集只核接口/实际图身份/容器包/帧数/尺寸/时长/音轨、原PNG编码CRC及原文件副本SHA，不听看/抽帧/ASR或内容审核，视频awaiting_human_review。

## 实际结果

H3与游戏同时运行的单次15秒档位测试成功，原run完成最终telemetry样本/汇总后exit0。HISTORY服务执行1339.626秒（22分19.626秒），提交至保存1365.741秒（22分45.741秒）。15.083333秒、768×416、24fps、362帧H.264 MP4含AAC 32kHz双声道473包，原生FLAC210包与服务首尾PNG另存、CRC有效。主助手独立执行`verify_benchmark.py`核实际请求/历史图、原文件副本SHA、包/帧数及raw-summary一致，`PRIMARY_BENCHMARK_VERIFICATION.json`保留证据。

131份原始资源样本，游戏PID/name/create_time在全部样本中一致存活，unknown0、采集errors0。显存采样峰15638MiB（约15.27GiB），最低剩358MiB，GPU最高99%、62°C、238.26W；系统CPU采样峰63.7%，物理可用内存最低6845952000字节（约6.38GiB）。Windows提交量峰52188102656字节，提交上限自动增大，不能用峰值提交量减最小上限；逐样本提交余量最低5323390976字节。目标采样10秒，实际最大间隔65.90秒；仅代表采到的极值，不能证明未采到瞬时峰值或两样本间持续状态。原始JSONL SHA `b7b4f47529db07e18772893f50f3a48eb6aeef17b9a434766b6c6f87cd119f36`，summary SHA `56cb4088d505b7cdd6b1b37caacac7bdfeee007086a03278562fe032299665f0`。

用户在测试中真实反馈“正常可玩，没明显变化”；自动FPS/流畅度仍null，不声称测过全程帧率。实测结论限于这款游戏当前状态与这个H3档位；未将其外推到其他游戏/模型。生成文件技术完整，内容仍awaiting_human_review，旧四段及失败3/10未变，一次POST、0重试、无发布。

实际测试片：`D:\IT\ai_douyin\data\local_media_tests\h3_game_concurrent_20261018\deliverables\game_h3_15s_with_audio.mp4`，SHA256 `884040dd5bc7f951fdc0edfb46989c2c27f1aea7add6cfcdff87a701832545ed`。
