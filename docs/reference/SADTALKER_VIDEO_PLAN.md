---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# 角色口型视频生成方案（修订版）

> 更新时间：2026-04-30
> 状态：SadTalker ✅ 已部署（conda sadtalker 环境，5070 Ti 可用）｜ 角色人格 ⚠️ 待集成到脚本生成 ｜ 背景叠加 ⚠️ 待实现

---

## 1. 当前已有 vs 缺失

| 环节 | 状态 | 说明 |
|------|------|------|
| 角色图片 | ✅ 完成 | 角色A / 角色B 单人图已就绪 |
| 语音合成 | ✅ 完成 | Edge-TTS（已集成，两个角色不同音色） |
| SadTalker 部署 | ✅ 完成 | conda sadtalker 环境，5070 Ti 可用 |
| 口型视频生成 | ✅ 完成 | 已测试成功，2-3 分钟/个 |
| **角色人格刻画** | ❌ 缺失 | 脚本生成未考虑角色性格区分 |
| **背景视频叠加** | ❌ 缺失 | 需要叠加在原版视频上，非独立展示 |
| **视频时长扩展** | ❌ 缺失 | 对话可能比背景视频长，需要循环/拼接 |
| 视频拼接合成 | ⚠️ 待实现 | FFmpeg / MoviePy 左右分屏 + 叠加 |

---

## 2. 完整流程（修订后）

```
背景视频（可灵 / ComfyUI 原版）
    ↓【可选：首尾拼接扩展时长】
循环背景视频（与对话总时长对齐）
    ↓
对话脚本生成（RAG + LLM + 角色人格描述）
    ↓
Edge-TTS 生成角色A语音（沉稳学长音色）
Edge-TTS 生成角色B语音（元气学弟音色）
    ↓
SadTalker 驱动角色A图 + a.wav → 角色A口型.mp4
SadTalker 驱动角色B图 + b.wav → 角色B口型.mp4
    ↓
角色口型叠加到背景视频（透明度/位置可调）
    ↓
BGM 混音
    ↓
最终输出视频
```

---

## 3. 角色人格刻画（新增）

### 3.1 角色设定

```python
ROLE_A_PERSONA = {
    "name": "学长",
    "voice": "zh-CN-YunjianNeural",
    "rate": "+5%",
    "traits": ["逻辑清晰", "语速中等", "冷静沉稳", "擅长用例子讲解"],
    "style": "A 是引导者，擅长从实际问题切入，用具体案例帮助理解",
}

ROLE_B_PERSONA = {
    "name": "学弟",
    "voice": "zh-CN-XiaoyiNeural",
    "rate": "+10%",
    "traits": ["普通人视角", "真诚好奇", "语速轻快", "有真实生活感受"],
    "style": "B 从真实生活场景出发，先描述遇到的困惑或经历，再自然引出对原理的追问",
}
```

### 3.2 对话模式

真实感对话的关键：**B 先描述一个真实生活场景/困惑，然后 A 自然引入概念并解释原理**。

```
B（遇到真实情况）→ A（引出概念）→ B（追问为什么）→ A（解释原理）→ B（恍然大悟/举一反三）
```

**示例（以"复利"为例）**：

```
B: 最近想存点钱，朋友推荐了一个理财产品，说收益很高，但我看那个计算方式有点看不懂。
A: 你是说那种"利滚利"的计算方式吧？听起来像复利效应。
B: 复利？对，就是那个！它和普通存款利息有什么区别吗？
A: 简单说，普通存款是本金乘以利率，而复利是每一期的利息也计入下一期的本金继续产生利息。相当于利息也在帮我们赚钱。
B: 哦我明白了！那是不是存得越久，实际收益增长得越快？
A: 对，这就是复利的威力。拿10万块、年利率5%来说，10年后不是变成15万，而是约16.3万，时间越长差距越大。
B: 难怪说"时间就是金钱"，原来是这么回事！
```

### 3.3 脚本生成 prompt

```python
SYSTEM_PROMPT = f"""你是一个知识科普对话节目，追求真实自然，像两个朋友在聊天。
角色设定：
- 角色A（{ROLE_A_PERSONA['name']}）：{'，'.join(ROLE_A_PERSONA['traits'])}。对话风格：{ROLE_A_PERSONA['style']}
- 角色B（{ROLE_B_PERSONA['name']}）：{'，'.join(ROLE_B_PERSONA['traits'])}。对话风格：{ROLE_B_PERSONA['style']}

对话规律（重要）：
1. B 先从真实生活场景或具体经历切入（不是直接问概念）
2. A 从 B 描述的场景引出知识点
3. B 追问"为什么"或"什么意思"
4. A 用具体数字或例子解释原理
5. B 联系回自己或举一反三
6. 内容基于以下知识：{{context}}

要求：
- B 说的话要像生活中真的在聊天的语气，可以有"诶"、"话说"、"我记得"等
- A 的解释要清晰但不书面，像在认真教导朋友
- 对话控制在 4-8 轮，总时长 30-60 秒
"""
```

