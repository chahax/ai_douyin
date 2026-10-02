# Seedream 图片资产优先的导演流程

视频制作顺序固定为：

1. 从已通过剧本和分镜提取角色、服装、表情、场景与固定道具。
2. 使用同一方舟账号的 doubao-seedream-5-0-pro-260628 生成角色多角度设定图。每名主要角色至少包含正面、三分之四、侧面、背面和关键情绪近景。
3. 实际看图审核年龄、脸型、发型、发色、服装、人体、角度间身份一致性；不合格时只重做该角色，未通过图片不能进入后续。
4. 使用 Seedream 生成无人物背景图。背景核对门窗、家具、空间轴线、光源和固定陈设，不得带人、伪文字或提前出现剧情道具。
5. 角色与背景都通过后，按镜头生成构图首帧。首帧再次审核人数、站位、视线、手部、道具数量与归属，并绑定图片哈希。
6. 仅将通过的原生 Seedream 图片作为 Seedance 的首帧或参考图片，执行图生视频。视频继续按逐段抽帧、声画检查和原始尾帧续段规则推进。

Seedance 是视频模型，Seedream 是图片模型。人物母版与背景母版不再由 Flux 或 Animagine 生成。ComfyUI只用于已审图片的排版、裁切、遮罩和局部修补；修改后的图必须重新审核。

资产包入口：

    .venv/Scripts/python.exe scripts/generate_ark_asset_pack.py prepare --manifest MANIFEST --output-dir NEW_OUTPUT
    .venv/Scripts/python.exe scripts/generate_ark_asset_pack.py submit-all --output-dir PREPARED_OUTPUT

每张图片单独保存请求、服务端响应、原图、哈希和审核状态。未知提交结果禁止自动重提；生成成功仍保持 media_review=pending，直至实际看图完成。


## 2026-09-26 表现方式参考与版本审核
参考片只提供构图、景别、前后景活动、表情动作时序的带秒数证据；剧本事件、动机和对白只来自本项目稿。编剧修订后先由助手逐节审查，导演再生成镜头、动作窗口和资产提示词，随后独立上下文交叉复核和助手终审。未知声音项目不能由静帧或ASR代替。
入口 scripts/run_visual_performance_revision.py 按 writer/director/check 分阶段运行，复用原角色模型并累计原任务调用预算；--prepare-only 只生成本地请求。旧制作稿不覆盖。剧本和导演稿未通过不能启动图片；图片未实际审核不能启动视频。
禁止在图片或视频提示词中独立加入新刺激，例如合同故事中的“听见关心”。动作对象、动作完成结果与人物持物逐镜审查；画风变化不能修改角色年龄与身份。声画延后授权只在原绑定序列有效。

## 平台拒绝与未知提交结果
PrivacyInformation 回执只证明服务以该理由拒绝本次输入，不证明真实人物身份、确定误判、其他未点名图片已通过或没有收费。
保存原始错误码、请求哈希和点名索引后暂停该内容提交，使用平台支持的审核/申诉方式处理；不通过删除点名图片、改变外观或换seed探测规避。
网络超时、服务端错误等结果未知时保持 submit_outcome_unknown 和提交锁；不得写 task_created=false 并自动重提。平台接收与渲染成功都不等于视觉或表演通过。

## 文本门槛与当前检查点
新版图片manifest必须绑定 text_acceptance_run，指向本次文本审查目录。prepare与submit均重验TEXT_ACCEPTANCE.json、模型独立审核请求绑定、助手终审和当前剧本/分镜哈希；通过后改稿会使媒体入口失效。校验器在 src/content_factory/performance_revision_gate.py，回归测试 tests/test_performance_revision_gate.py。旧资产包历史记录保持原协议，不补造通过。
当前表现修订检查点见 data/video_generation/blank_cost_20260925/performance_revision_20260926/RUN_STATUS.json；目前独立复审尚未通过，禁止据候选稿直接生成媒体。配置调用上限与账号额度是两回事，不能将本地上限称为账户耗尽。

## 用户取消调用次数上限后的修订
用户要求“没过记录优化啊目前可以取消调用上线”。当前表现修订启用 performance_revision_call_limit_enabled=false，历史累计调用不重置；共享状态 max_calls 保留数值以兼容旧入口，但此修订入口不再用它限次。返修读取当前选定版本，独立审核不混入历史问题清单；使用服务默认思考设置，不强制disabled，实际设置写入回执。
check_v7 已通过165秒18段文本；当前实时阶段以RUN_STATUS.json为准，不沿用此前47次检查点的未通过状态。图片仍逐张实审。失败图片只有显式 review_intent=repair_failed_visual_asset 且绑定该失败审核时可作为修图输入，修后产物保持待审；此许可不能把失败图片当作合格生产参考或视频首帧。opening_frame 为正式资产类型。
