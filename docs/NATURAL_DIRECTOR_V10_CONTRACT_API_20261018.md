# 自然导演 v10 纯合同接口

MiniMax只写完整自然文本，不输出JSON或工具，不接收历史失败大JSON；DeepSeek忠实整理并审核，再对照全源文、完整稿、自然导演及全部最终SDK请求做最终整包审核。所有API无凭据、网络、派发或媒体审查；共享放行门会重读本地原生证据文件。旧v8/v9保持。

模块：`src/content_factory/natural_director_contracts_v10.py`。

```python
quality_policy() -> dict
build_natural_director_payload(source_text, draft_text, *, brief, policy=None, feedback=None, max_tokens=12000) -> {messages, parameters}
build_extract_review_payload(source_text, draft_text, natural_director_text, *, brief, policy=None, max_tokens=16000) -> {messages, parameters}
parse_extract_review(text, *, source_binding, draft_binding, materials, native_response_ref, artifact_id='extract-001') -> dict
compile_video_requests(extract) -> dict
build_final_review_payload(source_text, draft_text, natural_director_text, extract, *, brief, policy=None, max_tokens=12000) -> {messages, parameters}
parse_final_review(text, *, source_binding, draft_binding, materials, native_response_ref, artifact_id='final-review-001') -> dict
make_handoff(natural_director_text, extract, final_review, *, source_binding, draft_binding, brief, native_evidence) -> dict
validate_handoff_for_dispatch(handoff) -> dict
verify_native_evidence(natural_director_text, extract, final_review, *, source_binding, draft_binding, brief, native_evidence) -> dict
```

`materials`必须直接来自对应已保存原生请求最后一条user.content解析出的完整对象。运行器验证精确system prompt、来源/完整稿、冻结brief、SDK请求、完整响应/用量/stop和实际文件绑定，再重建parse结果，不可信任助手手写通过旗标。

提取原生对象：`verdict(pass/revise)`、`whole_text_reviewed(bool)`、`faithful_to_natural(bool)`、`summary(str)`、`checks(dict，九维每维具体结论)`、`issues(list)`、`segments(list)`。每段只需`segment_id`、`duration_seconds`(4–15整数)、`prompt`(忠实完整的自然语言实际表演提示词)、`source_notes`(仅本地来源定位说明)。可保留额外原生信息，但不将证据字段拼入视频prompt。问题含severity(minor/major/blocking)、location、evidence、suggestion；可含responsibility_layer。revise可没有segments。pass必须全文/忠实true、九维齐全，无major/blocking，并通过硬时长与ID覆盖合同。程序不以字数判断节奏或猜测自然导演缺失内容。

最终原生审核：`verdict`、`whole_text_reviewed`、`all_requests_reviewed`、`summary`、`checks`(九维)、`issues`。最终审核材料内`video_requests`由同一SDK编译器取得。最终pass必须完整/全部请求审完，无major/blocking，最终artifact绑定材料整体SHA和全部请求SHA。

两个parse产物保留完整原生JSON文本及解析对象，附程序来源/原稿/自然导演/brief/规范/请求指纹。`compile_video_requests`返回`schema,quality_policy,provider,model,requests,sha256`等；每request含`segment_id,duration_seconds,prompt,request,request_sha256`。按实际SDK构造，不固定15秒，不取第一条表演，不改台词或秒数。

`native_evidence`由运行器保存原生请求/响应文件绑定及已验证证据，包含`verified=True`、`source_binding`、`draft_binding`、`natural_director_sha256`、`extract_native_response_ref`、`final_native_response_ref`、`video_requests_sha256`、冻结`protocol(writer/director)`及`stages`。`stages`三个键是`natural_director`、`extract_review`、`final_review`，每项含`request`、`response`实际绝对路径/bytes/SHA256绑定。共享`make_handoff`与`validate_handoff_for_dispatch`都实际重读文件，核对原生模型、结束/用量、精确system、同源全文/简报/自然稿、完整提取与全部真实SDK请求，再原样重建两个parse产物。手写`verified=True`或hash而没有实际文件不能放行；文件变更立即拒绝。本地文件一致性不是服务密码学签名。交接与派发检查只证明文本和请求一致，`production_dispatch_allowed=False`，媒体和发布另有授权。

DeepSeek两个builder的`parameters.response_format={"type":"json_object"}`，与实际独立v10客户端HTTP一致；MiniMax不附此参数。JSON Output不证明内容正确，明确截断/未知仍停止，不补JSON或改原判词。

本轮5+5轮、原总20calls/500000和累计用量由运行器锁与持久账本执行；本模块不扩预算、不做运输自动重试。
