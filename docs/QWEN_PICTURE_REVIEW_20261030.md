# 实际输入核对、地点前后提示补充与本机Qwen独立审查

## 实际输入存在

读取已冻结的CALL_324.json，而不是依据当前代码推测。user顶层字段是source、audio_items、output_schema。

| 位置 | 实际内容 |
|---|---|
| source.chapters第19章 | role=context_only，77段、正文2035字符 |
| source.chapters第20章 | role=target，76段、正文2018字符 |
| source.chapters第21章 | role=target，88段、正文2037字符 |
| audio_items | 94项，含audio_id/source_id/kind/speaker/text/evidence_ids |

context_only不是独立顶层字段，也不是占位符；它是章节role的值。audio_items不是只有ID，模型能读到每句内容和署名；“只引用ID”约束的是画面节点的输出，程序之后按ID展开声音原文。

原文与INPUT.json一致。完整原请求见 [CALL_324.json](../data/corpus_production_trials/20261030_picture_channels_v2/CALL_324.json)，核对数据见 [ACTUAL_INPUT_VERIFICATION.json](../data/corpus_production_trials/20261030_qwen_independent_review/ACTUAL_INPUT_VERIFICATION.json)。

## 已补充的地点要求

> 逐场结合前后原文核对地点：前一场最后实际发生的行动和结束地点是什么，当前场从哪里开始，哪些动作发生在移动前、途中、抵达后，结束时人物又在哪里；下一场从这个已发生的结束状态承接。原文出现到站、出门、进店、回来等转折时，保留转折前后动作各自所属的位置。允许省略无信息的移动过程或合并场次，但合场文字必须明确各阶段的位置，不能把后一地点的动作放进前一地点。这里只要求清楚表达地点前后的内容，不要求额外生成状态表或逐步分析说明。

改于isolated_nodes.PICTURE。完整新业务提示保存为 [PICTURE_PROMPT_UPDATED.md](../data/corpus_production_trials/20261030_qwen_independent_review/PICTURE_PROMPT_UPDATED.md)。本轮没有调用MiniMax重生成，因此不能宣称新地点提示已真实解决错误。原候选和旧请求不变。

## Qwen实测

当前本机Ollama只有qwen2.5:7b，7.6B/Q4_K_M；使用已安装模型，无下载、无云模型调用。模型digest已冻结在MODEL.json。通过已有local_screenplay_lab.invoke本地接口审查一次，num_ctx=32768、num_predict=6144、temperature=0.5、seed=42，结束后按keep_alive=0释放模型。

发送完整第19章前情、第20—21章正文（241段），以及原12场候选的完整画面和94条已展开声音。不发送旧审核结果、主助手错误清单或预期答案；三个已知问题单独存在EXPECTED_FINDINGS_NOT_SENT.json。用户已经接受的“融创乐园附近便利店”作为本稿制作选择传给审查员，避免重复报警。

这是一次通用内容审查：核对事件因果、动作场所、人物回应、声音类型/署名和必要信息遗漏。不是只摘三处错误让模型确认，也没有要求模型重写。

20项相关回归通过，报告data/qa/qwen_review_prompt_20261030.xml。这是程序验证，不是语义结果。

返回done=true、done_reason=stop，实际12542输入tokens、1028输出tokens，总13570tokens，约31.425秒；没有输出截断证据。发送内容与冻结输入逐项一致，完整源段和候选均保留。

## 主助手核对结果

三个预先冻结的已知问题均未发现：

1. 到站后牵手行动被放在公交车内。
2. 系统提示后的转头、对视、微笑遗漏。
3. A001“嗯嗯”无依据署叶东。

模型还误报：

- 把候选“对白[A043|叶嫣儿|CH21-P006]：好看吗？哥哥。”引用成叶寻。
- 将原文没有程序声音ID、未署名对白保留待核，当成实质错误；混淆声音索引与原文证据。
- 声称没有表现苏墨骄傲表情，而原场10明确写“苏墨回以微笑，笑容里满是骄傲”；该建议还重复出现。

结论：本次独立审查0/3命中且存在误报，不接受它作为自动验收依据。不能由一次样本推断全部Qwen型号均无效，也不能因为模型写“总体忠实”就放行原稿。当前只完成提示补充和一次本地审查测试，未修原稿、未迁移生产审核器。

- [Qwen原始审查](../data/corpus_production_trials/20261030_qwen_independent_review/review/OUTPUT.md)
- [实际发送请求](../data/corpus_production_trials/20261030_qwen_independent_review/review/REQUEST.json)
- [主助手逐项核对](../data/corpus_production_trials/20261030_qwen_independent_review/PRIMARY_REVIEW.json)
- [验收记录](../data/corpus_production_trials/20261030_qwen_independent_review/ACCEPTANCE.json)
