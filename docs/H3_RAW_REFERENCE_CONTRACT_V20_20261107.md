# H3原始视频提示词与人物/环境参考：v20

本组件只做纯CPU的prompt/graph构造，不调用文本模型，不生成组合首图，不提交媒体，不写资产库，也不放宽旧v15/v19的校验。文件：src/content_factory/visual_h3_reference_passthrough_v20.py。root独立runner负责源文件/音频绑定、输入暂存、未知结果不重派、视频收存与真实验收。

## 已核本地真实能力

- MiniMaxH3ImageToVideo只有first_frame/last_frame，不接受ref_images。旧fl2va路径不能冒充多参考图输入。
- MiniMaxH3ReferenceToVideo支持不带首帧的纯参考模式，最多9张参考图；每个图片batch只用第一张，必须独立LoadImage。API动态槽为ref_images.ref_image_0至_8，提示标签按实际顺序为<Picture 1>至<Picture 9>。
- 接video VAE时参考同时进入DiT参考latent；不接只进视觉文本编码。本组件连接现有video VAE。
- 需要不同的minimax_h3_ref2va_pruned_int8_convrot.safetensors；D盘已存在20,970,379,616字节，历史官方校验SHA9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779，本轮没有重算20GB整文件SHA或实推。当前正在运行的fl2va图不改。
- ref_image_size=match默认按输出面积等比缩小并round32；max参考短边上限2048、参考token全程参与采样，可能更慢。本轮没有性能/画面质量验收。
- 官方已缓存UI模板：data/model_maintenance/minimax_h3_20261015/official_reference/video_minimax_h3_r2v.json。节点源码、运行中/object_info只读响应、tokenizer引用格式及历史下载证明均绑定在data/qa/h3_reference_passthrough_v20/CAPABILITY_READONLY.json。

## 构造API

```python
result = build_graph(
    base, bundle, source_prompt, input_mapping, scope, width, height, frames, seed,
    reference_mode="reference_only",
    auxiliary_tail=None, ref_image_size="match",
)
```

base是现有project API graph（condition=MiniMaxH3ImageToVideo及127/129/130等已有节点），不是UI模板。bundle直接使用visual_h3_reference_bundle_v20.collect输出；函数强制调用其validate重核真实当前审核/版本/来源。input_mapping是reference_id到caller已经暂存的Comfy相对图片名的精确映射。每张独立LoadImage，不按像素SHA合并不同角色。

结果含graph、compiled_prompt、source_prompt_sha256/byte_length、reference_map、bundle_sha256和完整reference_bundle。reference_map含1基Picture标签、0基flat槽、loader node、源文件SHA、相对输入名和预计节点缩放尺寸。输出原生5+17n帧、124至362帧、24fps、宽高32倍数。本模块复用base采样/音画保存，改为Ref2VA条件与已在盘ref2va权重，不带first_frame/last_frame。validate_graph是独立v20函数，不调用/修改旧共享_validate_graph。

source_prompt可直接给UTF8 bytes或str。保BOM、CRLF与所有原文字符为精确前缀，只附加按Picture映射的人物外观/服装、环境来源清单。相同entity的front/side明确归于同一人物，不描述成两人。不增加固定机位、构图、推拉禁止、动作重写、时序重排或新的声音指令。已有Picture标签只核有对应槽，不静默重编号；其人物含义需caller与bundle对应。此版不接Video/Audio参考输入，发现原文有未真实绑定的该类标签会拒绝。

## 原文优先与旧提示词污染门

prompt_from_shot优先complete_video_prompt/full_video_prompt/video_prompt/source_video_prompt，原样返回且完整字段须含原audio句。明确source_prompt文件/bytes完全绕过renderer。若只有通用visual_prompt则保其原文，并直接拼接原audio.text（含引号/换行不JSON转义），speaker/mode/source_speaker/source_channel/source_direction等原元数据另列。static_start_prompt/opening不会当全段视频内容。

旧staging_provenance.schema=continuous_source_home_staging/v6而无明确完整视频字段时硬拒，要求原始source prompt；不以regex偷偷删除旧“固定侧面”等适配文字，不把v6模型再写稿冒称原文。

## 确定性本窗原文renderer

`prompt_from_source_window(scene, window)`供新planning.source_prompt_contract=source_window/v20分支使用。只取window.action_ids及早于窗口开始、仍与本窗重叠的持续actions；逐行description原串。只取window.audio_ids中的完整原台词，直接拼接text，不转义引号/换行；原speaker/mode及全部元数据保留。原timeline/story_time/place_id/location/time/camera逐值标注，不读取scene.plot/information/performance，避免整场未来情节漏入本窗。原本无动作的音频窗/环境空镜合法；错误未来ID、已结束ID、未知ID、错场及劈开音频拒绝。root负责新planner分支把此字符串写入complete_video_prompt，不改变旧planner默认或旧冻结稿。

角色reference集合必须与source_shot.visible_cast精确相等。只有源visible_cast确实为空，才允许环境-only；环境canonical+指定view永远必需。collector不受旧组合首图两人cap限制，本适配器则总图数硬上限9，不截断/拼贴以凑数。

## 旧尾帧仅辅助

可选auxiliary_tail={image,native_result,review}，三者均为path/SHA文件绑定。native RESULT须有已知prompt_id及同SHA的files.last；review须schema=reviewed_h3_auxiliary_tail/v20，accepted_for_continuity=true，并绑定同book/source/image/native_result。它占第N个Picture，含它仍最多9；不能取代本窗人物/场景的任何必需参考。root须真实审图后出具证明，本模块不自行批准。

## 验证范围

纯CPU回归覆盖原文BOM/CRLF字节前缀、仅参考appendix、四/九槽映射、同人多视图/同像素双身份、必需参考缺项、已审尾图、源与文件/graph篡改、空镜、旧v6门、本窗动作边界、原始含引号换行台词和无动作音频窗。参考权重的本机真实加载、显存/速度、声音和画面一致性尚未验收，不能用程序测试替代。
