---
doc_status: planning
doc_category: design
last_reviewed: 2026-06-28
parent_doc: docs/IMPROVEMENT_ROADMAP.md
implements: V5（小说→纯视频）
estimated_effort: 8d
---

> 文档状态：设计文档，待评审。

# V5 · 小说→纯视频 Pipeline 设计文档

## 一、目标

**输入**：小说文本（一段或几段，几百到几千字）。
**输出**：纯视频 MP4（无角色叠加，无静态图），含旁白 + 角色对白 + 字幕 + BGM。

## 二、与 V4 的区别

| 维度 | V4 | V5 |
|---|---|---|
| 输入 | 短关键词 / 单段文本 | 整篇小说 / 长文本 |
| 角色 | Sonic fox 数字人（idle 循环） | **无** |
| 视觉 | ComfyUI 静态图（2 张） | **Wan 2.2 AI 视频片段**（N 段 3-5s）|
| 配音 | Edge-TTS 单旁白 | 旁白 + **角色对白** |
| 时长 | ~13s 短片 | ~30-60s（取决于小说长度）|
| 模型 | FLUX/Animagine (img2img) | Wan 2.2 (i2v) |
| GPU 显存 | 4-6 GB | 10-16 GB |

## 三、Pipeline 三阶段（按用户决策）

```
[novel.txt]
    ↓ L1: LLM 拆镜
[scenes.json] (N 段，每段 narration + dialogue + first/last frame prompts)
    ↓ L4: 单段视频生成 (Wan 2.2 i2v)
[clip_001.mp4 ... clip_N.mp4]
    ↓ L5: 直接 concat 成片
[final.mp4]
```

### L1 · LLM 拆镜（沿用 + 扩展）

**复用**：`scene_planner.py` 的分镜逻辑。

**新增字段**：
- `first_frame_prompt`: 用于 Wan 2.2 首帧的图像 prompt
- `last_frame_prompt`: 末帧图像 prompt（保证段间连贯）
- `narration`: 旁白文本（叙述用）
- `dialogue`: 角色对白（list of {speaker, text, emotion}）

**Pydantic schema**（A.4.1 L0）：
```python
class ScenePlan(BaseModel):
    scene_id: int
    narration: str = Field(min_length=5, max_length=300)
    dialogue: list[DialogueLine] = Field(min_length=0, max_length=10)
    first_frame_prompt: str = Field(min_length=20, max_length=200)
    last_frame_prompt: str = Field(min_length=20, max_length=200)
    duration_seconds: float = Field(ge=3.0, le=5.0)  # ship.md L1: 时长约束

class DialogueLine(BaseModel):
    speaker: str  # ship.md L1: 角色白名单
    text: str = Field(min_length=2, max_length=100)
    emotion: str = ""  # happy / sad / angry / neutral

class NovelSplit(BaseModel):
    scenes: list[ScenePlan] = Field(min_length=2, max_length=20)
```

**A.5.2 retry 参数变体**：
- v1 默认 prompt
- v2 加"请用具体名词" + "首尾帧要呼应"
- v3 切到 DeepSeek-V3 + 加 1 个 JSON 示例

### L4 · 单段视频生成（Wan 2.2 i2v）

