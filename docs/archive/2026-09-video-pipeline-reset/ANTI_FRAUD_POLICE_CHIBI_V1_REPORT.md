# 冒充公检法诈骗短片：双工作流制作报告

更新时间：2026-07-27  
项目目录：`data/qa/anti_fraud_police_chibi_v1`  
生成画幅：704×1248，9:16，25fps；交付画幅：1080×1920，30fps  
目标时长：约 30–40 秒

## 1. 成片定位

- 内容：冒充公检法诈骗警示。
- 叙事：现实主义情绪与信息结构。
- 视觉：高级 3D 软萌布偶 / Q 版玩偶定格电影质感。
- 情绪：平静 → 疑惑 → 恐惧 → 犹豫 → 醒悟 → 庆幸。
- 核心标语：真警察不会通过电话办案，更不会让你转账。

## 2. 固定人物档案

### 李婷

- 年龄与身份：28 岁，中国女性白领。
- 脸型与五官：鹅蛋脸，深棕色杏仁眼，淡妆，成年职业女性面貌。
- 发型：黑色直发，固定为整齐低马尾。
- 服装：浅蓝色衬衫、深炭灰色修身西装外套、可见的细银项链。
- 材质与比例：细密植绒布料、可见纤维和轻微缝线，大头但保持成年人体比例。
- 表演限制：情绪逐级变化但不夸张；禁止儿童化、换脸、换发型、换衣、项链消失。
- 唯一身份锚点：`old/keyframes/liting_anchor_v2.png`。

### 陈警官

- 年龄与身份：35 岁，中国男性派出所民警。
- 外貌：端正国字脸，短黑发，眼神坚定。
- 服装：藏蓝色执勤服，不生成可读警号。
- 气质：沉稳、专业、动作简洁。

## 3. 八镜头分镜与 Motion Identity

| 镜头 | 景别 / 镜头 | Hero Motion（起始 → 路径 → 结束） | 时长 |
|---|---|---|---:|
| 01 | 中景；固定 | 低头看电脑 → 手机震动后伸右手拿起并移到右耳 → 微皱眉接听；慢速、小幅 | 4s |
| 02 | 面部近景；极慢推近 | 疑惑接听 → 眼神收紧、轻咬下唇、手指逐渐抓紧手机 → 保持克制的紧张；极慢、轻微 | 4s |
| 03 | 手部微距；固定 | 拇指远离屏幕下方 → 缓慢靠近并在屏幕上方停顿、轻颤一次 → 不触屏并缩回；极慢、精确 | 3s |
| 04 | 中全景；固定 | 站在书桌旁、手机贴左耳 → 向窗边自然走两小步并抬右手揉太阳穴 → 双脚稳定停住、呼吸稍急；正常速度、中幅 | 5s |
| 05 | 越肩近景；固定 | 食指悬在手机上方 → 缓慢下降到确认区上方并轻颤 → 停在接触前、不点击；极慢、极小幅 | 5s |
| 06 | 中近景；固定 | 盯着转账页 → 新来电出现后整个人短暂停住、食指撤离 → 把手机转正准备接听；慢速、小幅 | 4s |
| 07 | 双人中景 / 视频通话分屏；固定 | 警官面向镜头 → 抬一只手做停止手势并坚定说明，李婷肩膀放松、手机缓慢降至胸前 → 两人稳定停住；正常速度、中小幅 | 5s |
| 08 | 中景；固定 | 手机已挂断、双手短暂捂脸 → 长舒气并缓慢放下双手、坐直 → 平静看向镜头；慢速、小幅 | 5s |

## 4. 两套工作流

### 旧工作流：无身份适配器基线

```text
Flux.1 Schnell FP8
→ CLIP Text Encode
→ KSampler（4 steps / CFG 1 / Euler / Simple）
→ VAE Decode
→ 每镜头独立关键帧
→ LTX-2.3 I2V（8 steps / 65或97帧 / 25fps）
```

