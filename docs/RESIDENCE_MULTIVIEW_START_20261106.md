# 共享住所线路启动与多机位实测（2026-11-06）

用户要求直接启动此路线并说明还需开发的点。本轮补齐已审背景续跑接线，并真实启动本地worker；生成两张后发现共同空间错误及主审核误放行，已安全暂停新试跑，撤回两图资格。没有进入人物首图或视频。

## 已完成的开发

- `visual_environment_continuation_v6.derive/prepare`：新任务显式复用原三张已审front和原READY外观参照；逐项绑定book/source/style/master/front版本/审核/guide/parent/crop。默认无continuation行为不变。
- 新run只增加reverse/side，移除无用人物导入；每机位最多1张、2次已知审核；不重复源参照审核、不复制或改写旧bundle。
- 状态与执行重新只读核原资格，原front或参考变化即停止；新增side登记不使引用过期，不冻结整个资产库总SHA。
- 有真实guide的布局false/null不能被缺guide的两裁图复核升级；非front审核必须绑定本房当前front SHA。

原三张front的主审核原生回答已独立核对，四项均true且没有crop升级；仍可复用。见`data/qa/ENVIRONMENT_PRIOR_FRONT_PRIMARY_AUDIT_V10_20261106.json`。

## 实际执行与结果

源run：`data/visual_asset_pipeline/runs/novel_residence_appearance_20261106_v6`。

新run：`data/visual_asset_pipeline/runs/novel_residence_multiview_20261106_v7`。

既有CLI worker真实启动（PID32128/launch_id residence_multiview_20261106_v7），原先预备6个新机位。实际生成苏墨房reverse与side各1图，均768×1024、原生保存已收存。发现多床后，使用公开pause入口；第二图在暂停写入前已进入审核，在途调用完成后worker正常exit0/paused，其余4机位没有派发。

![原正面、两张新图与空间图对照](D:/IT/ai_douyin/data/qa/residence_multiview_20261106/SU_MO_VIEW_FAILURE_COMPARISON.jpg)

两张新图的灰旧墙/水泥地/棕木/灯光风格接近。但固定布局只有bed_01一张床；新图左前保留原front的床边，另在新guide床位生成完整床，成了两个实例。全幅front与机位guide同时携带空间信息是疑似原因；尚未做仅guide+外观裁图的A/B验证，不能称已证明或已修好。

reverse真实主审核与BLIND均写出two beds，主审核却四项true、issues空，后续style也accepted；这是主审误放行，**不是本轮刚封住的crop升级**。side也在暂停前完成主审并开始目标外观推理，同样combined=accepted。side最后APPEARANCE_CLAIM为1793973984.656，暂停写入1793973994.252，属于在途收尾，没有暂停后新派审核。

主代理直接查看两张原图后，通过`registry.review`按asset/version/input SHA/图SHA CAS追加`root_agent_visual_inspection`、`repair_required/layout=false`事件，撤回两图资格；没有改写Qwen原回答或声称其自行拦截。原AIaccepted状态另存`STATE_AI_BEFORE_VISUAL_WITHDRAWAL.json`，原native与审核事件保留。最新资格为原3front selected、2新图pending、4视图missing，整套ready=false。原视频暂停不动。

## 必须补齐的开发与验收

1. **生成参考的空间隔离**：受控验证生成只使用本机位guide与已审局部外观ROI，全幅front用于审核；如需家具细节应裁单一实例，避免重新引入另一机位完整布局。这是待验证的技术方向，不能只补一句“只有一张床”。
2. **结构化家具实例核对**：目标图先独立提取家具实例数量；与程序`layout.objects`的实体总数上界硬核，部分入镜仍算实例，床单/床架不能算另一张床，未知保留未知。不能用英文证据中的数字或总评true强填通过。正常遮挡可以减少可见数量，但不能凭空增加物理实体。
3. **默认生产入口与排镜接线**：背景方案变化后，需要按新样式重新安排镜头，并将此路线接入新任务默认入口。现有首图/H3绑定与失效门已在代码里，人物资产、组合首图和整段视频仍须实际验收；管理后台本轮未重启加载。

本轮程序测试与实际图片结果分别记录，不将mock/协议通过当作空间语义通过。最终关键联集以本轮QA XML为准，不累加旧678、230、17等计数。

本轮最终37个唯一关键测试全部通过（0失败/跳过/重复，385.94秒），27份源码与7份测试前后SHA一致。XML：`data/qa/visual_environment_shared_views_v10_critical_20261106.xml`，SHA`341bf4c13319a232bd22a51f8b9671ec9ceb3f8bee3c9fbe2e80d80040f2668a`；完整清单：`data/qa/VISUAL_ENVIRONMENT_SHARED_VIEWS_V10_CRITICAL_ACCEPTANCE_20261106.json`。测试后的SHA收集器曾把node selector误当文件路径而退出，使用原BEGIN与同一XML/log补齐after SHA，collector_error保留；没有重跑或把它冒充pytest失败。主代理独立复核当前SHA与37个XML测试ID。

实际调用为2次Klein图像POST、6次Qwen3-VL视觉推理（两图各BLIND/主审/目标外观），0源参照复审。两图AI误放行的原记录均保留，主代理已直接看图撤回资格。程序关键测试通过不等于这两张实图合格。

## 边界与证据

主证据目录`data/qa/residence_multiview_20261106`：BEFORE、DERIVATION、PREPARED_RECEIPT、PAUSE_RECEIPT、ROOT_VISUAL_WITHDRAWAL、FINAL_REQUIREMENTS_AFTER_WITHDRAWAL及FINAL_ACCEPTANCE。

没有重生原front、源参照复审、人物/首图/视频/发布、服务重启、浏览器操作、依赖或模型下载、定时监控。原H3 PAUSE的SHA须与BEFORE一致。本轮新图2，原生ID已知，没有新增未知调用；剩余4图未派发。
