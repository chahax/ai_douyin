# B版逐句说话人与心声执行编译 v26

这是独立纯CPU节点。它只消费已确定的剧本、人物参考与显式speaker/mode记录，在每句原引号前插入具名声画执行说明；不调用编剧模型、不猜说话人、不改A版或运行中的v24执行器。

## 为什么新增

A版S01已实际检出三句原台词，但第二句期间弟弟仍在动嘴。ASR文字一致不等于说话人与口型一致。仅在开头写人物名字和Picture对应关系不够，因此B版将该对应关系紧贴每句台词重申，同时呈现本人的面部和原有动作、开口/闭口演出。r2不再把对白统一收成纯脸部近景，避免遮住跪下或递接动作。

该设计是待验证的生成条件改进，不是已经通过真实视频验收，也不能保证模型服从。

## 输入合同

通用 `spatial_speech_grounding_spec/v26`：

- `source_prompt`：完整原提示词path/SHA；原CRLF、动作、时间线、原引号标点全部保留。
- `actors`：actor_id→具名人物、实际参考图片path/SHA、Picture序号、衣服/身份描述；字段不接受额外引号示例。
- 每句结构化记录：`quote_index`（0基原引号出现位置）、`quote_sha256`（包含左右引号的完整原句UTF8 SHA）、`speaker_id`、`mode`（dialogue或inner）。
- `speaker_map_authority`：说明speaker/mode来自哪个明确可信的上游记录。

未知人物、缺失/未知mode、SHA不匹配、重复或越界索引、原文出现位置未完整覆盖均拒绝，不按最后出现的人名或默认男童声猜测。原文相同台词重复出现时保留独立出现位置，不用全局replace误改多句。

本次显式映射来自主代理任务，专门绑定INPUTS中已冻结的4份精确源SHA：

| 段 | 各原引号依次归属 |
|---|---|
| S01 | 叶西决对白、叶南对白、叶西决对白 |
| S02 | 苏墨心声、叶西决对白 |
| S03 | 苏墨心声、叶西决心声 |
| S04 | 苏墨对白、叶西决对白、苏墨心声 |

S02原句“叶西决把面包往苏墨面前递”没有被按最后人名误署给苏墨；由显式quote occurrence记录确定为叶西决。此书特定的trusted factory只接受已知4份源SHA；通用API仍可接上游明确提交的其他源/人物/声画记录。

## 输出方式

对白原引号前插：

```text
镜头明确呈现<Picture 2>中穿灰色翻领短袖上衣和深色长裤的哥哥叶南的面部及本段原有动作，由叶南本人开口说出本句台词：
```

心声原引号前插：

```text
镜头明确呈现<Picture 3>中穿米色圆领短袖上衣和灰色短裤的弟弟叶西决的面部及本段原有动作。叶西决本人嘴唇闭合，原段中的动作和表情照常演出。本句为叶西决的内心独白，以叶西决的画外音呈现：
```

上述说明不复制台词，不添加“禁止生成XX”、工程标签、示例编号或统一固定机位。原来的听者反应、动作、神情与时长句保留。r2的工程样式名称只写在AUDIT的instruction_style，不进入模型正文。旧r1产物保持冻结，兼容验证和可逆恢复，不覆盖成新措辞。

每个插入记录同时保存原字符/UTF8字节offset、编译后的插入区间、speaker/mode和原句SHA；正向重放可还原编译稿，按区间逆向移除后必须逐字节恢复原稿。AUDIT核对原引号顺序和计数完全相同，本次共10处，一处也不增删。

## CLI与实际CPU产物

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_speech_grounding_v26.py --trusted-inputs data/video_generation/spatial_minute_experiments_20261107_v1/INPUTS.json --out data/video_generation/spatial_minute_experiments_20261107_v1/B_speech_r2
```

通用方式改用 `--spec <json>`；两种入口不可同时使用。

实际已执行上述真实4源CPU prepare，输出新 `B_speech_r2/INPUT_SPEC.json`、`S01..S04.prompt.txt`、逐段audit、`AUDIT.json`和`READING.md`。原B_speech和r1源码/测试/XML/验收（before_plain_actor_action_r2）保持。全部是候选输入、0模型调用、production_approved=false。B fullspec尚未创建，需主代理审看完整A后选用。

## 验证范围

最新35项CPU测试包括源SHA/原音频引用SHA、外来人物/缺mode、重复/漏引号索引、相同原句多次出现、CRLF及UTF8位置、可逆回放、审计篡改、严格书籍源版本、实际4份production源prepare与真实CLI黑盒；并增加无工程标签、面部与原动作同时呈现、不统一锁纯脸部、S04跪下和跑出保留、原r1实际产物兼容验证。测试只验证编译与输入合同，不证明H3已经正确分配说话人。有效结果以 `data/qa/spatial_v26/speech_r2_final.xml` 为准，不与旧32或setup错误轮累加。
