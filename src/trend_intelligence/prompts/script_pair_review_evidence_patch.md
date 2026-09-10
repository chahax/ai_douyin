# 仅修正审核报告中已定位的原文引文

你收到同一剧本、证据和父审核报告，以及程序校验定位的 allowed_paths 和 evidence_targets。本轮只修引文复制错误，不重新编写剧本或整份报告。

只返回一个合法 JSON 对象，键集合恰好等于 allowed_paths，每个值是该路径完整的替换引文字符串。路径必须原样带开头 `/`，不得补字段、改路径、返回整稿或 Markdown。不得使用重复 JSON 键。原文中的英文双引号必须按 JSON 转义。

逐项对照 evidence_targets.source_text 和 required_match：full 要求全文逐字一致，contiguous_excerpt 要求逐字连续的真实原文；不得跳字、同义改写或拼接。静默对白仅在 empty_allowed=true 且原文为空时允许空字符串。原文字词和标点都属于引文。

所有 checks、issues、summary、findings、assessment、notes、decision 及未列出的字段都冻结。你必须核对引文与父报告判断的关系，不能另挑一句话只为支持已写好的结论。如果真实引文会动摇或改变原说明、发现或通过/失败判断，或者必须改未允许字段才诚实，应停止补丁并仅返回 {"full_review_required":"具体说明哪个原结论需要重新审核以及原因"}。这会要求完整复审，不能把它解释成通过；不要与引文路径混在同一对象。

修正引文不代表内容审核通过；程序仍对合并报告执行完整原审核门禁。禁止把原来的实质失败或未解决问题改成通过。
