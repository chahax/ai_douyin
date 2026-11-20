# 空间参考材质后继与MoGe近视角 v25（2026-11-08）

## 材质问题的真实后继

主代理在两张真实Klein输出发现叶南的头/手仍保留青色塑料。原空间r3把整个占位体都赋身份标识色，因此不仅存在提示词风险，输入图本身也在强烈表达“青色头部”。本次修复的是渲染资料的材质合同，不再改机位或否认原失败图。

新 `identity_color_clothes_only/v25` 在同一 `spatial_r3` 下生成独立 `blender_skin_proxy_v25`。原 `SPATIAL_PLAN.json`、`HANDOFF.json`、全部人物状态、几何、相机及十句对白字节不变；旧 `blender_fov_r1` 和默认生成脚本保留。AST测试确认所有球/柱/方块调用的几何参数和camera函数不变。新图的实际12个相机矩阵、可见角色列表和面包持有人与原r3逐字段一致。

材质合同位于新REQUEST和实际RENDER_METADATA：

- `material_contract.schema = spatial_skin_material_contract/v25`
- `policy = identity_color_clothes_only/v25`
- 头、鼻尖与裸露手臂使用共享 `human_skin_proxy_v25`，RGB为 `[0.62,0.43,0.31]`、roughness为0.7。
- 身份蓝/青/橙仅留在各角色躯干衣服与裤子；不把身份色当皮肤色。
- `geometry_changes/camera_changes/state_changes = false`。
- `renders[*].actor_material_bindings` 由真实Blender逐Mesh读取材质名和RGB，消费者不能仅信合同文本或把null当通过。
- `RESULT.skin_material_check.skin_materials_verified = true` 必须来自实际材质核验；每名角色至少实际观察到head、arm、torso。空、短、null、NaN RGB均拒绝。

实际12张736×1312 CPU渲染已完成，session66219 exit0。RESULT SHA为 `e69b6fb036326b0ef542aa4c495f608be8025c4d817b459e4993047e782435e6`，CONTACT SHA为 `372bdf0e8dc9e3d9ce0c403a7f5b15301cc0fe31656fee2447f893a7072671d3`。代理实际查看全CONTACT和S01_start，头/臂已为肤色、衣裤仍区分。重复CLI复用已有回执，没有重渲。

本轮最终42唯一CPU测试通过（0失败0跳过，0.98秒），不是与原33/38项累加。证据 `data/qa/spatial_skin_v25_20261108_release.xml`，实际验收与源码SHA在 `data/qa/spatial_skin_v25_native_20261108/ACCEPTANCE.json`。新材质图仍是粗几何占位，不存在精细脸、头发或手指rig；手臂末端使用肤色不等于完成真人手部制作。不能据此宣称Klein后继已成功，须由主代理重新跑真实图片节点判断。

运行方式：

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_scene_v24.py render --run data/video_generation/spatial_minute_experiments_20261107_v1/spatial_r3 --render-tag blender_skin_proxy_v25 --material-policy identity_color_clothes_only/v25 --blender D:/IT/ai_douyin/data/tools/spatial_20261107/blender/blender-4.5.9-windows-x64/blender.exe
```

## 独立MoGe近视角演示

`scripts/render_moge_near_views_v25.py` 只读取此前实际MoGe导出的 `moge/mesh.glb`、`CAMERA.json`、`source.png` 和推理回执，不重新调用模型。源GLB按其已声明的OpenCV→GLB轴变换导入Blender，使用原相机内参与贴图，Cycles CPU两线程、单采样、发光贴图避免二次照明改变原图。输出为原视角与左右各0.03估计单位的平移视角，共三张576×768。三维轴不与手工舞台混合。

实际唯一执行session5807 exit0。`moge/near_views/RESULT.json` SHA为 `b902fb9cfa1a17d8f614af75fbcaf36cb9490c04c4990ab10201f8d01466c86f`；CONTACT SHA为 `36abb2bba29db5c0f486422cdcac5a5bf9b9e425b3863f8b5f29e24d4753a01f`。原图有效像素重投影MAE约0.50/255，原视角覆盖98.30%，左右视角覆盖97.03%/97.20%。未覆盖孔洞透明保存、对照图用品红显示，未做修补或臆造背面。

代理实际看过CONTACT与left原图：床、桌、窗的近视角透视保持一致，床/桌边缘和部分灯具边缘有孔洞。它验证了下载模型实际几何的近视角能力，不等于已得到完整房间或可用反拍。0.03是模型估计场景单位，只有尺度估计准确时才近似3cm，未做物理测量。输出没有自动加入B视频参考。

这两项后继均为CPU制作与检查，额外GPU推理/模型POST为0，未修改H3服务、旧暂停、账号或发布状态。
