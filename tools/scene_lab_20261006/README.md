# 固定场景工具下载与组合实测（2026-10-06）

用户请求：“都下载下来组合试下”。本轮在独立本地目录完成下载、安装、真实 MCP 握手、同一三维场景渲染、两个深度控制图片与一条空场景短视频。没有新增付费云调用、文本模型调用、自动重试或发布。所有产物均为本地方案试验，未替代 S7 正式资产，也未记为创作质量通过。

## 可直接核对的产物

- [原图对照与短视频审片页](REVIEW.html)：切换办公室和走廊机位，查看固定渲染与 VACE 图片的差别；视频由用户播放审核。
- [单一三维场景](geometry/office_corridor_candidate.blend)：所有机位来自同一个场景。
- [平面图](geometry/plan.png)、[办公室朝门口](geometry/office_to_door.png)、[走廊回望办公室](geometry/corridor_to_office.png)、[反向机位](geometry/office_reverse.png)。四张预览各有对应深度 PNG。
- [坐标与机位合同](geometry/SCENE_MANIFEST.json)、[保存场景验收](geometry/GEOMETRY_CHECKS.json)。
- [实际生成与保存回执](comfy/EXECUTION_STATUS.json)、[视频文件完整性](comfy/VIDEO_FILE_INTEGRITY.json)。

## 下载、安装与接入

| 项目 | 实际版本/数量 | 验证 |
| --- | --- | --- |
| Blender 便携版 | 4.5.14 LTS；398,661,046 字节归档 | 官方 SHA256 校验成功；实际渲染并保存 .blend |
| Blender MCP 作者源码与运行包 | 固定提交 34b7bd277fff75a693cde78930b4359478958a01，mcp-for-blender 2.1.8，SDK 1.30.0 | 独立环境；MCP 初始化成功；get_scene_info 读取实际场景 |
| Comfy MCP / CLI | comfy-mcp 0.10.0，comfy-cli 1.22.0，SDK 2.3.0 | 独立环境；MCP 初始化、硬件读取、工作流预检、3次实际本地提交成功 |
| Comfy Skills | comfy、comfy-debug、comfy-director、comfy-relay | 使用官方 skill-installer 安装；源固定到 comfy-cli 提交 805e7de758a297f4888f4a8fcf170f49d124434f；下次技能列表刷新后可见 |
| Wan2.1 / VACE | 两份官方源码；VACE 1.3B fp16，4,309,519,800 字节 | 模型文件按 Hugging Face 固定提交与 SHA256 校验；本机实际推理 |
| 官方工作流 | 6个 VACE 模板、VACE 教程源码、深度控制样例 | 保留来源与文件 SHA256；本次按本机真实节点 Schema 构建 API 图 |

Blender MCP 与 Comfy MCP 的 SDK 主版本不兼容，已隔离在两个 venv。当前通过标准 MCP 客户端脚本连接实测；没有修改全局 Codex MCP 配置。ComfyUI 复用 D:\IT\AI_vido\ComfyUI 的现有运行时和 UMT5/Wan VAE；试验输入、输出、用户目录和模型路径独立，未更新其依赖。Runway Act-Two 与 Seedance 属于云服务方法，已保留研究与官方链接，没有可供本地安装的模型包，本轮未调用。

[下载计划](DOWNLOAD_PLAN.json)、[Blender校验](DOWNLOAD_RECEIPT_blender.json)、[源码及模板](DOWNLOAD_RECEIPT_sources.json)、[模型校验](DOWNLOAD_RECEIPT_weights.json)、[MCP安装记录](MCP_INSTALL_RECEIPT.json)、[技能记录](SKILL_INSTALL_RECEIPT.json)。

## 实际分工与结果

