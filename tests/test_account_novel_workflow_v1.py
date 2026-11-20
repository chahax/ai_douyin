from copy import deepcopy
import json

from src.content_factory.account_novel_workflow_v1 import AccountNovelWorkflow
from src.content_factory.creative_workflow import CREATE_REVIEW_PROFILE, _hash
from src.content_factory.creative_workflow_contract import PROMPTS, WRITER_TOOL_SCHEMAS
from tests.test_creative_workflow import FakeClients, _answers, _bundle


def test_whole_novel_revision_sent_as_complete_schema_and_all_beats_adopted(tmp_path):
    answers = _answers()
    initial = deepcopy(answers[2])
    updated = deepcopy(initial)
    updated["premise"] = "新版两人通过解释消除误会"
    updated["beats"][0]["id"] = "N01"
    updated["beats"][1]["id"] = "N02"
    updated["beats"][1]["before"] = "听见解释后紧张地看向对方"
    shots = deepcopy(answers[3])
    for shot, beat in zip(shots["shots"], updated["beats"]):
        shot["beat_id"] = beat["id"]
    failed = {"story_preserved": False, "issues": [{"owner": "writer", "location": "B01",
              "evidence": "迟疑", "impact": "人物反应不清楚", "proposal": "完整返修表演", "severity": "major"}],
              "calibration_focus": []}
    clients = FakeClients([*answers[:4], failed, updated, shots, answers[4]])
    before_prompts, before_schemas = deepcopy(PROMPTS), deepcopy(WRITER_TOOL_SCHEMAS)
    run = tmp_path / "run"
    workflow = AccountNovelWorkflow(run, clients=clients, model_profile=CREATE_REVIEW_PROFILE)
    state = workflow.run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    script = json.loads((run / "SCREENPLAY.json").read_text(encoding="utf-8"))
    assert script["beats"] == updated["beats"]
    assert script["premise"] == updated["premise"]
    rec = json.loads((run / "writer_revise__01.json").read_text(encoding="utf-8"))
    prompt = rec["request"]["messages"][0]["content"]
    assert "本次为小说完整剧本返修" in prompt
    assert "其他拍逐字保留原稿" not in prompt
    assert "只返回 {replace_beats" not in prompt
    assert rec["request"]["tool_schema_sha256"] == _hash(WRITER_TOOL_SCHEMAS["writer_script"])
    actual = [kw["structured_schema"] for (_, messages), kw in zip(clients.calls, clients.call_kwargs)
              if "本次为小说完整剧本返修" in messages[0]["content"]]
    assert actual == [WRITER_TOOL_SCHEMAS["writer_script"]]
    payload = json.loads(rec["request"]["messages"][1]["content"])
    assert payload["revision_mode"] == "full_script"
    adopted = json.loads((run / "writer_revise__01__affected_projection.json").read_text(encoding="utf-8"))
    assert adopted["schema"] == "creative_writer_full_revision_adoption/v1"
    assert adopted["ignored_beat_ids"] == []
    director = json.loads((run / "director_shots__full_revision_joint_01.json").read_text(encoding="utf-8"))
    target = json.loads(director["request"]["messages"][1]["content"])
    assert target["script"]["beats"] == updated["beats"]
    assert "previous_shots" not in target
    review = json.loads((run / "writer_check__01.json").read_text(encoding="utf-8"))
    review_target = json.loads(review["request"]["messages"][1]["content"])
    assert review_target["script"]["beats"] == updated["beats"]
    assert PROMPTS == before_prompts and WRITER_TOOL_SCHEMAS == before_schemas


def test_shared_content_revision_limit_stops_at_two_complete_new_scripts(tmp_path):
    answers = _answers()
    def issue(location):
        return {"story_preserved": False, "issues": [{"owner": "writer", "location": location,
                "evidence": "迟疑", "impact": "人物反应不清楚", "proposal": "完整返修表演", "severity": "major"}],
                "calibration_focus": []}
    responses = [*answers[:4], issue("B01")]
    for number in (1, 2):
        script = deepcopy(answers[2])
        shots = deepcopy(answers[3])
        for index, beat in enumerate(script["beats"]):
            beat["id"] = f"N{number}{index}"
            shots["shots"][index]["beat_id"] = beat["id"]
        responses += [script, shots, issue(script["beats"][0]["id"])]
    clients = FakeClients(responses)
    run = tmp_path / "run"
    state = AccountNovelWorkflow(run, clients=clients, model_profile=CREATE_REVIEW_PROFILE,
                                max_revisions=2).run(_bundle(tmp_path))
    assert state["status"] == "needs_revision"
    assert state["revision_rounds"] == 2
    assert len(list(run.glob("writer_revise__[0-9][0-9].json"))) == 2
    assert not (run / "MEDIA_HANDOFF.json").exists()
