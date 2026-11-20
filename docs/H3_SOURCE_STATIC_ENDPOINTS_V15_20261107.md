# H3 显式同图首尾约束（2026-11-07）

F1 高分辨率原生视频虽技术成功、对白 ASR 正确，画面仍转向并显现本应画外的孩子。原结果保持技术成功和画面拒绝，不覆盖原图、graph、PLAN 或原生 ID。新代码提供独立 opt-in 小样入口，不自动恢复旧任务。

## 原生能力与范围

本机 `D:/IT/AI_vido/ComfyUI/comfy_extras/nodes_minimax_h3.py` 的 `MiniMaxH3ImageToVideo` 已接受 first_frame/last_frame；当前 fl2va 权重可用，不下载模型或改服务。[ComfyUI 官方节点说明](https://raw.githubusercontent.com/Comfy-Org/docs/main/tutorials/video/minimax/minimax-h3-native.mdx)及[MiniMax 官方提示指南](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md)描述了首尾条件和对应音画结构。

旧默认只接 first_frame。新策略仅在当前单镜 ready、逐源动作证据与显式起止姿态授权全部核验后，将同一 `ref_scene` 图像槽同时接 first_frame 和 last_frame。不新增 LoadImage，不循环视频，不拼静态帧；整个 277 帧/24fps 仍须由原生 H3 实际生成。首尾条件不会证明中间画面正确，成片继续要求视觉审核。

原生 first_frame 使用拉伸、last_frame 使用保纵横比裁切；保留既有 1% 纵横比门，新端点策略要求尺寸为 32 倍数。288×512 为独立低分辨率验证，正式仍可用 736×1312，不改原剧本帧数和总时长。

## 配置

```python
config.update(
    native_prompt_contract='official_multimodal/v15',
    native_prompt_plan={'path': native_plan_path, 'sha256': native_plan_sha},
    keyframe_policy='source_static_first_last',
    source_endpoint_certificate={'path': certificate_path, 'sha256': certificate_sha},
)
```

官方 native prompt 由独立 `visual_h3_native_prompt_v15.load_for/compile_for` 编译；端点策略只选择其 first/first_last 锚点模式，不修改原 source shot、台词或声线演出。

## 证书

`visual_h3_endpoints_v15.prepare_certificate(asset_run, new_output, shot_id, source_action_evidence=..., authorization=...)` 仅写新证书，拒绝写进原 asset_run。动作记录必须包含精确 id/start/end/text/sha256，逐字匹配当前源文件。授权包含 actor、非空 statement、当前 shot_id/binding_sha256 和以下严格布尔确认：same_start_end_pose、same_start_end_camera、same_start_end_location、full_native_video_required。

证书精确绑定 book/source、原 source shot 摘要、已审首图、binding、asset PLAN、H3_INPUT_READY 与原文动作引用。程序验证来源真实性；“此镜起止可以同姿态”明确标为 operator decision，不假称模型或程序自动推断。证书只允许当前一个单镜 scope，不能把它套到别的镜头、起身/离场动作或整批任务。

本轮 root 仅授权 F0001。实际证书为 `data/qa/h3_endpoints_v15_20261107/F0001_STATIC_ENDPOINT_CERTIFICATE.json`，源入场状态 901:955 和画外段 957:993 逐字核验，绑定 source shot `51cb28bb...`、首图 `3e356866...`。

## 持久验证和收存

新 prepare/派发持续重核当前源、ready、已审图、证书及 native prompt 来源；冻结 graph 必须与声明的 first-only 或 first+last policy 一致。RESULT 如实保留 `source_same_frame_conditioning`、证书及 native prompt 绑定，同时仍为 `media_review_required`，不会自动提升画面资格。

已提交原生任务的原 ID 收存仍按冻结内部图和元数据验证；即使后来外部源/证书撤销，也保留按原 ID 收存能力并记录 source error，不重派未知 POST。原 native int→FLOAT 两处规范化证明及 source_direction 路线保持。

## 验证结果

最终受影响三文件联集 97 项通过，0 失败/跳过：`data/qa/visual_h3_endpoints_v15_affected_20261107.xml`。包含默认 first-only、同槽端点、无显式授权拒绝、证书/source/frame 篡改、277 帧低分辨率配置、外部撤销后原 ID 收存，以及原生 float cast 全部回归。临时 HTTP 视频为协议夹具，不是 H3 视觉验收。

实际已审 F1、真实 MiniMax v15 motion plan 和证书的只读整合预览另存 `data/qa/h3_endpoints_v15_20261107/REAL_INPUT_AUDIT.json` 及 `PROBE_WORKFLOW_PREVIEW.json`：288×512/277f，同首尾槽，无生产 prepare、无 POST。此子代理没有模型/GPU 调用；真正小样由主代理新 namespace 执行。
