from streamlit.testing.v1 import AppTest
import json

from src.web import creative_workflow_dashboard as page


def _app():
    return AppTest.from_string(
        "from src.web.creative_workflow_dashboard import page_creative_workflow\n"
        "page_creative_workflow()",
        default_timeout=15,
    ).run()


def test_page_novel_route_launches_explicit_new_workflow(tmp_path, monkeypatch):
    novel = tmp_path / "novel.txt"
    novel.write_text("第一章。人物发现秘密后回家。" * 15, encoding="utf-8")
    launches = []
    monkeypatch.setattr(page, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(page.subprocess, "Popen", lambda argv, **kwargs: launches.append(argv))

    app = _app()
    assert not app.exception
    app.text_input[0].set_value("小说试跑")
    app.text_input[2].set_value(str(novel))
    app.button[0].click().run()

    assert not app.exception
    assert len(launches) == 1
    argv = launches[0]
    assert argv[argv.index("--source-driver") + 1] == "novel"
    assert argv[argv.index("--novel") + 1] == str(novel)
    assert "--video" not in argv
    assert "--analysis" not in argv


def test_page_switches_to_independent_video_driver(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"test media")
    analysis = tmp_path / "analysis.md"
    analysis.write_text("原视频 source.mp4。先看门口，再看人物转身。" * 10, encoding="utf-8")
    launches = []
    monkeypatch.setattr(page, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(page.subprocess, "Popen", lambda argv, **kwargs: launches.append(argv))

    app = _app()
    app.selectbox[0].set_value(app.selectbox[0].options[1]).run()
    assert not app.exception
    app.text_input[0].set_value("视频原创试跑")
    app.text_input[2].set_value(str(video))
    app.text_input[3].set_value(str(analysis))
    app.button[0].click().run()

    assert not app.exception
    assert len(launches) == 1
    argv = launches[0]
    assert argv[argv.index("--source-driver") + 1] == "reference_video"
    assert argv[argv.index("--video") + 1] == str(video)
    assert argv[argv.index("--analysis") + 1] == str(analysis)
    assert "--novel" not in argv


def test_page_displays_detached_launch_failure(tmp_path):
    run_dir = tmp_path / "failed"
    run_dir.mkdir()
    (run_dir / "LAUNCH_ERROR.json").write_text(json.dumps({
        "schema": "creative_launch_error/v1", "status": "needs_attention",
        "error": "相同来源与创作焦点已有逻辑任务",
    }, ensure_ascii=False), encoding="utf-8")
    app = _app()
    app.session_state["creative_run_dir"] = str(run_dir)
    app.run()
    assert any("已有逻辑任务" in item.value for item in app.error)


def test_page_can_reopen_saved_run_after_fresh_session(tmp_path, monkeypatch):
    run_dir = tmp_path / "saved_run"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "status": "needs_attention", "source_driver": "novel",
        "last_error": "对白时长不足",
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(page, "RUNS", tmp_path)
    app = _app()
    assert not app.exception
    choices = app.selectbox[1].options
    assert run_dir.name in choices
    app.selectbox[1].set_value(run_dir.name).run()
    assert not app.exception
    assert app.session_state["creative_selected_run"] == str(run_dir)
    assert any("needs_attention" in str(item.value) for item in app.json)


def test_page_resumes_needs_attention_task_with_bound_materials_and_budget(tmp_path, monkeypatch):
    run_dir = tmp_path / "saved_run"
    run_dir.mkdir()
    novel = tmp_path / "source.txt"
    novel.write_text("完整正文" * 100, encoding="utf-8")
    state = {
        "status": "needs_attention", "source_driver": "novel",
        "creative_focus": "同一事件", "max_calls": 20, "max_total_tokens": 500000,
        "max_revisions": 2, "max_contract_repairs": 8,
        "budget_policy_version": "v4_20260923", "calls_started": 6,
    }
    manifest = {
        "schema": "creative_material_manifest/v1", "source_driver": "novel",
        "title": "恢复测试", "files": {"story_source": {"path": str(novel)}},
        "scope": {},
    }
    (run_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8",
    )
    (run_dir / "materials.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8",
    )
    launches = []
    monkeypatch.setattr(page, "RUNS", tmp_path)
    monkeypatch.setattr(page, "_launch_detached", lambda argv: launches.append(argv))
    app = _app()
    app.selectbox[1].set_value(run_dir.name).run()
    resume = next(item for item in app.button if item.label == "恢复同一任务")
    resume.click().run()
    assert not app.exception
    assert len(launches) == 1
    argv = launches[0]
    assert argv[argv.index("--run-dir") + 1] == str(run_dir)
    assert argv[argv.index("--novel") + 1] == str(novel)
    assert argv[argv.index("--focus") + 1] == "同一事件"
    assert argv[argv.index("--max-contract-repairs") + 1] == "8"
    assert "--video" not in argv
    assert any("调用次数不会重置" in item.value for item in app.success)


def test_page_does_not_offer_resume_after_bound_budget_is_exhausted(tmp_path, monkeypatch):
    run_dir = tmp_path / "exhausted"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "status": "needs_attention", "source_driver": "novel",
        "last_error": "writer_script 校验失败；共享格式与契约修复预算已满",
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(page, "RUNS", tmp_path)
    app = _app()
    app.selectbox[1].set_value(run_dir.name).run()
    assert not app.exception
    assert not any(item.label == "恢复同一任务" for item in app.button)
    assert any("不能从页面重置预算" in item.value for item in app.warning)


def test_page_explains_temporary_assistant_review_without_third_model(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "RUNS", tmp_path)
    app = _app()
    assert not app.exception
    assert any("不需要第三审核模型" in item.value for item in app.info)
    assert any("0/3" in item.value for item in app.info)


def test_page_explains_review_can_stop_after_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "RUNS", tmp_path)
    monkeypatch.setattr(page, "calibration_status", lambda _root: {
        "stop_per_draft_assistant_review": True,
        "consecutive_first_draft_passes": 3,
    })
    app = _app()
    assert not app.exception
    assert any("不再要求逐稿助手复核" in item.value for item in app.info)


def test_page_explains_old_profile_passes_do_not_count(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "RUNS", tmp_path)
    monkeypatch.setattr(page, "calibration_status", lambda _root: {
        "stop_per_draft_assistant_review": False,
        "consecutive_first_draft_passes": 0,
        "profile_mismatch_reviews": 2,
    })
    app = _app()
    assert not app.exception
    assert any("2 份旧流程首稿通过记录" in item.value for item in app.info)


def test_page_shows_bound_assistant_failure_without_claiming_video_pass(tmp_path, monkeypatch):
    run_dir = tmp_path / "reviewed"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "status": "media_handoff_pending_capability",
        "assistant_review_required": True,
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "CALIBRATION_REVIEW.json").write_text(json.dumps({
        "category": "video_original", "outcome": "major_issues",
        "first_draft_no_major": False, "reviewed_at": "2026-09-22T00:00:00+00:00",
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "CALIBRATION_REVIEW.md").write_text("B03 台词方向错误。", encoding="utf-8")
    monkeypatch.setattr(page, "RUNS", tmp_path)
    app = _app()
    app.session_state["creative_run_dir"] = str(run_dir)
    app.run()
    assert not app.exception
    assert any("主要质量问题" in item.value for item in app.error)
    assert not any("视频声画通过" in item.value for item in app.success)


def test_page_original_route_uses_brief_without_novel_or_video(tmp_path, monkeypatch):
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"schema": "creative_brief/v1", "theme": "关心"}), encoding="utf-8")
    launches = []
    monkeypatch.setattr(page, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(page.subprocess, "Popen", lambda argv, **kwargs: launches.append(argv))
    app = _app()
    app.selectbox[0].set_value("原创创作简报").run()
    app.text_input[0].set_value("新作品")
    app.text_input[2].set_value(str(brief))
    app.button[0].click().run()
    assert not app.exception
    assert len(launches) == 1
    argv = launches[0]
    assert argv[argv.index("--source-driver") + 1] == "original"
    assert argv[argv.index("--brief") + 1] == str(brief)
    assert "--novel" not in argv and "--video" not in argv



def test_page_feedback_uses_latest_stage_and_separates_history(tmp_path, monkeypatch):
    from test_creative_stage_debug import _rebuilt_run, _read_json
    run, bundle, script, _ = _rebuilt_run(tmp_path)
    current_hash = _read_json(run / "writer_script.json")["output_sha256"]
    monkeypatch.setattr(page, "RUNS", tmp_path)
    app = _app()
    app.session_state["creative_run_dir"] = str(run)
    app.run()
    assert not app.exception
    selector = next(item for item in app.selectbox if item.label == "反馈责任阶段")
    assert selector.options == ["writer_analysis", "director_brief", "writer_script"]
    selector.set_value("writer_script").run()
    next(item for item in app.button if item.label == "比较该阶段最近两版").click().run()
    assert not app.exception and any("FIXTURE rebuilt script" in item.value for item in app.code)
    next(item for item in app.checkbox if item.label == "显示历史阶段版本（只读）").check().run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 3 and len(app.dataframe[1].value) == 2
    next(item for item in app.text_area if item.label == "反馈原话").set_value("FIXTURE UI second feedback").run()
    next(item for item in app.button if item.label == "绑定阶段反馈").click().run()
    assert not app.exception
    state = _read_json(run / "state.json")
    assert state["debug_feedback"][-1]["output_sha256"] == current_hash
    assert state["debug_stage_validity"]["director_brief"] == "current"
    assert state["calls_started"] == 5



def test_page_feedback_rejects_version_changed_after_display(tmp_path,monkeypatch):
    from copy import deepcopy
    from test_creative_stage_debug import _rebuilt_run, _read_json, _resume
    from src.content_factory.creative_stage_debug import CreativeStageCommandService
    run,bundle,script,_=_rebuilt_run(tmp_path)
    monkeypatch.setattr(page,'RUNS',tmp_path)
    app=_app();app.session_state['creative_run_dir']=str(run);app.run()
    next(x for x in app.selectbox if x.label=='反馈责任阶段').set_value('writer_script').run()
    next(x for x in app.text_area if x.label=='反馈原话').set_value('[fixture stale UI feedback]').run()
    service=CreativeStageCommandService(run)
    service.feedback('writer_script','[fixture concurrent upstream repair]')
    revised=deepcopy(script);revised['title']='[fixture concurrently revised title]'
    _resume(run,bundle,[revised],stop='writer_script')
    count=len(_read_json(run/'state.json')['debug_feedback'])
    next(x for x in app.button if x.label=='绑定阶段反馈').click().run()
    assert not app.exception
    assert any('displayed stage version changed' in x.value for x in app.error)
    assert len(_read_json(run/'state.json')['debug_feedback'])==count
