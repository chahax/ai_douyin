"""Independent novel adapter: full model-authored revisions, unchanged source locks.

The base stage implementation is reused with an isolated globals dictionary. This
lets its *recorded and sent* prompt/schema agree without mutating the legacy
module's process-wide dictionaries (other tasks may run in this process).
"""
from __future__ import annotations

from copy import deepcopy
from types import FunctionType

from .creative_workflow import CreativeWorkflow
from .creative_workflow_roles import RoleResponseError, RoleResult

VERSION = "account_novel_full_script/v1"
FULL_REVISION_PROMPT = """本次为小说完整剧本返修。按 issues 和 previous_script 重新提交完整剧本对象，
包含 title、premise、selected_candidate_id、duration_seconds、beats、screenplay_markdown。
不返回 replace_beats 或补丁，不拼接旧稿。可以调整所有节拍的数量、编号、顺序、动作和时长，
但不能更换已选故事身份、selected_source、原文对白及事件因果。原文是人物、剧情和对白唯一来源；
审核 location 只是问题定位，不是局部修改边界。明确世界框架、人物关系与目标、空间前情；
逐拍写时间地点、在场人物动作、神情视线、对白反应与段首尾状态，动作与对白自然交叠。
提交完整 beats 旧接口结构，不用 events。新版将全文复审，导演分镜从完整新稿重建。
"""


class _PreserveResponse:
    """Keep the native envelope which the legacy role metadata wrapper drops."""

    def __init__(self, client):
        self.client = client
        self.last_result = None

    def call(self, *args, **kwargs):
        self.last_result = None
        self.last_result = self.client.call(*args, **kwargs)
        return self.last_result


class AccountNovelWorkflow(CreativeWorkflow):
    """New entry only; neither original-event nor v6 policy is impersonated."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clients = _PreserveResponse(self.clients)

    def _call_model(self, role, messages, **kwargs):
        callback = getattr(self, "pre_dispatch_validator", None)
        if callback is not None:
            try:
                callback()
            except Exception as exc:
                exc.provider_dispatch_started = False
                raise
        try:
            result = super()._call_model(role, messages, **kwargs)
        except RoleResponseError as exc:
            tokens = exc.response_metadata.get("total_tokens")
            if type(tokens) is not int or tokens < 0:
                self.state["usage_status"] = "unknown"
                self.state["reported_tokens_is_known_total"] = False
            raise
        result = RoleResult(result.text, result.metadata, self.clients.last_result.response_payload)
        metadata = result.metadata
        if type(metadata.get("total_tokens")) is not int or metadata["total_tokens"] < 0:
            self.state["usage_status"] = "unknown"
            self.state["reported_tokens_is_known_total"] = False
            raise RoleResponseError("模型响应用量未知，保留原结果并停止，不重新派发",
                                    {**metadata, "response_fault_code": "USAGE_UNKNOWN"},
                                    response_text=result.text, response_payload=result.response_payload)
        if metadata.get("finish_reason") not in ("stop", "tool_calls"):
            raise RoleResponseError("模型响应没有明确完成标识，保留原结果并停止",
                                    {**metadata, "response_fault_code": "COMPLETION_UNKNOWN"},
                                    response_text=result.text, response_payload=result.response_payload)
        return result

    def _save(self):
        if self.state:
            expected = {"version": VERSION, "mode": "full_script", "prompt": FULL_REVISION_PROMPT}
            bound = self.state.get("account_novel_adapter_binding")
            if bound is not None and bound != expected:
                raise RuntimeError("小说整稿适配绑定变化，停止恢复")
            existing = self.state.get("script_revision_binding")
            if existing is not None and existing != expected:
                raise RuntimeError("小说整稿返修模式不能迁移旧任务")
            self.state["account_novel_adapter_binding"] = expected
            self.state["script_revision_binding"] = expected
            self.state["assistant_review_required"] = True
        if self.state.get("usage_status") == "unknown":
            from .creative_state_store import commit_state
            self.state["known_reported_tokens"] = self._reported_tokens()
            self.state["reported_tokens"] = None
            commit_state(self.run_dir, self.state)
        else:
            super()._save()

    def _stage_impl(self, name, role, payload, validator):
        base = CreativeWorkflow._stage_impl
        isolated = dict(base.__globals__)
        prompts = deepcopy(isolated["PROMPTS"])
        schemas = deepcopy(isolated["WRITER_TOOL_SCHEMAS"])
        # Starting from the full writer prompt keeps novel quotation/source
        # constraints while removing the conflicting local-patch instructions.
        prompts["writer_revise"] = prompts["writer_script"] + "\n" + FULL_REVISION_PROMPT
        schemas["writer_revise"] = deepcopy(schemas["writer_script"])
        isolated.update(PROMPTS=prompts, WRITER_TOOL_SCHEMAS=schemas)
        adapted = FunctionType(base.__code__, isolated, base.__name__, base.__defaults__, base.__closure__)
        adapted.__kwdefaults__ = base.__kwdefaults__
        return adapted(self, name, role, payload, validator)
