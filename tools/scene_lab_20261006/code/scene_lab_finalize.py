from pathlib import Path
import json,struct,hashlib,datetime,shutil,subprocess,html
root=Path('tools/scene_lab_20261006').resolve();states=json.loads((root/'comfy/EXECUTION_STATUS.json').read_text())
assert len(states)==3 and all(x.get('interface_success') for x in states)
video=Path(states[2]['outputs_saved'][0]['path']);data=video.read_bytes();pos=0;atoms=[]
while pos<len(data):
 if len(data)-pos<8:raise RuntimeError('truncated mp4 atom header')
 size,typ=struct.unpack('>I4s',data[pos:pos+8]);head=8
 if size==1:
  size=struct.unpack('>Q',data[pos+8:pos+16])[0];head=16
 if size==0:size=len(data)-pos
 if size<head or pos+size>len(data):raise RuntimeError('truncated mp4 atom')
 atoms.append({'type':typ.decode('ascii'),'bytes':size});pos+=size
assert {'ftyp','moov','mdat'}.issubset({x['type'] for x in atoms})
(root/'comfy/VIDEO_FILE_INTEGRITY.json').write_text(json.dumps({'path':str(video),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'complete_top_level_atoms':True,'atoms':atoms,'decoded_frames':0,'audio_listened':False,'asr_calls':0,'audiovisual_review_model_calls':0,'content_status':'awaiting_human_review'},indent=2),encoding='utf-8')
# Preserve reproducible scripts within the trial alongside receipts.
code=root/'code';code.mkdir(exist_ok=True)
for name in ['scene_lab_download.py','scene_lab_install.py','scene_lab_build_geometry.py','scene_lab_launch_comfy.py','scene_lab_blender_mcp_ui.py','scene_lab_mcp_probe.py','scene_lab_prepare_workflows.py','scene_lab_submit_mcp.py','scene_lab_status.py']:
 shutil.copy2(Path('.codex_staging')/name,code/name)
