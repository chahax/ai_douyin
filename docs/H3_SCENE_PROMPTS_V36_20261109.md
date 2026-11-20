# v36 中文场景表演提示词

入口为 `scripts/prepare_h3_scene_prompts_v36.py`，实现为 `src/content_factory/visual_h3_scene_prompt_v36.py`。只做来源与文本编译，不调用文本模型、视觉模型、ASR 或 OCR，不授予画面或成片通过资格。旧 v33/v34 和旧产物不变。

输入是 `data/qa/h3_prompt_identity_v33_20261108/REAL_CASE_r4/SPEC.json` 四段；输出位于 `data/video_generation/h3_scene_performance_minute_20261109_v2/source_prompts`。`PROMPT_PLAN.json` 绑定四个原文文件、原结构记录摘要、四份实际 prompt 文件及原声句子。协调器应将每份 prompt 文件的全文原样赋给 H3 `condition.inputs.prompt`，不再追加旧包装。

本轮变化：

- 原文从第一个本段时间标记到结束，逐字保留。因此对白、动作、表情及原镜头切换仍按原顺序交织呈现。每段 3/2/2/3 句，共 10 句，保留原说话人、声道与时段。
- 保留来源中的服装识别、声线和当前起点。新增人物看向场景伙伴、面包或房门的自然侧面表演说明，不输出 `visible_parts/face` 等工程枚举，不要求全员正对镜头。
- 实际 prompt 明确写入一条约束：“画面是纯摄影剧情影像，不出现字幕或其他屏幕文字；所有台词仅作为声音播放。”这不是后期去字幕标志，也不承诺模型一定遵守。
- 本机 `GET http://127.0.0.1:8190/object_info/MiniMaxH3ImageToVideo` 实测：required 只有 clip、vae、prompt、width、height、length；optional 仅 first_frame、last_frame，没有 negative_prompt。因此不添加虚构负向字段。原始节点信息及事实记录在 `data/qa/h3_scene_prompt_v36_20261109`。

接口：

```python
compile_segment(entry)  # prompt_text、audio、source_map、纯程序audit
prepare(source_file=SOURCE, output_dir=OUT, node_capability=None)  # 返回PROMPT_PLAN的path/SHA绑定
validate(plan_binding)  # 重核原文、10句、动作位置映射和四份编译文件
```

`audio[].text` 包含原引号，`spoken_text` 为原台词内容，`speaker_id/mode/start/end/quote_index/quote_sha256` 保留结构化声音映射。`source_map` 将原始字符区间及 SHA 映射到新 prompt 的字符区间。审计中的 `ordered_quotes_exact/all_source_actions_copied` 只表示确定性文本对照成立。

全部输出保持 `user_review_pending=true`、`production_approved=false`、`publication=false`、`native_text_absence_guaranteed=false`。没有要求新图通过旧 v33 的全脸审核，也没有伪造视觉审核。

验证：`tests/test_visual_h3_scene_prompt_v36.py` 共 15 项通过，3.48 秒，0 失败/跳过；证据 `data/qa/h3_scene_prompt_v36_20261109.xml`。覆盖真实四段输入输出、10句原话、动作/时序映射、原文或声音字段篡改、输出幂等与损坏、无需图像审核及不得宣称通过。测试没有推理或媒体提交；本轮只有读取节点 schema 的 HTTP GET。