**模型确认**：本地已有，无需下载。
- `wan2.2_ti2v_5B_fp16.safetensors` (9.4 GB)
- `wan2.2_vae.safetensors` (1.4 GB)
- `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (6.3 GB)
- `wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors` (27 MB, **4 步加速 LoRA**)

**单段生成步骤**（每段 3-5s）：
1. LLM 生成首帧图像 prompt → ComfyUI `keyframe_gen_xl.json` → first_frame.png
2. LLM 生成末帧图像 prompt → ComfyUI `keyframe_gen_xl.json` → last_frame.png
3. ComfyUI Wan 2.2 i2v：输入 first_frame + last_frame + motion prompt → clip.mp4

#### 4.1 2D 风格选择（与 B 档位主文档 §3.3 一致）

| 风格 | Checkpoint | 用途 | 备注 |
|---|---|---|---|
| **通用插画**（默认）| DreamShaper XL | 90% 场景 | 中文友好，风格化强 |
| **纯日系**（备选）| AnythingXL | 校园/恋爱题材 | 二次元浓度高 |
| **写实**（慎用）| RealVisXL | 现代都市 | 成功率较低，慎用 |

风格通过 `V5Style` 枚举选择，CLI 参数：`--style dream_shaper_xl` / `anything_xl` / `realvis_xl`。

#### 4.2 首末帧生成工作流（独立 workflow）

首末帧不是简单的 "img2img"，需要**角色一致性 + 构图控制**。独立 workflow JSON：

**`assets/workflows/keyframe_gen_xl.json`**：

| 节点 | 模型/LoRA | 强度 | 用途 |
|---|---|---|---|
| CheckpointLoader | DreamShaper XL（或 AnythingXL） | — | 底模 |
| PuLID_Apply | 角色参考图（reference_face.png） | fidelity 0.85 | 角色脸一致性 |
| ControlNet (Lineart) | 首末帧构图 lineart | weight 0.7 | 构图锁定 |
| CLIPTextEncode | first_frame_prompt / last_frame_prompt | — | 场景描述 |
| KSampler | 25 步, cfg 7, euler | — | 出图 |
| VAEDecode + SaveImage | — | — | 存 PNG |

**角色参考图管理**：
- 每个角色 1 张正脸 PNG，存 `data/characters/<name>/reference.png`
- L1 拆镜时输出的 characters 列表必须与 reference 目录一致（白名单校验）
- 找不到 reference 时降级到无 PuLID（角色一致性会下降，记录 WARNING）

#### 4.3 异常处理（复用 I-2 模式）

- Wan i2v 失败 → 重试 1 次（不同 seed）
- 仍失败 → 降级：用 first_frame.png 做 4s 静态图（类似 V4）
- 全部失败 → 抛 `VideoClipUnavailableError`，记录到 `video_clip_failures` 表

### L5 · 后期合成（直接 concat）

**新增模块**：`src/content_factory/video_concat.py`

```python
def concat_clips(
    clip_paths: list[Path],
    narration_paths: list[Path],
    output_path: Path,
    bgm_path: Path | None = None,
    subtitle_paths: list[Path] | None = None,
) -> Path:
    """ffmpeg concat:
    1. 每个 clip + 对应 narration/dialogue 混音
    2. concat demuxer 拼接所有段（无损、不重编码）
    3. 叠加 BGM（音视频混合）
    """
```

#### 5.1 段间连贯性校验（concat 前自动）

```python
def verify_segment_continuity(
    prev_clip_path: Path,
    next_clip_path: Path,
    threshold: float = 0.3,
) -> bool:
    """抽末帧和首帧，计算 LPIPS 距离。
    返回 True 表示视觉过渡平滑，False 表示需要 prompt 变体重试。"""
    end_frame = extract_last_frame(prev_clip_path)     # 540x960 RGB
    start_frame = extract_first_frame(next_clip_path)
    distance = compute_lpips(end_frame, start_frame)  # 0~1，<0.3 通常流畅
    return distance < threshold
