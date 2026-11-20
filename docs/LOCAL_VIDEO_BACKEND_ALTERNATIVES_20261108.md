# 本机可替换视频后端：只读调查（2026-11-08）

**结论：LTX-2.3 distilled FP8 是可保留的本地候选，当前没有可直接运行的权重。现有8190已具备官方首尾帧音视频蓝图全部原生节点；理论最小接入可只加两份权重、不装新节点/不改服务。但16GB显存、32GB内存的实际运行和中文多人说话控制均未验证，本轮不下载约39GB模型、不替换正在运行的A/B。**

## 本机事实

- GET `127.0.0.1:8190/object_info`：已注册LTXAVTextEncoderLoader、EmptyLTXVLatentVideo、LTXVImgToVideo(Inplace)、LTXVAddGuide、LTXVConcatAVLatent/SeparateAVLatent、LTXVEmptyLatentAudio、AudioVAE Encode/Decode、FreezeLatent、ReferenceAudio、GetICLoRAParameters。
- 已读取本地 `D:/IT/AI_vido/ComfyUI/blueprints/First-Last-Frame to Video (LTX-2.3).json`，SHA `f05a9025c1ba72db7e29d175d1942a89692c8ea3015a5cb6b00b62cb89490f10`。展开子图后24个原生节点类型全部在当前服务，0缺项；UUID子图包装不误算缺节点。
- D盘模型根中的clip/LTX、loras/LTX、unet/LTX2、vae/LTX-Kijai只发现一份缓存gitignore，没有模型；live checkpoint/Gemma枚举也缺所需权重。未遍历C盘。
- 对应原始证据在 `data/qa/spatial_v26/backend_survey/`：LIVE_NODES、LOCAL_LTX_FILES、LOCAL_FLF_BLUEPRINT_FACTS、READONLY_SUMMARY。

## 最小候选与下载体积

|用途|官方发布文件|约体积（发布页显示，十进制）|
|---|---|---|
|模型＋视频VAE＋音频VAE等完整checkpoint|`Lightricks/LTX-2.3-fp8/ltx-2.3-22b-distilled-fp8.safetensors`|29.5GB|
|本地文本编码器|`Comfy-Org/ltx-2/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors`|9.45GB|
|合计|两份文件；VAE复用checkpoint，不再重复算一份|约38.95GB（约36.3GiB）|

体积源：[Lightricks原文件](https://huggingface.co/Lightricks/LTX-2.3-fp8/blob/main/ltx-2.3-22b-distilled-fp8.safetensors)、[Comfy-Org编码器](https://huggingface.co/Comfy-Org/ltx-2/blob/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors)。本机官方FLF蓝图三个loader也指向上述两文件，未要求额外VAE、LoRA或上采样器。HF API精确字节查询直连超时，记录失败；上述为页面舍入体积，不伪造精确byte或SHA。

最小recipe采用原生FLF联合音视频图：CheckpointLoader→模型/视频VAE；同checkpoint→AudioVAELoader；Gemma＋checkpoint→TextEncoder；视频latent经两次AddGuide锚定首/尾，音频空latent与视频Concat→采样→Separate→视频与音频分别Decode→CreateVideo/SaveVideo。官方distilled为8步、CFG1；本地蓝图sigmas为 `1,0.99375,0.9875,0.98125,0.975,0.909375,0.725,0.421875,0`。首次只应独立小样（例如384×672、121帧/24fps），不直接开一整分钟。[官方Comfy说明](https://docs.comfy.org/tutorials/video/ltx/ltx-2-3)

如要预制音频驱动口型，可研究同页IA2V；如要Blender深度/姿态调度，可研究IC-LoRA Union Control。两者比最小FLF多权重与约束，不能把节点存在等同于本机已验证可用，也不应把H3五图Picture机制直接搬过来。

## 硬件与中文边界

[官方Desktop当前main](https://github.com/Lightricks/LTX-Desktop)已经推荐Windows24GB显存、32GB内存；[当前兼容矩阵](https://github.com/Lightricks/LTX-Desktop/blob/main/docs/local-compat-matrix.md)列16GB streaming支持部分T2V/I2V/A2V，但Windows streamed Fast通常要求40GiB内存，NVMe映射路径降到32GiB；IC-LoRA/编辑还有不同门槛。因此旧版“16GB能跑”不能推导本机稳定跑全功能，更不能拿第三方8GB广告当验收。该矩阵属于Desktop运行时，不是本机Comfy性能实证；不建议为本轮另装Desktop。

[官方模型卡](https://huggingface.co/Lightricks/LTX-2.3/raw/main/README.md)metadata列zh等9语言，但正文Model Details写English。必须标为**中文原生对白、童声和指定人物口型未实证**，不能承诺比H3强。尺寸需32倍数、帧数8n+1。FP8/FP4可减权重内存，但不保证峰值激活、offload延迟或主机内存满足。

## 许可证与其他候选

- LTX为自定义[Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2)，不是non-commercial，也不是Apache。年度收入至少1000万美元的实体需另付费商用许可；还有用途及竞争性产品限制。当前私人本地视频试验可列候选，不能据此替任意主体保证无限制商用。Gemma编码器另受[Google Gemma条款](https://ai.google.dev/gemma/terms/)约束；仓库再打包不消除上游条款。
- [HunyuanVideo-Avatar](https://github.com/Tencent-Hunyuan/HunyuanVideo-Avatar)：论文描述多人分脸音频注入，但发布版/10GB路径对三人剧情的能力未核验；官方10GB说明链接Wan2GP，基础安装是Linux/Python3.10/旧torch/flash-attn，官方ComfyUI项目计划仍未勾选。不能视为给当前服务加权重即可。其[Community License](https://github.com/Tencent-Hunyuan/HunyuanVideo-Avatar/blob/main/LICENSE)排除欧盟/英国/韩国并有其他使用条件，不能标任意商用。当前不纳入本轮。
- SHARP已因其模型non-commercial范围被本轮排除，不因代码公开重新纳入生产。

本调查仅读取API、D盘模型文件名/大小、官方文档和蓝图；下载模型0、安装0、GPU/模型POST0、服务变更0、A/B输入及speech/runtime修改0。推荐保留“后续原生LTX FLF/IA2V短样”候选，当前不扩大下载或另建50GB框架。