用途：最低依赖、快速验证剧本与镜头。  
已知限制：不同镜头存在脸型漂移；双人和界面镜头可能出现重复人物；不能稳定生成可读中文界面。

### 新工作流：人物身份增强

```text
李婷人物母版
→ OpenAI CLIP ViT-L/14
→ XLabs Flux IP-Adapter V2
→ Flux.1 Schnell FP8 关键帧
→ LTX-2.3 I2V
```

辅助路线：

- 人体动作：DWPose / OpenPose 预处理。
- SDXL 姿态控制：Animagine XL 3.1 + xinsir SDXL OpenPose。
- Flux ControlNet Union：已安装为实验备选，需单独验证与本机底模、节点的兼容性。
- 遮罩与合成：SAM2。
- 面部微动：LivePortrait。

注意：XLabs Flux IP-Adapter 和 InstantX Flux ControlNet Union 面向 Flux.1-dev。用于 Flux Schnell 属于本机实验组合，需要以实际输出为准；不能仅依据结构兼容就推定许可或画质兼容。

## 5. 关键参数

### 关键帧

| 参数 | 值 |
|---|---|
| 模型 | `flux1-schnell-fp8.safetensors` |
| 分辨率 | 704×1248 |
| 采样 | Euler + Simple |
| Steps / CFG | 4 / 1.0 |
| 人物母版种子 | 527002 |
| 镜头基础种子 | 527101–527108 |
| 新工作流种子偏移 | +2000 |
| IP-Adapter 强度 | 0.35–0.78，按是否露脸调整 |

### 视频

| 参数 | 值 |
|---|---|
| 模型 | LTX-2.3 22B distilled FP8 scaled |
| 分辨率 | 704×1248 |
| 帧率 | 25fps |
| 帧数 | 3秒镜头 65 帧；其余镜头 97 帧 |
| Steps / CFG | 8 / 1.0 |
| 首帧约束 strength | 0.94 |
| 运镜 | 固定为主，禁止自动大幅推拉摇移 |

## 6. 确定性后期

AI 不负责生成可读 UI 文字。以下元素统一在合成阶段叠加：

- 镜头 03：`境外来电 / 00 开头号码`。
- 镜头 05：`资金核查 / 确认转账`。
- 镜头 06：`110 来电`。
- 镜头 08：`真警察不会通过电话办案，更不会让你转账！`。
- 全片中文字幕、统一 TTS、电话提示音由 FFmpeg / 故事视频合成器完成。

## 7. 已安装新组件

| 组件 | 本地路径 | 状态 |
|---|---|---|
| x-flux-comfyui | `D:\IT\AI_vido\ComfyUI\custom_nodes\x-flux-comfyui` | 已加载，相关节点可调用 |
| Flux IP-Adapter V2 | `D:\IT\AI_vido\ComfyUI\models\xlabs\ipadapters\ip_adapter.safetensors` | 已实测生成 8 张增强版关键帧 |
| OpenAI CLIP ViT-L/14 | `D:\IT\AI_vido\ComfyUI\models\clip_vision\openai_clip_vit_l14\model.safetensors` | 已由 IP-Adapter 工作流实测 |
| InstantX Flux Union | `D:\IT\AI_vido\ComfyUI\models\controlnet\InstantX_FLUX1_dev_Controlnet_Union\diffusion_pytorch_model.safetensors` | 实验备选 |
| xinsir SDXL OpenPose | `D:\IT\AI_vido\ComfyUI\models\controlnet\xinsir_sdxl_openpose\diffusion_pytorch_model.safetensors` | 动作控制备选 |

Downloads 中原始文件暂不删除，作为离线备份。  
旧工作流基线已保存于 Git 分支 `codex/hospital-workflow-v4-snapshot`，基线提交 `32b3dad`。

## 8. 可复现文件

