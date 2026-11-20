# 同住所风格与实际材质参考 v5（2026-11-06）

三个房间各自从几何图独立生成，可能得到三种住房档次和质感。v5 增加同住所风格组，并真正向其它房间输入已审核基准房的材质裁剪图。共享的是墙面、地面与木材表面；每房布局、机位和功能性材料仍由本房合同决定，不把完整主卧图片当厨房图像条件。

## 合同与来源

`packet.style_groups` 显式启用本功能；没有该字段的旧 run 保持兼容。每组保存 `id/style_version/definition_sha256/source/source_ids/master_place_id/members/shared_style/required_material_slots/room_materials`。每个成员带 `style_group_id/style_version/home_style_sha256`，后两项须与组定义一致。组摘要覆盖除自身摘要字段外的完整定义。

共享风格由独立住所规划节点提供受控值，房间最终材质仍存 `static_materials`；例如固定稿明确的厨房水泥地优先保留。原小说确证、固定剧本视觉约束与美术设计选择分层，不把设计枚举冒称小说原文事实。

## 单向生产链

```mermaid
flowchart LR
    G[住所风格组与每房材质] --> M[新基准房 front：本房 geometry]
    M --> L[正式房间布局及人数审核]
    L --> C[实际成图：墙/地/木材 ROI]
    C --> S[独立真实材质审核]
    S --> R[style_reference_ready]
    R --> O[其它房 front：本房 geometry 与兼容 ROI PNG]
    O --> T[本房布局审核 与 独立风格审核]
    T --> F[本镜首图及当前风格复核]
```

基准房先通过原房间审核。只有内部 bootstrap 读取器能读取这个 layout-only 阶段；正式资产查询在材质 bundle READY 前仍不授予生产资格。基准房不依赖自己尚未产生的材质图，因此没有循环，也不会反复生成基准房来等待自己。

本轮新规划选择 `children_room/front` 为 master。仅 CPU 预览确认了该机位有足够墙、地和木材投影，最终必须在实际新成图上审核；没有拿旧未通过图片当正式样本。

## 实际像素与审核

`visual_environment_v4._perspective(return_surfaces=True)` 输出深度可见表面 mask，保持原 guide PNG 像素不变。`visual_residence_style_v5` 对 mask 腐蚀留边，再选满足最短边 64 像素的纯面内接矩形；每张裁剪最大 256×256，最多三张。当前 `visible_surface_masks/exposure-v2` 在纯 mask 内同时按真实原图曝光、可用明暗比例、局部对比与面积排序，避免总选几何面积最大但看不清的暗柜板。全暗图会停止。算法只选择坐标，不提亮、重绘或改动原像素。

材质图直接由真实已审核原图裁剪，不由提示词、seed、合成颜色块或原房间全景替代。mask 与曝光评分只负责提出候选区域，不能证明图中确实是木材或纯纹理。独立 `review_style_materials(mode="reference")` 同时看完整基准房作为全局风格上下文，以及实际材质裁剪；全局年代、做工和整体写实感不再仅靠小色块推断。每个 patch 的材质兼容、texture-only 和 identifiable 仍必须从该 patch 的真实像素分别通过，完整房间不能补出看不清的小图证据。全部必需项通过才建立 READY，不因此升级房间布局或小说忠实度。

其它房生成输入为本房 guide、需要时的本房 canonical front，以及与目标材质兼容的裁剪 PNG。木地板样本不会传给水泥地厨房；厨房不会收到整张基准卧室图。完整 master 只属于 VLM 的 `source_context`，不属于 Klein 图像生成输入；两种审核模式都单独绑定这个上下文的实际 SHA。多材质使用冻结 PNG，不扩张原 ImageCrop 单引用合同。生成图另做 `mode="target"` 风格审核，比较可见兼容表面的固有色调、年代和做工、磨损与写实感，正常曝光差异和功能材质差异不等于风格错误。

## 文件与资格

入口仍为 `pipeline.prepare(new_run, packet, config)` 和普通 `tick`；新 run 自动把 `style_reference_root` 绑定到自身 `style_references`。

`style_references/<group>/<输入指纹>/` 保存 `MANIFEST.json`、`patches/{wall,floor,wood}.png`、`REFERENCE_REVIEW.json` 和 `READY.json`。清单绑定当前书、组定义、原固定稿 SHA、基准资产 ID/版本/设计版本/图像 SHA/审核 SHA、布局与相机摘要、guide SHA、裁剪原坐标/原尺寸/PNG SHA、mask 与 renderer 版本。

每次复用独立核对 registry 当前基准版本和审核、原图实际字节、原固定稿及裁剪重算结果；不只信 manifest 自称。组改版、基准更新、原图或裁剪篡改、材质审核绑定变化均会阻止旧资格。成员环境的依赖继续影响首图、SHOT_BINDINGS 与 H3；旧镜头必须重新绑定当前组摘要，不能用旧 staging 直接继续。H3 也只读核对首图的完整当前风格回执。

## 验证边界

新材质模块首轮 18 项与旧环境 49 项联合 **67 项通过**，66.70 秒，`data/qa/residence_style_v5_final.xml`；另补 ROI 细条带选择用例通过，`data/qa/residence_roi_selector.xml`。包括实际临时 HTTP 的三房生成条件、无整房跨场输入、材质兼容过滤、真实 crop 重算、原图/原文/manifest 篡改、master 更新、跨组拒绝、未知结果保留、严格 bool/null 与 bootstrap 无循环。最终统一发布回归由主代理另外冻结统计，不将阶段次数相加。

测试审核回执是明确的协议夹具，不代表真实视觉通过。环境开发代理没有发起 GPU、模型或真实 `/free` 请求；新基准房、真实材质和三房成图由主代理独立实测。旧 run、旧 H3 暂停、视频、账号、服务与发布均未因此改动。

真实 v1 材质审查返回完整已知 needs_review。针对暗柜板及全局判断证据不足，只追加一次通用 v2 修复与复核：沿用已通过的基准房，不重生、不覆盖旧 bundle；新 mask 版本产生独立 bundle 指纹。v2 模块 **24 项通过**，56.59 秒，`data/qa/residence_style_exposure_v2.xml`，包含暗大块与亮小块对照、全暗拒绝、原像素不变、context 独立 SHA 和辨识度硬门。真实原图 CPU 预览位于 `data/qa/residence_roi_exposure_v2_20261106`，旧木材平均亮度约 0.090，新候选约 0.249；此数值不是材质或风格通过证明。后续唯一真实参考复核由主代理执行，未通过就明确保留结果，不无界换 run 重试。
