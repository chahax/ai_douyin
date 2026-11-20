# v37 多角度身份与真实末帧承接提示词

新模块 `src/content_factory/visual_h3_scene_prompt_v37.py`，入口 `scripts/prepare_h3_scene_prompts_v37.py`；旧 v36 源码及四个冻结 prompt 未改。

实际文本计划：`data/video_generation/h3_multiview_continuity_minute_20261109_v3/source_prompts/PROMPT_PLAN.json`。schema 为 `h3_multiview_continuity_prompts/v37`；`segments[].id/source/prompt/audio` 接口沿用 v36。协调器将 `prompt` 文件字节直接交给单首图 I2V 的 `condition.inputs.prompt`，不叠加旧固定机位或工程包装。

本轮规范：

- 从原 `REAL_CASE_r4/SPEC.json` 保留四段、10句原话及各自说话人、声音模式和时间。原定时正文、动作、神情及摄影文字整体逐字保留，仍在同段内交织。
- 明确源三名映射人物。多角度身份参考对应同一演员的脸和衣着，实际站位、朝向、入画与离场按源动作变化，不把参考站姿等同于表演姿态。
- S01建立源人物造型映射；S02—04继续输入画面中的当前身份、衣服、持物、空间和动作，不再重复三条完整的肖像介绍。
- 开场直接进入动作或声音，睁眼交流时看向场景伙伴、面包或行进方向，保留自然侧面、三分之二侧面以及原镜头切换。
- 保留一句实际 prompt 文字约束：纯摄影影像、无字幕或其他屏幕文字、台词仅声轨。不发送不存在的原生 negative_prompt 字段，也不保证模型一定不生成字幕。

`continuity_input_requirement` 是协调器的输入要求，不是图像审核结论：S02—04必须使用本轮前段真实 video.last 像素作为 Klein 最小身份编辑输入，编辑后保存的实际图才可成为本段 H3 first；只登记 last 的来源而不把像素送入编辑不满足要求。每段都记录 `predecessor_segment`。上游多角度图用于编辑与身份保持，并非声称 H3 本次直接消费7/8张图。

接口：

```python
compile_segment(entry)
prepare(source_file=SOURCE, output_dir=OUT, node_capability=None)
validate(prompt_plan_binding)
```

本模块只验证来源字节、结构、原10句、时间与字符位置映射；没有 VLM、ASR、OCR、抽帧、新图查看或语义审核。所有产物保持 `user_review_pending=true`、`semantic_review_performed=false`、`production_approved=false/publication=false`。实际编辑图的原生来源与 first_frame 接线由协调器核实，成片由用户审核。

CPU最终回归：原 v36 的15项与新 v37 的14项，共29个唯一测试通过，3.97秒，0失败/跳过；证据 `data/qa/h3_scene_prompt_v37_20261109.xml`。本轮0服务访问、0模型调用、0媒体POST，复用了先前只读节点能力证据。
