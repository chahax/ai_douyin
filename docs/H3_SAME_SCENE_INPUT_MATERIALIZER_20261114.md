# 同场输入物化入口

`scripts/materialize_h3_same_scene_inputs.py` 提供纯CPU函数：

```python
materialize(run, shot_id, predecessor_binding, review_binding,
            initial_states_binding, output_dir)
```

三个 binding 参数均为 `{path, sha256}`。CLI 同名 `--predecessor-binding`、`--review-binding`、`--initial-states-binding` 参数读取**保存了 binding 对象的JSON文件**；`--run`、`--shot`、`--out` 指定新run、目标段和目标段内全新输出子目录。

入口读取新run已有系列PLAN、ORIGINALS、SOURCE_CATALOG和当前段模板。只接受本run紧邻前段的实际RESULT；四原件SHA、PLAN/STATE/REQUEST/RESPONSE/HISTORY、实际图SHA与原输出定位均核对。只有已知保存成功、原UUID与图哈希一致的前段才能成为guide。缺失未来RESULT时只返回等待，不写未来初态、不调用离线prepare。旧run结果、非紧邻段、未知结果或被修改的证据均拒绝。

`review_binding` 指向实际同帧guide review，沿用现有 `guide_image`、`predecessor_result`、可见演员、身份映射、世界状态、完成已知与证据字段。它是调用方的实际观察记录；writer不会自行看像素认人。

初态JSON合同为：

```json
{
  "schema": "same_scene_initial_states/v1",
  "predecessor_result": {"path": "...", "sha256": "..."},
  "guide_image": {"path": "...", "sha256": "..."},
  "states": {"character_id": {
    "instance_id": "stable_instance_id",
    "position": "实际观察或已确认承接的位置",
    "posture": "unknown",
    "gaze": "实际观察或已确认承接的视线",
    "held_items": [],
    "body_ownership": {"body": "stable_instance_id"}
  }},
  "observations": {"character_id": {
    "posture": "occluded",
    "evidence": "区分本帧所见、遮挡及来源/已确认前态"
  }}
}
```

演员集合及instance必须完整匹配模板。姿态观测允许 `visible`、`occluded`、`offscreen`；已知坐立姿态必须有本帧可见证据，遮挡与画外保持 `unknown`。writer保留调用方明确提供的持物，不因没看见便主动清空，也不自行从历史补工具；所有持物语义的正确性仍由实际观察及来源分析负责。

三项state basis由程序从实际尾帧、前RESULT和review计算。动作权限与源动作表沿原模板，逐镜断言从本次初态和已授权delta重新计算，不复制历史初态/历史断言。

只有模板明确要求接触计划时才物化contact：只复用已批准的关系/源配置，换为本次真实basis，再与新review中的observed_contacts核对。S03等没有contact模板的段不会被自动补出持续接触。若contact闭包需要改变当前冻结camera/source，返回 `needs_explicit_source_catalog_revision`，由上游新版本与显式catalog采纳处理；writer不修改ORIGINALS、系列源或原模板。

成功后写入全新STATE、GUIDE、INPUT_SPEC、可选CONTACT及证据回执，并实际运行完整 `flow.prepare` 和 `flow.validate`。这仍只是离线输入完成：不会暂存到模型输入目录、调用HTTP/模型/ASR、改变服务或派发任务。导演规范与最终graph审批由已有执行路径消费，离线完成不代表成片质量通过。

测试：`tests/test_h3_same_scene_materializer.py`。所有native媒体均为D目录中的明确合成协议fixture，真实模板/资料仅用于CPU输入编译，不能当成真实模型产出。