(root/'.gitignore').write_text('blender/\ndownloads/\nenvs/\nmodels/\nsources/\ncomfy/user/\ncomfy/logs/\n',encoding='utf-8')
# Review page only presents original artifacts; no video autoplay or frame extraction.
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>办公室—走廊 · 固定场景组合试验</title><style>body{font-family:system-ui,sans-serif;background:#f5f4ef;color:#252b31;margin:0}main{max-width:1180px;margin:auto;padding:28px}h1{font-size:28px}p{line-height:1.75}.badge{background:#e6ddd0;padding:8px 14px;border-radius:8px;display:inline-block}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}figure{margin:0;background:white;border-radius:12px;overflow:hidden}figcaption{padding:12px 16px;font-weight:600}img,video{width:100%;display:block}section{margin:28px 0}button{padding:10px 18px;margin:4px;background:#344943;color:white;border:0;border-radius:6px;cursor:pointer}a{color:#345e80}small{color:#5c646b} @media(max-width:700px){.grid{grid-template-columns:1fr}}</style><main><h1>固定三维场景 → 深度图 → 本地 VACE</h1><div class="badge">本地试验完成 · 布局与生成内容待用户确认</div><p>四个机位来自同一份 Blender 场景。下面可切换两个透视机位，对照原始三维渲染和独立生成的图片。生成器仍改变了门、椅子和柜子细节；接口成功没有替代空间和审美验收。</p><button onclick="setView('office')">办公室朝门口</button><button onclick="setView('corridor')">走廊回望办公室</button><section class="grid"><figure><img id="base" src="geometry/office_to_door.png"><figcaption>固定几何渲染 · 原始布局</figcaption></figure><figure><img id="gen" src="comfy/output/scene_lab/depth_office_to_door_00001_.png"><figcaption>深度＋渲染参考 → VACE 生成</figcaption></figure></section><section><h2>同一空间的平面关系</h2><img src="geometry/plan.png"><p>办公室 6×5 米，走廊 6×2 米，门洞 0.95 米。尺寸是本轮设计候选，尚未获得用户确认。门打开85°仅用于查看连通性，不替代剧本的门状态。</p><a href="geometry/office_corridor_candidate.blend">下载同一 Blender 场景</a> · <a href="geometry/SCENE_MANIFEST.json">坐标、机位和深度合同</a></section><section><h2>约2秒本地空场景视频试验</h2><video controls preload="none" src="comfy/output/scene_lab/depth_office_to_door_00002_.mp4"></video><p>512×288，17帧，8fps；使用固定机位的深度条件。仅核对接口成功和文件完整保存，状态 awaiting_human_review。助手未抽帧、听看、ASR或调用音画审核模型。本片人物表演尚未接入此试验。</p></section><section><h2>角色与生产流程仍待处理</h2><p>方澄身份候选尚未选定；林屿旧请求仍结果/计费未知，未重派。选定身份后再补脸部正面、左右45°和侧面细节参考。S7 剧本、导演安排、对白和实际表演窗口没有修改；原账本完整保留。</p><a href="README.md">工具版本、实际验证与未解决问题</a></section></main><script>function setView(v){const office=v==='office';document.getElementById('base').src='geometry/'+(office?'office_to_door':'corridor_to_office')+'.png';document.getElementById('gen').src='comfy/output/scene_lab/depth_'+(office?'office_to_door':'corridor_to_office')+'_00001_.png';}</script></html>'''
(root/'REVIEW.html').write_text(page,encoding='utf-8')
report='''# 固定场景工具下载与组合实测（2026-10-06）

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

Blender MCP 与 Comfy MCP 的 SDK 主版本不兼容，已隔离在两个 venv。当前通过标准 MCP 客户端脚本连接实测；没有修改全局 Codex MCP 配置。ComfyUI 复用 D:\\IT\\AI_vido\\ComfyUI 的现有运行时和 UMT5/Wan VAE；试验输入、输出、用户目录和模型路径独立，未更新其依赖。Runway Act-Two 与 Seedance 属于云服务方法，已保留研究与官方链接，没有可供本地安装的模型包，本轮未调用。

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
'''
(root/'README.md').write_text(report,encoding='utf-8')
Path('docs/SCENE_GEOMETRY_LOCAL_COMBINED_TRIAL_20261006.md').write_text('''# 固定三维场景工具下载与本地组合实测（2026-10-06）

承接用户“都下载下来组合试下”。本轮下载与安装已完成，实际完成同一Blender场景的4个机位与深度图、两个本地VACE图片作业及一个本地空场景短视频。没有付费云调用、自动重试、发布或S7文本改动。

详细记录、版本、不可变回执和问题见[本地组合试验](../tools/scene_lab_20261006/README.md)，直接对照见[原始渲染、生成图片及视频审片页](../tools/scene_lab_20261006/REVIEW.html)。

三维对象合同检查通过；实际生成图片仍改动家具与门细节，走廊图新增柜子。因此尚未得到可采用的同一空间生成资产。短视频只核对接口和文件完整性，状态awaiting_human_review；未抽帧、听看、ASR或音画模型审核。人物身份、面部细节、正式首帧与人物表演均未完成，创作质量没有通过。

建议下一步确认固定布局、完善真实渲染背景，再安排有明确区域边界的人物或材质合成。原S7账本、未知林屿请求和冻结记录保留。
''',encoding='utf-8')
now=datetime.datetime.now(datetime.timezone.utc).isoformat();progress=Path('data/task_progress_monitor/creative_progress_state.json');old=json.loads(progress.read_text(encoding='utf-8-sig'))
checkpoint=Path('data/task_progress_monitor/checkpoints');checkpoint.mkdir(exist_ok=True)
cp=checkpoint/'scene_lab_before_completion_20261006.json'
if not cp.exists():cp.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
old.update({'updated_at_utc':now,'stage':'local_geometry_and_vace_probe_saved_awaiting_human_layout_and_video_review','next_step':'确认固定三维布局，完善渲染背景；选定人物后再补面部参考','geometry_local_trial':{'root':str(root),'review_page':str(root/'REVIEW.html'),'download_complete':True,'blender_version':'4.5.14','mcp_handshakes_verified':2,'skills_installed':4,'rendered_views':4,'depth_maps':4,'local_image_jobs':2,'local_video_jobs':1,'paid_cloud_calls':0,'new_text_calls':0,'auto_retries':0,'same_space_generated_assets_accepted':False,'human_video_status':'awaiting_human_review','original_linyu_outcome_unknown_preserved':True,'formal_production_model_changed':False},'geometry_tool_installations':{'blender_portable':1,'isolated_mcp_environments':2,'skills':4,'new_model_weights':1}})
progress.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'all_jobs_saved':True,'video_bytes':len(data),'report':str(root/'README.md'),'review':str(root/'REVIEW.html'),'paid_cloud_calls':0,'auto_retries':0}))
