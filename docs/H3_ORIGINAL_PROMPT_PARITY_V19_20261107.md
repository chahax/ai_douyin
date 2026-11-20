# 原Seedance提示词与本地H3一分钟对照

本次是独立对照试验：保持2026-11-02 Seedance四段请求中的唯一文本值，改由本地H3生成。不能将结果差异简单归因为“相同模型设置”：Seedance原片为720×1280，本次H3原生736×1312；两条模型路线各自处理构图和动作。

入口：`scripts/run_h3_seedance_prompt_parity_v19.py`。实现：`src/content_factory/visual_h3_prompt_parity_v19.py`。新根：`data/video_generation/h3_seedance_prompt_parity_60s_20261107_v1`。不修改旧任务、原暂停、后台服务、账号或发布流程。

## 固定输入

- 提示词来自`data/video_generation/six_children_seedance_60s_20261102_trusted/segments/S01`至`S04/REQUEST.actual.json`中的唯一`content[type=text].text`，分别655、644、679、660字符。与`PROMPT.txt`按文本读取后的内容一致；原文件CRLF字节SHA与实际UTF8字符串SHA分开记录。
- 不经模型重写、不翻译、不加包装或相机限制。图中的`condition.inputs.prompt`就是原JSON文本值。
- S01使用同一Seedream开场原件，SHA为`7fd7a5ab3af9f3ce164077fec92fc89159c68d5b0001f8d85f343ceca00a88e7`。
- S02—S04仅用本次上一段H3实际原生`last`保存节点的PNG原字节；绑定上段结果、原生任务ID和图像SHA。没有引用Seedance尾帧，也没有合成新的组合首图。
- 四段均仅提供`first_frame`，省略`last_frame/ref_images`。原生736×1312、24fps、362帧、12步、H3内嵌音频。无裁剪、放大或内容失败后自动重拍。
- 工作底图取自已知完成的F10原生工作流，以原history图和结果做CPU等价核对；仅允许既有两种Comfy数值输入int→float的等值转换。

## 操作

```powershell
# CPU准备与本地只读状态
.venv/Scripts/python.exe -B scripts/run_h3_seedance_prompt_parity_v19.py prepare
.venv/Scripts/python.exe -B scripts/run_h3_seedance_prompt_parity_v19.py status

# 真实媒体派发；只由主代理在原授权范围内启动
.venv/Scripts/python.exe -B scripts/run_h3_seedance_prompt_parity_v19.py execute --through S01
# 或自动串行四段，四段技术原件齐全后自动CPU合成
.venv/Scripts/python.exe -B scripts/run_h3_seedance_prompt_parity_v19.py execute

# 合成/音画时钟检查可独立重复读取；不产生新媒体模型调用
.venv/Scripts/python.exe -B scripts/run_h3_seedance_prompt_parity_v19.py assemble
.venv/Scripts/python.exe -B scripts/run_h3_seedance_prompt_parity_v19.py qa
```

`--run`仍受到固定独立命名空间限制，不能借此启动旧任务。`--through`指定技术收存停止点。`execute`返回未知、原生失败或暂停时停止，不自动换任务ID。`status`只读取本地文件，不查询服务、不创建文件。

每次POST前取得运行锁、共享GPU锁和服务输入锁，核对服务实际输入/输出目录、严格列表结构的原生queue、模型文件元数据、源文件与原暂停完整SHA。请求和CLAIM先持久保存；原生响应丢失则保留未知，绝不再次POST。已有ID只轮询原history/queue，可在上游变化后继续收存原ID，但不得新提交下一段。`NATIVE_IDS.jsonl`和`job_ids.txt`分别追加原ID并去重。

每段保留REQUEST、CLAIM、RESPONSE、history、原生图等价凭据，以及video/audio/first/last四类原生原件路径和SHA。技术保存不等于内容审核通过；所有结果仍`production_approved=false/publication=false`。

## 合成与检查范围

合成前要求四个不同原生任务ID、四个不同视频SHA/原路径、完整原生成功history、正确原提示词和上段尾帧绑定。分别解码核对362帧，不依据AAC封装时长拼接、不使用fps滤镜补丢帧。

每段视频`trim=end_frame=362`并按`N/24`重建时钟；音频分别解码，48kHz每帧2000样本，按724000样本修正正常priming/padding后串接。原生音画时长差超过0.25秒即阻断，不能静默截掉大段台词。保留每段原元数据和trim/pad样本数，原片与独立音频原件不改。

最终严格1448帧、736×1312、24fps、2896000音频样本、60.333333秒，双轨起点0。QA提供CPU解码/元数据/样本数证据；没有把ASR或视觉模型结果伪装成已运行。实际人物、动作、语言和四段节奏仍由主代理看片比较。后处理不处于下一段POST前置门中。

## CPU验收

`tests/test_visual_h3_prompt_parity_v19.py`覆盖原文逐值传递、两段本次H3尾帧链、Response恢复、未知不重发、原暂停/新暂停、输入冲突、服务路径、共享双锁、history数值等价与非法变更、只读状态、原生ID唯一性和最终音画时钟。另有两路独立CLI进程通过临时HTTP服务验证正常响应与响应丢失，不访问真实8190。

计时素材是明确标注`TIMING_ONLY`的64×80 CPU图案与测试音，验证4×362帧和逐样本PCM边界；不是H3真实产物，不能进入正式原生资格门或写正式最终片。测试报告与最终源码清单在`data/qa/h3_prompt_parity_v19_20261107`。开发代理只做CPU准备和测试，没有实际媒体POST。