1. Blender维护唯一几何、对象坐标、门洞、光源和相机。固定场景有两张桌、两把椅、一个门扇及办公室—走廊连续地面。重新打开保存文件后，全部对象世界变换与合同一致；四个机位绑定同一个几何哈希。
2. 渲染输出构图参考和统一0–9米范围的深度图。办公室6×5×2.8米、走廊6×2米、门开85°均是本轮候选设计，不冒称原剧本精确尺寸或拍摄状态；屋顶省略用于布局检视。
3. Comfy MCP读取RTX 5070 Ti约16GB显存，校验实际本机节点。预检返回valid=true、0错误、无付费节点。全部3次工作流提交都有独立原始prompt_id，未重复派发。
4. 原始深度和渲染图确实进入 WanVaceToVideo 的 control_video 与 reference_image。两张图片分别以 length=1 独立生成；短视频使用相同办公室深度重复17帧，8fps、512×288、20步。视频没有被抽帧成图片，两张图片不是视频抽帧。
5. 两张图片和一条MP4均成功保存。只对视频做接口回执、文件大小、SHA256和MP4顶层结构完整性核对；未解码观看、未听音、未做ASR或音画审核。

## 已发现的问题与后续选择

- **三维层的空间一致性已可检验，生成层仍有漂移。** 办公室生成图大体保留窗、门、双桌与柜子，但改动门扇和椅子细节。走廊生成图还新增了门外柜子，室内远墙的深色面也与渲染参考不一致。不能把这两张生成图作为同一房间的合格设定资产。
- 若要求严格同一空间，下一步优先确认这个固定布局，再完善 Blender 材质、完整天花和窗外照明，保留其渲染背景用于制作；生成模型可用于局部材质/人物合成，但应明确允许修改的区域。继续让模型整幅重绘不能提供几何保证。
- VACE小模型本轮仅验证兼容与保存链路。当前512×288输出及单帧图片方式不能证明正式画质、多镜一致性或人物表演通过；不自动替换已有视频服务。
- 本机ComfyUI 0.28.0启动提示前端/模板版本偏旧和GLSL节点缺少comfy_angle；本次图未使用这些节点，3次执行均成功，故未全面更新生产依赖。
- 角色身份未定，脸部参考尚未生成。方澄仍待A/B选择；林屿原请求结果/费用未知，原ID及回执保留，不重派。选定身份后每角色补正面、左右45°、侧面细节，继承实际脸型和皮肤特征。

视频状态为 **awaiting_human_review**，人审结果为空；不能据此续接原尾帧或宣称创作质量通过。原S7台词、导演规划与逐镜表演窗口未修改，MiniMax创作/DeepSeek少量全文审查的分工不变。

## 账本与复现

旧S7图片服务调用9次、保存8张、已知115200 reported image tokens；林屿未知项仍为null。本轮单独记2次本地图片作业与1次本地空场景视频作业，云图片与视频调用均为0，文本调用为0。原冻结绑定检查成功，见[只读核对](ORIGINAL_S7_BINDING_CHECK.json)。

试验源码保存在[code](code/)，工作流在[comfy/workflows](comfy/workflows/)。提交入口使用独占SUBMIT_INTENT文件防止重复提交；再次执行已有作业会拒绝，结果未知只查原ID。任何新的试验应另建明确合同和作业ID，不删除意图来复用调用。

官方依据：[Blender渲染通道](https://docs.blender.org/manual/id/4.5/render/layers/passes.html)、[Blender MCP作者仓库](https://github.com/ahujasid/mcp-for-blender)、[Comfy MCP](https://docs.comfy.org/agent-tools/mcp)、[Comfy VACE教程](https://docs.comfy.org/tutorials/video/wan/vace)。

全部作业完成后已核对队列为空，关闭本轮启动的隐藏 Blender 和 Comfy 实例，释放硬件资源。下载文件、隔离环境、工作流和产物均保留；见[停止回执](HELPER_STOP_RECEIPT.json)。没有停止其他任务或修改原云请求。

## 用户核对后的流程顺序更正

本轮约2秒视频在图片尚未获得用户确认时提前生成。助手将“组合试下”解释得过宽；本轮视频仅保留为技术试验记录，不作为正式制作流程推进或任何内容通过的依据。后续仍按固定场景/人物设定→少量图片→用户确认→正式镜头首帧→当前段视频生成→用户人工审核推进。图片确认前不新增视频派发。原视频、回执、未知请求与账本完整保留，不删除或重置。直接视频生成不会天然保证物理一致性。
