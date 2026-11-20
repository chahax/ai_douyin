# 小说视频的空间片场与状态承接 v24

本模块把同一房间的家具、门窗、机位和具名人物状态放进一套坐标，不让每个视角独立重新造房间。它输出可核查的空间资料；不调用图片/视频模型，不授予资产或成片生产资格，不修改旧冻结计划、旧暂停或账号后台。

## 资料与边界

入口为 `scripts/run_spatial_scene_v24.py`，实现在 `src/content_factory/visual_spatial_scene_v24.py`。当前设计根为 `data/video_generation/spatial_minute_experiments_20261107_v1/spatial_r3`。前代 `spatial`、`spatial_r1`、`spatial_r2` 保留。

输入是上一版四段原提示词，逐文件绑定 SHA、逐句保留十处对白。房间长宽高、家具尺寸、人物占位身高是**本轮拍摄设计**，不是小说给出的测量事实，也不是从参考照片完成的真实三维重建。角色身高不冒充原文年龄。蓝、青、橙分别标识苏墨、叶南、叶西决，仅用于占位识别，不代表服装颜色。原 `spatial` 仅俯视原型保留；r1将朝向改为从双方世界坐标计算；r2为第四段换到能看见门的机位，真实渲染又发现成人挡住弟弟；r3将该镜换到房间西侧并补人物代理盒遮挡诊断。本轮不无界增加后继，r3仍有局部问题时保留结果给主代理判断。

本次固定几何包含一床、一桌、一门、两窗；三个人物 ID 和一个袋装面包 ID。人物起止状态记录位置、姿态、眼态、朝向、可见性，面包持有人只能是一名具名人物。第三段唯一一次面包移交由叶西决到苏墨。第四段包含跪下中间状态及经门离开的路径，离场后人物仍有 ID，但不渲染在室内。

站立、坐姿和跪姿朝向为从 +X 逆时针计的 yaw 角；占位头部鼻尖标出正面。卧姿身体跟随床的长轴、面朝天花板。颜色仅编码角色 ID，不表示最终服装。

源文本第二段仅说苏墨醒来、低头看面包，第三段起点说坐在床沿；本设计把第二段结束安排为撑起坐在床沿，明确登记为 staging interpolation，不伪称原稿已写出精确坐起时刻。

## 可检验输出

- `SPATIAL_PLAN.json`：坐标、唯一对象、机位、原文绑定和四段起止状态。相邻段的结束/开始状态必须逐字段相同。
- `VALIDATION.json`：家具数量、边界、碰撞、对白及状态承接检查。
- `DIAGRAMS.json` 与 `diagrams/*.png`：四段前后共八张俯视图及第四段跪下图；紫线显示相机方向和水平视野。
- `CAMERA_PROJECTION.json`：设计头部中心的相机投影、家具及其他人物代理盒的视线遮挡；明确不等于全身轮廓、墙体或真实生成图的完整审核。
- `HANDOFF.json`：人物 ID 到原人物参考 ID 的映射，以及每段起止位置、机位、道具移交，供后续视频管线消费。
- Blender 渲染完成后，`blender_fov_r1/` 保存三张空房同源视角、九张状态图、`room_layout.blend`、实际请求/日志/文件 SHA 及 `CONTACT.jpg`。占位人是简化形体，不能当作正式小说人物图或真实生成视频。占位手臂没有手指抓握rig，袋装面包为独立的持有状态位置标记；后续图片模型必须根据语义完成捧袋与递接，不能照抄悬空方块和球柱手臂。

## 运行

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_scene_v24.py prepare
.venv/Scripts/python.exe -B scripts/run_spatial_scene_v24.py validate
.venv/Scripts/python.exe -B scripts/run_spatial_scene_v24.py render --blender D:/path/to/blender.exe --timeout 1200
```

Blender 使用原生脚本、Cycles CPU、两线程，无 CUDA 或服务启动。共用一个几何场景切换相机，不靠镜像冒充反拍。输出为736×1312。已知文件及请求冻结，重复执行复用已验证回执；输出或来源变更时拒绝，要求新命名空间。

## 开发验证

`tests/test_visual_spatial_scene_v24.py` 最终33项 CPU 测试通过，1.46秒，证据 `data/qa/spatial_scene_v24_20261107_release.xml`。包括真实独立 CLI/PNG 产物和重复执行、原稿变化保护，额外人/床/桌、无据道具移交、边界状态错位、路径端点和中段穿家具、穿墙不经门、世界朝向、相机正反向/遮挡、r2“头在框内但被成人挡住”的负例、非有限坐标及生成的 Blender 脚本语法。

第一轮 pytest 默认C盘临时目录权限失败，保留原错误 XML；切换显式D盘新临时目录后通过。不将旧28/30/31/32项或第一次错误与最终33项累加。真实 Blender 渲染状态另看 `blender_fov_r1/RESULT.json`；该回执不存在时不得称实际三维渲染通过。空间图通过也不能代替 H3 的身份、动作、声音和空间遵守实测。

首轮实看时曾把环境取景裁切误归因为 Blender FOV 接口错误；随后实际 projection matrix 证明原垂直FOV误差仅约0.000004°，该推断已撤回，原说明和撤回证据同时保留在 `spatial_r1/blender/CALIBRATION_REJECTION*.json`。新 `blender_fov_r1` 是显式按传感器高度计算焦距并增加实际FOV检查的版本，不宣称修好了已证实的原FOV错误。

## 本轮真实三维结果

最终 r3 已在官方校验的 Blender 4.5.9 LTS 完成12张736×1312真实 CPU 渲染，原执行 session25579 exit0；三个空房视角、四段前后状态及第四段跪姿共用同一几何。`spatial_r3/blender_fov_r1/RESULT.json` SHA为 `6ddd88d5ef1316f5802028e03849b3fd10894b7fab0de62d7f0f8953fe74dfe1`，CONTACT SHA为 `afecfb6367c3576e34916c7f45fc08abcda8ba581eecd05e8816377c3da64ff5`。所有 PNG、CONTACT、实际metadata和.blend的SHA已独立重核，所有原文本SHA未变。实际相机矩阵的垂直FOV最大误差约0.000004°。

代理实际查看了最终12图CONTACT、第四段起点和跪姿近图：r3门与三个人物头部可见，但成人靠左边缘有裁切，跪姿下半身被前景床挡住。保留这些原型限制，不再追加r4/r5；主代理应以实际图决定如何消费。前3段可辨认卧床→坐起→站立及持物状态。占位体没有眼部表情、衣服纹理或精细手指，不能认为身份、美术和动作终审已过。

另用独立 Blender 命令重新打开真实保存的 `.blend`，核验单床、单桌顶、单门、两个窗Mesh、实际床尺寸、CPU设备、736×1312及保存相机矩阵，通过；再次实际运行同一 CLI 复用原回执且exit0，没有重渲。证据和冻结源码/测试SHA在 `data/qa/spatial_scene_v24_native_20261107/ACCEPTANCE.json`。第一次独立检查把 `window_light` 灯误计为窗户，原脚本和错误保留；v2按 Mesh 类型筛选通过。Blender Python断言错误可能仍退出0，因此不能只用进程exit0当通过，须检查实际回执和契约。

本轮未产生GPU推理或图片/视频模型POST，原旧H3 PAUSE SHA保持 `9d5d0c747ef006a715dafe3ed527b7d4f94414ff7479b2c4155442cfebff377e`。这些是空间层与CPU渲染证据，不是用户要求的一分钟生产视频；视频仍由主流程接入图片人像化和原生H3真实生成。
