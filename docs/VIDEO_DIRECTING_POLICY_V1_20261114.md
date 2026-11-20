# 通用视频导演规范 v1

本层把通用构图规范编译到每镜实际正向提示词，并生成对应的视觉核查清单。它不调用模型、不生成媒体、不修改旧任务，也不把结构检查通过当成成片通过。

入口是 `src/content_factory/video_directing_policy_v1.py` 的 `apply(manifest, graph, policy_binding)`。返回新 `manifest`、新 `graph`、`directing_plan`、`rendered_text` 和 `checklist`。原对象保持不变，图中唯一变化为 `condition.inputs.prompt`；manifest 只更新提示词、两个对应哈希，并新增 `directing_policy` 回执。资产槽位、原文、台词、说话人、声音模式、时窗及人物状态保持原值。

策略 JSON 使用模块的 `DEFAULT_POLICY`：schema 为 `video_directing_policy/v1`，只有固定通用规则枚举和静态/逐镜文字预算。它不接受人物名、书名、资产路径或任意故事规则。

## 规范

- 每镜明确主体与取景范围。入镜人物以可辨认的头肩、轮廓或有明确归属的动作细节承接；画外人物的身体整体留在取景范围之外。只剩没有主体的腿、衣袖或躯干，应列为构图缺陷。
- 持续接触可见时，清楚交代双方身份和接触端点。护理对象和目光对象分别承接，不随转头换成另一个身体。
- 单主体中景旁有画外人物或持续接触时，构图收紧为完整可辨的头肩、上身与属于本人的动作手部，避免画外人物的局部身体残留在边缘。机位仍可自由选择。
- 合理的手部、面部和局部特写继续允许，特写须能连接到同一身体的主人。若原模式是人物当面说话，构图同时保留其可辨认发声面部；本层不把台词擅改成旁白。
- 人物身份、衣着、道具持有人与场景布局沿资产及前态承接。交接和转场依原文与明确前态发生。没有结构化前态时保持未知，不从肖像或一段自由文本臆造人物姿态、持物或接触关系。
- 对白、内心声、画外对白和旁白分别保持原声音模式。语言信息通过声音轨呈现，摄影说明用于画面，字幕策略沿原稿。
- 不要求全员每镜同框，也不固定机位。

## 输入与证据边界

严格状态路线读取已绑定的 `actor_state`、`state_plan_binding`、`guide`；接触路线重放 pinned `contact_continuity.plan_binding` 并逐项核对原 resolution。没有 actor_state 的成熟路线，使用已经 source-bound 的 camera/audio，不补造状态。没有结构化接触计划时，plan 明确记录 `unknown_no_structured_contact_plan`。

成熟路线已核定的 `guide_kind=generated_scene` 或 `segment_selection.mode=scene_cut` 会在首镜启用本场起点与布局说明。当前地点可读取 `script_fields.location.place_id`；前场只有自由文本时，前场地点ID保持未知，仍按明确切场标记使用本场起点，不解析文字猜地点。

兼容完整模型图与成熟路线的提示词 pregraph。模块认证原图哈希、实际 positive、提示词哈希与来源绑定；模型节点和物理资产端口仍由所在执行路线认证。逐镜说明插入原时间标题之后，兼容“入镜”“画面人物为”“以中景呈现”等标题。缺少唯一镜头锚点时返回明确错误，不把所有说明堆在结尾。

回执 `manifest.directing_policy` 的 schema 为 `video_directing_policy_application/v1`，记录 policy binding、plan、逐镜文字、核查清单及原图/原提示词哈希。所有视觉检查初始状态均为 `requires_actual_pixel_review`，`model_quality_passed=false`。实际成片仍须检查边界残肢、重复人物、身体归属、道具与空间连续性、字幕及声画对应。

CPU 回归位于 `tests/test_video_directing_policy_v1.py`，覆盖单人成人与旁白、握手、群像、手部特写、成熟路线 pregraph，以及当前单蓝衣镜头边缘仅余女孩腿部的构图机制。CPU 通过不表示新视频已经生成或质量通过。
