# 杀猪盘反诈短剧《完美恋人》制作报告

完成时间：2026-07-29  
项目目录：`data/qa/perfect_lover_pig_butchering_v1`  
成片时长：170.9 秒（2 分 50.9 秒）  
画幅：竖屏 9:16  
叙事方式：纯人物对白，无旁白、无画外普法

## 1. 剧情改编

原始长剧本被改编为 19 个短镜头、707 字对白，完整保留以下阶段：

1. 养号与完美人设。
2. 每日关心和未来承诺。
3. 一千元试投与伪造收益。
4. 五万元“大额收割”。
5. 巴黎照片和手机型号破绽。
6. 用“高风险账户”试探对方。
7. 情感操控失效、保存证据、举报拉黑。

所有反诈信息均通过人物对白、表演和确定性文字卡出现，没有加入旁白解释。

## 2. 固定人物档案

### 林小雨

- 年龄与身份：25 岁，都市白领。
- 脸型与五官：柔和鹅蛋脸，深棕色杏眼，小巧直鼻，自然唇形。
- 发型：深棕色中短直发，空气侧刘海，低位半扎。
- 服装：奶油色针织上衣、灰粉色针织开衫、月牙银项链。
- 气质曲线：温柔期待 → 迟疑 → 依赖 → 恐惧 → 清醒 → 克制释然。
- 最终人物母版：`references/linxiaoyu/keyframes/linxiaoyu_anchor.png`。

### 陈默

- 年龄与身份：28 岁，对外包装为精英项目经理，实际为诈骗团伙成员。
- 脸型与五官：偏长鹅蛋脸，深棕色眼睛，浓直眉，干净短发。
- 固定识别物：黑色细框眼镜、自然侧分短发。
- 服装：驼色针织毛衣、白衬衫、黑色腕表。
- 气质曲线：温柔可靠 → 脆弱示好 → 兴奋鼓励 → 施压 → 冷漠控制。
- 最终场景母版：ComfyUI 输入目录中的 `perfect_lover_v1/references/chenmo_glasses_anchor.png`。

陈默初版尝试固定为无眼镜形象，但 Flux Schnell 在多镜头中随机生成眼镜。为提高连续性，最终把黑色细框眼镜纳入人物档案，并用稳定咖啡镜头二次建立场景母版。

## 3. 视觉与生成方案

### 关键帧

```text
Flux.1 Schnell FP8
→ XLabs Flux IP-Adapter V2
→ XlabsSampler
→ 704×1248 关键帧
```

- 采样：4 steps、CFG 1.0。
- 人物参考强度：0.70–0.95。
- 两位角色分别使用独立人物母版。
- 手机屏幕不承担信息展示：只生成手机背面、侧边或完全隐藏的屏幕。

### 人物视频

```text
关键帧
→ LTX-2.3 22B distilled FP8 scaled I2V
→ 单镜头单一 Hero Motion
→ 25fps、65帧为主
```

- 第 1、2 镜首次生成使用 97 帧；其余最终采用 65 帧快速档。
- Steps / CFG：8 / 1.0。
- I2V 首帧约束：常规镜头 0.95；高风险手机重试 0.97–0.98。
- 相机固定，不生成自动推拉摇移。
- 口部仅为自然说话微动，不是逐音素精确唇形同步。

### 对白和后期

- 林小雨：`zh-CN-XiaoyiNeural`。
- 陈默：`zh-CN-YunxiNeural`。
- 没有旁白音轨。
- 对白字幕每行约 16 个汉字，自动换行。
- 金额、伪造收益、照片来源、高风险账户和举报结果均由 ASS 确定性文字层生成。
- 场景补时使用 `video_fit_mode: hold_last`：视频播放一次后保持末帧，绝不循环回首帧。

## 4. 手机与界面安全规则

- AI 视频中的手机显示面不得朝向镜头。
- 不让扩散模型生成聊天记录、银行界面、收益页或中文。
- 第 12 镜完全取消手机，只用钱包和笔记本表达全部存款。
- 第 15 镜仅保留一部背面手机和一台屏幕背向镜头的笔记本。
- 第 18 镜手机背面始终朝向镜头。
- 所有准确数字和文字均在后期叠加。

## 5. 重试与淘汰记录

| 镜头 | 初版问题 | 最终处理 |
|---|---|---|
| 02 | 咖啡杯镜头多出第三只手 | 杯子和双手固定，只动眼神与嘴角 |
| 09 | 小额转账后手机离开画面 | 手机固定胸前，只做极小食指动作 |
| 12 | 凭空生成正面手机 | 取消手机，只保留钱包和笔记本 |
| 14 | 手机滑出画面 | 取消点击，只做眼神侧移 |
| 15 | 生成第二部手机并露出屏幕 | 一部手机与一台笔记本固定不动 |
| 18 | 手机翻成正面 | 高首帧约束，手机背面全程可见 |

废片保存在 `video/rejected`，最终成片未使用这些版本。

## 6. 最终交付

| 文件 | 路径 |
|---|---|
| 推荐成片 | `data/qa/perfect_lover_pig_butchering_v1/final/perfect_lover_captioned.mp4` |
| 无字幕母版 | `data/qa/perfect_lover_pig_butchering_v1/final/perfect_lover_raw.mp4` |
| 字幕源文件 | `data/qa/perfect_lover_pig_butchering_v1/final/perfect_lover_captioned.ass` |
| 自动质量报告 | `data/qa/perfect_lover_pig_butchering_v1/final/perfect_lover_captioned.quality.json` |
| 最终字幕抽帧表 | `data/qa/perfect_lover_pig_butchering_v1/final/final_caption_wrap_contact.png` |
| 人物与镜头提示词 | `data/qa/perfect_lover_pig_butchering_v1/project.json` |
| 对白与时间线清单 | `data/qa/perfect_lover_pig_butchering_v1/story_video.json` |
| ComfyUI API 工作流 | `data/qa/perfect_lover_pig_butchering_v1/workflows` 和 `video/workflows` |

## 7. 验收

- 成片：1080×1920、30fps、170.9 秒。
- 视频：H.264、yuv420p、BT.709。
- 音频：AAC。
- 发布质量门：通过，`issues` 为空。
- 成片 SHA-256：`335330DF585E2957513E24B5F6F2F1F22A9D250AF533823897C69AB65BD6771C`。
- 对四个长对白补时区间抽帧比较，平均像素差为 0.79–1.12，属于 H.264 编码波动；未出现回到首帧或分段重复。
- 最终接触表中未发现手机正面、第二部手机、多余手或越界字幕。

## 8. 后续可替换内容

复用时主要替换：

1. `project.json` 中的人物档案、关键帧提示词和 Hero Motion。
2. `story_video.json` 中的对白和镜头顺序。
3. `callouts.json` 中的确定性文字卡。

人物母版、Flux IP-Adapter、LTX I2V、`hold_last` 合成和字幕压制可以继续复用。更换画风时应重新生成人物母版和关键帧，但镜头结构、对白合成与手机安全规则不需要重写。