```

**触发位置**：video_concat.py 在 concat 前自动校验，任意相邻段 LPIPS > 0.3 时：
- 记录 WARNING + log.error_class="CONTINUITY_BREAK"
- 不阻断流程（视觉断点有时是叙事需要），但把段落标记 quarantined
- 若 strict mode：阻断 + 重跑该段的 Wan i2v（不同 seed）

LPIPS 模型：`data/models/lpips/alexnet-0.1.pth`（约 50MB，首次使用时下载）。

#### 5.2 音视频对齐策略

Edge-TTS 合成的 narration 音频时长 **通常 ≠** 视频段时长（3-5s 是硬约束）。三种对齐方式：

| 策略 | 优点 | 缺点 |
|---|---|---|
| **音频优先切割视频**（推荐）| 对白精准，台词不被截断 | 视频镜头被截断（首/末帧可能跳）|
| 视频优先切割音频 | 镜头完整 | 对白末尾被截（不可接受）|
| 整体音频合成后匹配视频 | 编排灵活 | 实现复杂，TTS 延迟叠加 |

**推荐音频优先切割**（对话类内容观众更在意台词清晰）：

```python
def align_audio_to_clip(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """按 TTS 时长切割视频：
    - TTS 时长 < 视频时长：截掉视频末尾
    - TTS 时长 > 视频时长：用 ffmpeg atempo 加速视频（限制 0.5~2.0x）
    - 超出 atempo 限制：返回原视频时长 + 警告"""
    video_dur = get_duration(video_path)
    audio_dur = get_duration(audio_path)
    if abs(video_dur - audio_dur) < 0.5:
        # 自然对齐：直接合并
        ...
    elif audio_dur < video_dur:
        # 音频短：截视频到音频长度
        subprocess(["ffmpeg", "-y", "-i", video_path, "-t", str(audio_dur), "-c", "copy", output_path])
    else:
        # 音频长：加速视频（0.5x~2x 范围内）
        speed = video_dur / audio_dur
        if 0.5 <= speed <= 2.0:
            subprocess(["ffmpeg", "-y", "-i", video_path, "-filter:v", f"setpts={1/speed}*PTS", ...])
        else:
            # 超出范围：截到 max(2x 加速后) + 警告
            logger.warning(f"TTS {audio_dur}s vs 视频 {video_dur}s 超出 atempo 范围")
```

#### 5.3 字幕

- 默认硬字幕（drawtext 烧录）
- 可选：soft subtitle（mov_text），便于后期修改
- 字幕时间戳：从 Edge-TTS 的 SubMaker 输出 WordBoundary 拿到每字时间

## 四、模块改动清单

### 新增

| 模块 | 路径 | 工作量 |
|---|---|---|
| Wan 2.2 ComfyUI workflow JSON | `assets/workflows/wan22_i2v_4step.json` | 1 天 |
| Wan pipeline 封装 | `src/content_factory/wan_pipeline.py` | 2 天 |
| Novel L1 拆分 | `src/content_factory/novel_splitter.py` | 1 天 |
| Pydantic schema | `src/content_factory/novel_schemas.py` | 0.5 天 |
| Video concat（含 narration 合成）| `src/content_factory/video_concat.py` | 1 天 |
| 端到端 CLI | `src/content_factory/v5_pipeline.py` | 0.5 天 |
| 单测 | `src/tests/unit/test_v5_pipeline.py` | 0.5 天 |
| Alembic 迁移（video_clip_failures 表） | `alembic/versions/0008_video_clip_failures.py` | 0.5 天 |

### 复用 + 修改

| 模块 | 改动 |
|---|---|
| `scene_planner.py` | 加 `first_frame_prompt` + `last_frame_prompt` 字段 |
| `script_generator.py` | 加 `narration` + `dialogue` 字段 |
| `background_resolver.py` | 不再用于 V5（保留作为 V4 fallback） |
| `presenter_pipeline.py` | 不动（V4 仍可用）|
| `video_composer.py` | 不动（仍服务 V4）|

## 五、ComfyUI Workflow 设计（wan22_i2v_4step.json）

```json
{
  "1": {"class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "wan2.2_ti2v_5B_fp16.safetensors"}},
  "2": {"class_type": "LoadLora",  // 4 步加速 LoRA
        "inputs": {"model": ["1", 0],
                   "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
                   "strength_model": 1.0}},
  "3": {"class_type": "VAELoader",
        "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
  "4": {"class_type": "CLIPLoader",  // umt5 text encoder
        "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                   "type": "wan"}},
  "5": {"class_type": "LoadImage",  // 首帧
        "inputs": {"image": "first_frame.png"}},
  "6": {"class_type": "LoadImage",  // 末帧
        "inputs": {"image": "last_frame.png"}},
  "7": {"class_type": "WanImageToVideo",  // 关键节点
        "inputs": {"positive": ["CLIPTextEncode", 0],  // prompt
                   "negative": ["CLIPTextEncode", 1],
                   "vae": ["3", 0],
                   "start_image": ["5", 0],  // 首帧
                   "end_image": ["6", 0],    // 末帧
                   "width": 540,
                   "height": 960,
                   "length": 81,            // 5s @ 16fps
                   "batch_size": 1,
                   "seed": 42}},
  "8": {"class_type": "KSampler",
        "inputs": {"model": ["2", 0],     // 用 LoRA 后的 model
                   "positive": ["7", 0],
                   "negative": ["7", 1],
                   "latent_image": ["7", 4],
                   "steps": 4,             // LoRA 加速：4 步即可
                   "cfg": 1.0,
                   "sampler_name": "euler",
                   "scheduler": "simple",
                   "denoise": 1.0}},
  "9": {"class_type": "VAEDecode",
        "inputs": {"samples": ["8", 0],
                   "vae": ["3", 0]}},
  "10": {"class_type": "VHSVideoCombine",  // 视频输出
         "inputs": {"images": ["9", 0],
                    "frame_rate": 16,
                    "loop_count": 1,
                    "filename_prefix": "v5_clip",
                    "format": "video/h264-mp4"}}
}
```

## 六、CLI 接口

```bash
python main.py novel-video \
  --input data/novels/sample.txt \
  --output data/videos/v5_sample.mp4 \
  --model wan2.2_ti2v \
  --style dream_shaper_xl \
  --segment-duration 4 \
  --bgm data/ref_audio/bgm.mp3 \
  --use-gpt-sovits false
```

**max_segments 默认动态计算**（不传 `--max-segments` 时）：

```python
def calc_max_segments(text_length: int) -> int:
    """每镜约 200-300 字。少于此下限 → 4 镜下限；多于上限 → 15 镜上限。"""
    return max(4, min(15, text_length // 250))
```

例：
- 500 字短篇 → `max(4, min(15, 500//250))` = max(4, 2) = **4 镜**（下限保护）
- 2000 字 → max(4, 8) = **8 镜**
- 5000 字 → min(15, 20) = **15 镜**（上限保护）

**输出**：
- `data/videos/v5_sample.mp4`（30-60s 纯视频）
- `data/presenter_v5/<timestamp>/` 包含所有中间产物（首末帧 PNG、clip MP4、narration MP3、segments.json）

## 七、单测覆盖

```python
class TestV5Pipeline:
    def test_novel_split_pydantic_validation(self): ...
    def test_scene_duration_constraint_3_to_5s(self): ...
    def test_dialogue_speaker_in_whitelist(self): ...
    def test_wan_pipeline_submit_workflow(self): ...
    def test_wan_pipeline_oom_fallback_to_static(self): ...
    def test_video_concat_preserves_order(self): ...
    def test_end_to_end_sample_novel(self): ...  # 跑一个 200 字短篇
```

## 八、时间表（8 天）

| 天 | 内容 |
|---|---|
| D1-2 | L1: novel_splitter + Pydantic schema（scene_plan, dialogue, novel_split）|
| D3 | Wan 2.2 ComfyUI workflow JSON 调通 + 试跑单段 + **D3 验证产物（见 §8.1）**|
| D4-5 | wan_pipeline.py：HTTP API 调用 + 重试 + 降级到静态图 |
| D6-7 | v5_pipeline.py + video_concat.py（拼音频 + BGM + 字幕 + 段间连贯性校验 + 音视频对齐）|
| D8 | 端到端跑 sample novel + 写单测 + 端到端 CLI |

### 8.1 D3 验证产物（实测数据采集）

D3 末尾必须留出实测数据，让预估变成事实：

```markdown
## D3 实测记录（实际填入）

| 项 | 预估 | 实测 | 差异 |
|---|---|---|---|
| 首末帧静态图（DreamShaper XL） | ~5s/张 | ___s | ___ |
| Wan 2.2 i2v 单段（4 步 LoRA） | 30-60s | ___s | ___ |
| Wan 2.2 i2v 单段（25 步无 LoRA） | 5-10min | ___min | ___ |
| 单段显存峰值 | ~12GB | ___GB | ___ |
| keyframe_gen_xl PuLID 显存 | ~8GB | ___GB | ___ |
| 端到端 8 段小说耗时 | ~10min | ___min | ___ |
```

**产物文件**：
- `data/test/wan22_test_clip_001.mp4`（单段成功）
- `data/test/wan22_test_keyframe_001.png`（首帧示例）

**实测数据让预估变成事实**，D4-D8 的容量规划基于实际数据调整。

## 九、风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Wan 2.2 单段 30-60s 推理太久 | 10 段需要 10 分钟 | 用 4 步加速 LoRA（已下好）+ max_segments ≤ 8 |
| Wan 2.2 显存 12-16 GB | 单卡跑满 | 降分辨率到 480x832 + LoRA 4 步 |
| 首末帧图像生成质量差 | 视频跳变 | L1 prompt 用 Pydantic 校验 + audit (Qwen-as-judge) |
| 角色对白角色识别错 | 配音错位 | ship.md L1: 角色名白名单校验 |
| 长小说 N 段爆炸 | 视频过长 | 默认 max_segments=8，可手动指定 |

## 十、不在本期范围

- 3D 效果（用户已明确接受 2D）
- 角色 3D 模型（MuseTalk / SadTalker 不做）
- 实时生成（V5 是 batch 处理）
- 视频编辑（剪辑、转场）
- 字幕特效（基础硬字幕即可）

## 十一、ROADMAP 更新

在 [docs/IMPROVEMENT_ROADMAP.md](IMPROVEMENT_ROADMAP.md) 加 Phase 2.5：

```
### Phase 2.5 · V5 小说→纯视频 Pipeline（NEW，基于 ship.md）

| 编号 | 名称 | 工作量 | 依赖 | 状态 |
|---|---|---|---|---|
| **V5-1** | L1 LLM 拆镜 + Pydantic schema | 1d | I-3 | ⏳ |
| **V5-2** | Wan 2.2 ComfyUI workflow JSON | 1d | — | ⏳ |
| **V5-3** | wan_pipeline.py + I-2 容错复用 | 2d | V5-2 | ⏳ |
| **V5-4** | video_concat.py（拼音视频 + BGM + 字幕）| 1d | V5-3 | ⏳ |
| **V5-5** | v5_pipeline.py 端到端 + CLI + 单测 | 2d | V5-4 | ⏳ |

合计 7-8 天。模型权重**已就位**无需下载。
```

## 十二、立即可做（你确认后即开始）

D1: 实现 `src/content_factory/novel_schemas.py`（Pydantic schema）
+ `src/content_factory/novel_splitter.py`（LLM 拆镜）
D2: 复用现有 `chat_completion_tracked` + retry prompt 变体（A.5.2）

跑通后用一段 200 字短篇验证 L1 输出质量，再决定是否进 D3+。

---

**附录**：设计文档索引
- [docs/ship.md](ship.md) - 编排状态机（A.2）/ 重试（A.5）/ 校验（A.4）/ 二审（A.6）
- [docs/IMPROVEMENT_ROADMAP.md](IMPROVEMENT_ROADMAP.md) - V5 在 Phase 2.5
- [docs/design/llm-governance.md](llm-governance.md) - LLM 限流/缓存/计量（I-4）— V5 L1 拆镜直接复用
- [docs/design/comfy-resilience.md](comfy-resilience.md) - 容错模式 — V5 Wan pipeline 直接复用
