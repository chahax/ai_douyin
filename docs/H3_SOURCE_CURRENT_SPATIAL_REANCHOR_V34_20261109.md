# v33生产测试的当前状态空间资料 v34（2026-11-09）

本轮为用户“生产测试一下重新生成”准备全新空间stage，不把旧B画面或旧坏尾帧冒充新的A房间依据。新根 `data/video_generation/h3_continuity_full_minute_20261109_v1`，最终空间资料在 `spatial_r2`。本模块仅CPU准备与Blender渲染，未调用图片/视频模型、未修改服务或旧暂停，不代主代理写任何true身份/房间/当前状态审核。

## 源与房间

已读取AGENTS顶部、v33说明及真实 `REAL_CASE_r4/SPEC.json`，实际查看 canonical房间front与side。front为灰褐墙、旧水泥地、木床、小木桌、两个窗、方罩顶灯；side的圆罩与床品小差异记录，统一以front方罩为本次设计主依据。照片未露出的门口和尺寸仍是显式舞台设计，不声称完成了照片的完整几何恢复。无新书柜、植物、椅子或多床。

`visual_spatial_reanchor_v34.plan_from_spec` 将四段真实源文件SHA、全部十句对白、各自 `source_state_span_ids` 和原span原文绑定到新plan，不使用此前B的“提前坐起”作为当前起点。四起点为：

|段|成人|弟弟与面包|
|---|---|---|
|S01|卧床闭眼，完整头颈肩躯干四肢关系|双手持袋，哥哥在身旁|
|S02|仍卧床闭眼|仍由弟弟持袋|
|S03|清醒仍在床上，尚未接袋|仍由弟弟举袋|
|S04|站立，袋在成人胸前并错开孩子头|弟弟空手，哥哥护在身旁|

`SOURCE_CURRENT_STATE_DESIGN.json` 绑定源r4与各起点，`production_approved=false`。前三段的摄影侧读脸与有限头部轻转是身份输入可读性的设计，原文后续看哥哥、起身、递接等动作仍留实际视频执行，不在首图提前演出。

## 已实际重渲的修改

- r0补全成人卧姿头颈肩与肢体连接，加入肤色头手、简单黑发与眼态、源方罩灯和灰褐墙地；root实看发现成人仍主要仰天鼻尖，S04袋受孩子头遮挡。
- r1在室内顶板以下提高床尾侧相机，卧姿头部朝摄影侧轻转不超过25°，孩子头部微仰不超过35°，闭/睁眼在实际脸表面可见；袋提到成人左胸。实际图的父脸和袋改善，但哥哥被裁到右边界。
- r2新增通用 `heads_fit/fit_camera`，按实际具名头中心及±0.18m保守头盒求视轴和最小整数垂直FOV，保留8%边界余量；不移动人物、编新状态逃避alias。S01—03选出89°垂直FOV，S04原62°已满足，不再改变。root实际看r2三张起点：3头入画、闭/睁眼可区分、成人胸前袋可见。近前景顶灯偏大作为minor摄影限制保留，不再增加机位后继。

新 `stage_policy=canonical_room_body/v34` 显式接到既有renderer，旧默认v24/v25脚本字节保留。新 `prepare_plan` 消费显式新设计，旧 `prepare` 仍沿原行为。四段机位和新分镜不是统一固定相机要求；实际H3使用经审核的Klein首图，按v33镜头设计变化。

## 交接文件

- `spatial_r2/SPATIAL_PLAN.json` SHA `56bb582897cc1a3be1b8eeb31d7a3f7f1ca766135c338e4ba3a55edd782f0696`
- `spatial_r2/HANDOFF.json` SHA `7a0d3de609f3822452af896874594849449acd63d139f22eab2be946798cf755`
- `spatial_r2/blender_canonical_v34/RESULT.json` SHA `bc73a71b0ef7d4128a19ba4ea61cfa94cf1488874fec7dd5e539ae5bd3d307f1`
- CONTACT SHA `d2473c8217c365daec862a390bcf01a3312ddd4f857c7bb08a9cfaf1139e4567`

实际Blender Cycles CPU两线程，736×1312，共12张（3空房、四段前后、一个跪姿），原进程27309 exit0。PNG、CONTACT、实际metadata及.blend SHA已独立重核；全部源文件SHA与十句原对白保持。空间人仍是占位体，非真实身份或照片式环境已验收。

推荐canonical stage_items为 `S01:S01_start, S02:S01_start, S03:S03_start, S04:S04_start`。S01/S02起点数据与实际相机矩阵均相同，不为逃避producer alias改状态或随意换角。复用canonical stage不代表复用Klein或视频原生结果；四段仍应独立生成。实际映射见 `STAGE_ITEMS_RECOMMENDATION.json`。

## 验证与冻结

最终53唯一CPU测试通过，0失败/0跳过，1.30秒；包含旧空间/材质合同、新r4源状态和十句引用、旧脚本字节兼容、所有头盒8%余量以及r1裁头负例。证据 `data/qa/spatial_reanchor_v34_20261109/release_final.xml`，不与旧51项或别轮172项累加。

`ACCEPTANCE.json` 和 `r2_frozen_snapshot` 存实际plan、render、script、metadata、source-design和映射副本/SHA。主代理已把最终r2绑定到本轮MINUTE_SPEC；后续只可增加诊断证据或新明确后继，不覆写本轮r2。
