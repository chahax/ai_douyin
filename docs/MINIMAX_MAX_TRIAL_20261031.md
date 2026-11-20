# 最新 MiniMax 最高强度实测（2026-10-31）

结论：声音阶段未通过；已对失败原稿独立审查，未进入画面生成，不能称完整剧本测试通过。

## 实际设置和范围

官方模型说明：https://platform.minimax.io/docs/guides/text-generation 。本次查验最新 MiniMax-M3.1-Flash，最高 reasoning_effort=max。两次原生 REQUEST 均核实该参数，max_completion_tokens=32768。模型名称未换，旧试验为 medium；输出上限也由16384提高，非严格单因素对照。

完整第19章前情、第20—21章目标，241原段。本次重新生成声音，没有复用321旧声音。328输出120项，329只审核这份失败声音原稿；没有画面请求、完整剧本、视频或发布。

## 结果

- 328：29726 tokens，含7903 reasoning tokens；完整已知返回，因 audio_not_original_span 停止。120项仅发现一处逐字差异：CH20-P052原文“似曾相见”改为“似曾相识”。这是一处轻微措辞改写，不能夸大为剧情错误；现有原句合同仍会阻断。
- 第53项“姐姐最好看了”指定叶西决，当前输入依据不足。第1项“嗯嗯”改为六兄妹群体，仍比原文“几个孩子”的范围更确定，未证明解决署名问题。
- 329：27965 tokens，含13622 reasoning tokens。抓到第53项定名无据，但误称全部逐字一致，漏了程序已查出的改词。建议替换为哥哥群体也缺充分依据。将部分可由画面表达的必要信息列为声音遗漏，尚不能作为整稿缺失结论。
- 无画面候选，本轮无法判断公交/到站位置、系统后对视、便利店地点是否改善。

## 工程与验收

入口支持显式 effort/max_tokens，完整新轮准备清除继承的 picture_only/review_only 标记；默认参数保持原样。相关12项程序测试通过，证据 data/qa/max_round_20261031.xml。这些测试验证参数与准备流程，不是文本质量通过。

新调用2次共57691已知tokens，累计329次/6232396已知tokens；pending=null。计划窗口327→330未用最后1次，试验结束，不为凑额度续跑。原始失败与历史未知记录保留；没有手改候选、默认迁移或服务重启。

更高思考强度本样本仍未消除署名推断和审核漏报。字面比对应继续由程序处理；语义归属与音画覆盖须分别核对。不能从这一次推断max总体优劣。

## 证据

- data/corpus_production_trials/20261031_minimax_max_round：原始请求、回执、120项原生声音、ALL_SPAN_DIFFERENCES.json、失败状态。
- data/corpus_production_trials/20261031_minimax_max_audio_review：原始请求、回执、review.md、PRIMARY_REVIEW.json、ACCEPTANCE.json。