- 剧本、人物档案、提示词、种子：`data/qa/anti_fraud_police_chibi_v1/project.json`
- 旧版关键帧 API：`data/qa/anti_fraud_police_chibi_v1/old/workflows`
- 旧版视频 API：`data/qa/anti_fraud_police_chibi_v1/old/video/workflows`
- 新版关键帧 API：`data/qa/anti_fraud_police_chibi_v1/new/workflows`
- 新版视频 API：`data/qa/anti_fraud_police_chibi_v1/new/video/workflows`
- 旧版配音合成清单：`data/qa/anti_fraud_police_chibi_v1/old/story_video.json`
- 新版配音合成清单：`data/qa/anti_fraud_police_chibi_v1/new/story_video.json`
- Flux 批量关键帧脚本：`scripts/comfy_image_batch.py`
- Flux IP-Adapter 批量关键帧脚本：`scripts/comfy_flux_ipadapter_batch.py`
- LTX 批量视频脚本：`scripts/comfy_ltx_antifraud_batch.py`
- 字幕与确定性界面脚本：`scripts/burn_antifraud_captions.py`
- 手机屏幕净化脚本：`scripts/clean_phone_screen.py`
- ComfyUI 后台启动脚本：`scripts/launch_comfy_detached.py`

## 9. 最终交付物

| 交付物 | 路径 |
|---|---|
| 旧工作流成片 | `data/qa/anti_fraud_police_chibi_v1/old/final/anti_fraud_police_old_captioned.mp4` |
| 新增强工作流成片 | `data/qa/anti_fraud_police_chibi_v1/new/final/anti_fraud_police_new_captioned.mp4` |
| 新旧同屏对比 | `data/qa/anti_fraud_police_chibi_v1/comparison/anti_fraud_police_old_vs_new.mp4` |
| 旧版质量报告 | `data/qa/anti_fraud_police_chibi_v1/old/final/anti_fraud_police_old_raw.quality.json` |
| 新版质量报告 | `data/qa/anti_fraud_police_chibi_v1/new/final/anti_fraud_police_new_raw.quality.json` |
| 新版终检接触表 | `data/qa/anti_fraud_police_chibi_v1/new/final/anti_fraud_police_new_contact.png` |
| 对比接触表 | `data/qa/anti_fraud_police_chibi_v1/comparison/anti_fraud_police_old_vs_new_contact.png` |

两套成片均为 1080×1920、30fps、39.808 秒、H.264、yuv420p、BT.709。两份成片提取出的音频流 MD5 均为
`a65d3317aac6ea8845c57160f5f67fbd`，证明旁白、警官台词、停顿和时间线完全一致。

## 10. 实测结果与限制

- 旧版质量门通过，但镜头 07 出现了多余站立女性，作为无身份适配器基线保留。
- 新版镜头 01 的“桌面伸手拿手机”动作自然；镜头 04 的走步、揉太阳穴和停步完整，没有腿部畸形。
- 新版镜头 06 首次生成出现手机离开画面后重新进入，已重试；采用的第二版从胸前持机到看到来电，主体和手机均连续稳定。废片保存在 `new/video/rejected`。
- 新版镜头 07 只保留李婷和陈警官两人，停止手势、放低手机均清晰，没有旧版的第三个人物。
- 新版镜头 03 为优先保证手部和手机稳定，采用单手持机，未强求拇指在两个按钮间犹豫的高风险精细动作。
- 新版镜头 04 的下装从长裤漂移为短裙/短裤；不影响反诈叙事，但若用于角色连续剧，应改用 OpenPose 首帧或角色 LoRA 重做。
- 新版镜头 08 曾生成不可读小字，最终用确定性的不透明标语层覆盖；所有 UI/中文均不依赖扩散模型生成。
- 两版的自动发布质量门均通过，`issues` 为空。

## 11. XLabs Flux IP-Adapter 兼容结论