### 3.4 更多场景示例

**话题：电商促销折扣**

```
B: 前两天看到电商平台说"付定金尾款半价"，算了一下好像也没便宜多少？
A: 你算的是定金减免的部分吧？其实这类促销涉及"先涨后降"和"定金膨胀"两种玩法。
...
```

**话题：健康管理**

```
B: 我现在开始早起晨跑了，但感觉体重没怎么降，是不是运动没用？
A: 你是做什么类型的运动？时长多少？
...
```

---

## 4. 背景视频叠加（新增）

### 4.1 素材说明

原版视频（背景层）：
```
D:\IT\AI_vido\ComfyUI\vido\4月19日.mp4
```
时长不够时，可首尾拼接扩展。

### 4.2 FFmpeg 叠加命令

```bash
# 背景视频在下层，角色A在左侧，角色B在右侧
ffmpeg -y `
    -stream_loop 3 -i background.mp4 `
    -i role_a_sadtalker.mp4 `
    -i role_b_sadtalker.mp4 `
    -filter_complex "
        [0:v]scale=1280:720[bg];
        [1:v]scale=320:360[role_a];
        [2:v]scale=320:360[role_b];
        [bg][role_a]overlay=x=0:y=180[tmp1];
        [tmp1][role_b]overlay=x=960:y=180
    " `
    -map 0:a? `
    -c:v libx264 -crf 23 -preset fast `
    output_with_characters.mp4
```

### 4.3 位置参数

| 位置 | x | y | 说明 |
|------|---|---|------|
| 角色A（左） | 0 | 180 | 背景720p，左侧角色高360居中 |
| 角色B（右） | 960 | 180 | 右侧，960=1280-320 |
| 背景 | 0 | 0 | 铺满1280x720 |

---

## 5. 视频时长扩展（新增）

背景视频短于对话时，用 FFmpeg 循环补齐：

```bash
# 获取音频时长
AUDIO_DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 audio.wav)

# 循环背景视频以对齐音频
ffmpeg -y -stream_loop 3 -i background.mp4 -i audio.wav \
    -shortest -map 0:v -map 1:a \
    background_looped.mp4
```

---

## 6. 完整合成代码

```python
from moviepy.editor import (
    VideoFileClip, AudioFileClip,
    CompositeVideoClip, concatenate_videoclips, clips_array
)

def compose_final_video(
    background_path: str,
    clip_a_path: str,
    clip_b_path: str,
    audio_a_paths: list,
    audio_b_paths: list,
    bgm_path: str = None,
    output_path: str = "data/videos/final_dual.mp4",
):
    # 1. 合并对话音频
    def concat_audio(paths):
        return concatenate_videoclips([AudioFileClip(p) for p in paths])

    audio_a = concat_audio(audio_a_paths)
    audio_b = concat_audio(audio_b_paths)
    total_duration = max(audio_a.duration, audio_b.duration)

    # 2. 背景视频循环对齐音频
    bg = VideoFileClip(background_path).loop(duration=total_duration).without_audio()

    # 3. 角色口型视频
    role_a = (VideoFileClip(clip_a_path)
               .subclip(0, min(audio_a.duration, 999))
               .resize(height=360))
    role_b = (VideoFileClip(clip_b_path)
               .subclip(0, min(audio_b.duration, 999))
               .resize(height=360))

    # 4. 背景叠加双角色
    video = CompositeVideoClip([
        bg,
        role_a.set_position(("left", "center")),
        role_b.set_position(("right", "center")),
    ], size=bg.size).set_duration(total_duration)

    # 5. 混音（BGM 音量压低）
    dialogue = clips_array([[audio_a.set_fps(44100), audio_b.set_fps(44100)]])
    if bgm_path:
        bgm = AudioFileClip(bgm_path).subclip(0, total_duration).volumex(0.3)
        final_audio = CompositeAudioClip([dialogue, bgm])
    else:
        final_audio = dialogue

    final = video.set_audio(final_audio)

    # 6. 输出
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    final.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")
    print(f"Done: {output_path}")
```

---

## 7. 待办清单

- [x] SadTalker 部署（conda sadtalker 环境，5070 Ti 可用）
- [x] 测试角色口型视频生成
- [ ] 角色人格 prompt 集成到脚本生成
- [ ] 首尾拼接扩展背景视频
- [ ] 背景 + 双角色叠加输出
- [ ] BGM 混音
- [ ] 集成到 main.py auto-publish
