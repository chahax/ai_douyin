"""Paid-call isolation checks for the source-bound legal opening."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from scripts import run_legal_opening_seedance_v1 as runner
from src.content_factory.creative_segment_execution import read
from src.content_factory.seedance_client import SeedanceAPIError, SeedanceClient, SeedanceConfig

class FakeClient:
    def __init__(self, error=None, tail=True):
        self.config=SimpleNamespace(provider="ark_api", model="doubao-seedance-2-0-mini-260615")
        self.created=0
        self.queried=[]
        self.error=error
        self.tail=tail
    def build_task_payload(self, prompt, **kw):
        with SeedanceClient(SeedanceConfig(api_key="offline-test", provider="ark_api",
                             model=self.config.model), record_calls=False) as c:
            return c.build_task_payload(prompt, **kw)
    def create_task(self, payload):
        self.created+=1
        if self.error:
            raise self.error
        return {"id":"offline-legal-task"}
    def get_task(self, task_id):
        self.queried.append(task_id)
        return {"id":task_id,"status":"succeeded",
                "content":{"last_frame_url":"https://example.invalid/original.png"} if self.tail else {}}
    def download_video(self, task, path):
        path.write_bytes(b"offline-video-bytes")
        return path
    def download_last_frame(self, task, path):
        path.write_bytes(b"offline-original-tail-bytes")
        return path

@pytest.fixture
def reserved(tmp_path):
    with patch("src.content_factory.creative_segment_execution.media_reservation_root",
               return_value=tmp_path/"story_budget"):
        yield tmp_path/"candidate"

def prepared(out, client):
    runner.execute("prepare", client, out)
    return client

def test_same_receipt_cannot_dispatch_twice(reserved):
    c=prepared(reserved,FakeClient())
    runner.execute("submit",c,reserved)
    with pytest.raises(FileExistsError):
        runner.execute("submit",c,reserved)
    assert c.created==1

def test_directory_change_does_not_bypass_unresolved_story_segment(reserved):
    c=prepared(reserved,FakeClient())
    runner.execute("submit",c,reserved)
    second=reserved.parent/"changed_directory"
    runner.execute("prepare",c,second)
    with pytest.raises(ValueError,match="unresolved"):
        runner.execute("submit",c,second)
    assert c.created==1
    assert read(second/"receipt.json")["status"]=="blocked_before_submit"
    assert read(reserved.parent/"story_budget"/"budget.json")["budget_reset_supported"] is False

def test_unknown_without_id_never_redispatched(reserved):
    c=prepared(reserved,FakeClient(error=RuntimeError("connection lost after write")))
    with pytest.raises(RuntimeError):
        runner.execute("submit",c,reserved)
    assert read(reserved/"receipt.json")["technical_status"]=="unknown"
    with pytest.raises(ValueError,match="never resubmit"):
        runner.execute("query",c,reserved)
    assert c.created==1
    assert c.queried==[]

def test_http_rejection_is_known_failed_not_unknown(reserved):
    c=prepared(reserved,FakeClient(error=SeedanceAPIError("rejected",status_code=400,error_code="InvalidParameter")))
    with pytest.raises(SeedanceAPIError):
        runner.execute("submit",c,reserved)
    r=read(reserved/"receipt.json")
    assert r["status"]=="request_rejected" and r["technical_status"]=="failed"
    assert c.created==1

@pytest.mark.parametrize("tail",[True,False])
def test_saved_candidate_stays_for_human_review_and_queries_original_id(reserved,tail):
    c=prepared(reserved,FakeClient(tail=tail))
    runner.execute("submit",c,reserved)
    runner.execute("query",c,reserved)
    runner.execute("query",c,reserved)
    r=read(reserved/"receipt.json")
    assert r["content_status"]=="awaiting_human_review"
    assert r["human_decision"] is None and r["next_segment_dispatch_allowed"] is False
    assert c.created==1 and c.queried==["offline-legal-task"]
    if tail:
        assert r["last_frame_source"]=="generation_service_original"
    else:
        assert r["last_frame"] is None and "continuation blocked" in r["tail_status"]

def test_source_plan_mutation_is_blocked_before_dispatch(reserved):
    c=prepared(reserved,FakeClient())
    p=read(reserved/"PLAN.json")
    p["performance_snapshot"]["active_performance"]="invented action"
    (reserved/"PLAN.json").write_text(json.dumps(p,ensure_ascii=False),encoding="utf-8")
    with pytest.raises(ValueError,match="changed"):
        runner.execute("submit",c,reserved)
    assert c.created==0

def test_query_before_submission_cannot_create_task(reserved):
    c=prepared(reserved,FakeClient())
    with pytest.raises(FileNotFoundError):
        runner.execute("query",c,reserved)
    assert c.created==0


def test_saved_receipt_can_bind_explicit_user_approval(reserved):
    from src.content_factory.media_review_policy import record_user_media_decision, validate_approved_tail
    c=prepared(reserved,FakeClient())
    runner.execute("submit",c,reserved)
    runner.execute("query",c,reserved)
    record_user_media_decision(reserved/"receipt.json","approved","下一段")
    assert validate_approved_tail(reserved/"receipt.human_review.json")["path"]==str((reserved/"SH01.provider_last.png").resolve())
    assert read(reserved/"receipt.json")["content_status"]=="approved"
    assert c.created==1

def test_changed_stored_request_cannot_receive_approval(reserved):
    from src.content_factory.media_review_policy import record_user_media_decision
    c=prepared(reserved,FakeClient())
    runner.execute("submit",c,reserved)
    runner.execute("query",c,reserved)
    r=read(reserved/"receipt.json")
    r["request"]["duration"]=15
    (reserved/"receipt.json").write_text(json.dumps(r,ensure_ascii=False),encoding="utf-8")
    with pytest.raises(ValueError,match="request changed"):
        record_user_media_decision(reserved/"receipt.json","approved","下一段")
    assert not (reserved/"receipt.human_review.json").exists()