本机的 `Flux.1 Schnell FP8 + x-flux-comfyui` 不能沿用 ComfyUI 核心 `KSampler` 路线，实测会出现
`DoubleStreamBlock.forward() got unexpected keyword argument 'attn_mask'`。本项目改用 x-flux 官方
`XlabsSampler` 后成功生成。后续复制增强版工作流时必须保留这一采样器，不要自动替换成核心 KSampler。

由于 XLabs IP-Adapter 主要面向 Flux.1-dev，而本机底模为 Schnell，本次属于已跑通的实验组合。它对近景面部和双人镜头有改善，但不能代替角色 LoRA、姿态约束或逐镜审核。

## 12. 手机背面版 V2

2026-07-28 根据成片审核结果，新增“手机永不露屏幕”的安全构图预设：

- 镜头 01：手机背面朝上放在桌面，按侧边拿起，移动到耳边时不翻面。
- 镜头 03：越过手机背壳拍人物表情，以画外音和顶部提示表达境外号码。
- 镜头 05：取消悬停点击动作，改为人物阅读隐藏屏幕、空闲手在桌面收紧。
- 镜头 06：手机固定在胸前，只用眼神和下巴表现看到新来电；`110 来电`由后期叠加。
- 镜头 07：手机背面朝镜头，警官抬掌，李婷只下移手机几厘米。
- 镜头 08：手机平放于桌面且背面朝上，整个镜头保持静止。

手机背面规则配置：`data/qa/anti_fraud_police_chibi_v1/phone_back_overrides.json`。

最终交付：

| 交付物 | 路径 |
|---|---|
| 手机背面版·旧工作流（修复版） | `data/qa/anti_fraud_police_chibi_v1/phone_back_v2/old/final/anti_fraud_phone_back_old_fixed.mp4` |
| 手机背面版·IP-Adapter增强（修复版，推荐） | `data/qa/anti_fraud_police_chibi_v1/phone_back_v2/new/final/anti_fraud_phone_back_new_fixed.mp4` |
| 两版修复后同屏对比 | `data/qa/anti_fraud_police_chibi_v1/phone_back_v2/comparison/phone_back_fixed_old_vs_new.mp4` |
| 最终抽帧对比 | `data/qa/anti_fraud_police_chibi_v1/phone_back_v2/final_contact_comparison.png` |
| 接缝连续性检查 | `data/qa/anti_fraud_police_chibi_v1/phone_back_v2/new/final/seam_check.png` |

验收结果：

- 两版均为 1080×1920、30fps、39.808 秒、H.264、yuv420p、BT.709。
- 两版发布质量门均通过，自动报告的 `issues` 为空。
- 两版音频流 MD5 均为 `a65d3317aac6ea8845c57160f5f67fbd`，与此前版本完全一致。
- 对 6 个重生手机镜头各抽取 4 帧检查，未发现空白手机屏幕、AI界面乱码、手机离场重入或中途翻成正面。
- 旧工作流镜头 07 的警帽仍带有非真实的装饰徽记；增强版已采用无帽警官，适合优先发布。

### 12.1 分段重复修复

原合成器使用 `-stream_loop -1` 补足短于旁白的镜头，导致约 3.88 秒长的视频素材在同一场景内重新从首帧播放，形成“3 秒后回到 0 秒画面”的断裂感。

本次新增 `video_fit_mode: hold_last`：

- 视频素材只播放一次，不再循环。
- 素材早于旁白结束时，以最后一帧自然停留到该场景结束。
- 新旧工作流的 `story_video.json` 均已启用该模式。
- 已检查原循环点 3.880、10.820、16.690、21.016、25.702、29.740、36.490 秒；修复版没有回到首帧。
- 两版修复成片的发布质量门均通过，音频流 MD5 仍为 `a65d3317aac6ea8845c57160f5f67fbd`。

旧的 `*_captioned.mp4` 文件仅作为历史对照保留；后续交付和发布应使用 `*_fixed.mp4`。
