# 渡口首段本地 H3 试生成结果

用户要求“可以用本地的minimaxh3模型试试这个剧本生成内容”。本次仅试《渡口的单程票》S01一次，未续段、重试、调用云模型或发布。

交付：`data/video_generation/h3_ferry_s01_trial_20261020/deliverables/S01_ferry_416x768_12step_with_audio.mp4`。原生H264带AAC，416×768、24fps、175帧、约7.292秒，1,022,491字节，SHA256 `df777cf37b15c8454f4c97134c828624ca8b86a5d4fb8e4292e7fa376c2a5596`。

唯一原任务ID：`28b126a0-6eaa-4e37-8d76-3f406c2f5a5b`。ComfyUI离线原生FL2VA int8，12步、不使用turbo LoRA或参考图，原生音轨。原7秒剧情沿H3网格生成175帧；仅替换原提示词首行的服务规格，正文逐字保持。原生CPU图校验及主审绑定完成后才提交；最终history核对实际图，仅fps/denoise有已知数值类型规范化。

服务执行673.095秒，约11分13秒，不含此前本地服务启动。旧配置恢复启动较慢，未重复提交。无云模型API调用费用，未估本地电费。原FLAC及服务内保存的首尾PNG已同字节另存；只核容器包、PNG结构及SHA，不看听、抽帧、ASR或判断内容效果。技术成功，内容状态仍为`awaiting_human_review`，评分null。

主审最终核319份旧文件SHA均保持，服务原文件与副本SHA相同、交付副本与原MP4相同，队列为空。同故事失败2/10、文本20次/383259停止不改。原六段及49.250秒合成片保持。

完整证据位于本次独立根：`AUTHORIZATION.json`、`PREPARED.json`、`PRIMARY_TRIAL_REVIEW.json`、`NATIVE_VALIDATION.json`、`REQUEST.actual.json`、`SUBMISSION_RESPONSE.json`、`HISTORY.json`、`receipt.json`、`PRIMARY_FINAL_REVIEW.json`、`SUBAGENT_DELIVERY_VERIFICATION.json`。技能要求委托长任务，子agent准备和跟踪，主agent独立审查派发门与交付。

永久一次claim登记在旧小说registry并采用独立H3格式，未改旧条目；未适配的旧入口遇到此格式会保守停止，需要显式识别H3原任务终态后再续行，不能删除claim来重新派发。本次没有后续段或自动重试权限。
