from copy import deepcopy
from types import SimpleNamespace
from src.content_factory.creative_segmented_director import generate_reviewed_beats, bind_segmented_director
from tests.test_creative_workflow import _answers

class Harness:
    def __init__(self, decisions, run_dir):
        self.run_dir = run_dir
        self.answers = _answers()
        self.decisions = iter(decisions)
        self.max_revisions = 2
        self.max_calls = 20
        self.state = {'segmented_director_binding': bind_segmented_director(), 'writer_prompt_binding': {'creative_brief': {}}, 'revision_rounds': 0, 'calls_started': 0}
        self.seen = []
    def _stage(self, name, role, payload, validator):
        self.seen.append((name, deepcopy(payload)))
        if name.startswith('director'):
            beat = payload['script']['beats'][0]['id']
            value = deepcopy(self.answers[3])
            value['shots'] = [s for s in value['shots'] if s['beat_id'] == beat]
            validator(value)
            return value
        return {}
    def _verified_review(self, *args):
        return next(self.decisions)
    def _save(self):
        pass

def test_pending_segment_stops_before_next_generation(tmp_path):
    w = Harness([None], tmp_path)
    assert generate_reviewed_beats(w, w.answers[2], w.answers[1], {}) is None
    assert len(w.seen) == 2

def test_accepted_segment_passes_actual_end_state_forward(tmp_path):
    w = Harness([[], []], tmp_path)
    value = generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    assert len(value['shots']) == 2
    assert w.seen[2][1]['previous_shot'] == value['shots'][0]
    assert w.seen[2][1]['style_lock'] == value['style']

def test_director_repair_only_regenerates_current_beat(tmp_path):
    w = Harness([[], [{'owner':'director'}], []], tmp_path)
    value = generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    calls = [p['script']['beats'][0]['id'] for n,p in w.seen if n.startswith('director')]
    assert calls == ['B01', 'B02', 'B02']
    assert w.state['revision_rounds'] == 1
    assert len(value['shots']) == 2

def test_script_problem_blocks_following_segments(tmp_path):
    w = Harness([[{'owner':'writer'}]], tmp_path)
    assert generate_reviewed_beats(w, w.answers[2], w.answers[1], {}) is None
    assert w.state['status'] == 'needs_revision'
    assert len(w.seen) == 2


def test_new_segment_and_review_receive_actual_locked_future(tmp_path):
    w = Harness([None], tmp_path)
    generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    expected = w.answers[2]["beats"][1:]
    assert expected and "before" in expected[0]
    assert w.seen[0][1]["upcoming_beats"] == expected
    assert w.seen[1][1]["upcoming_beats"] == expected
    assert "已锁完整剧本" in w.seen[0][1]["locked_future_instructions"]
    assert (tmp_path / "director_shots__beat_01_00__context_binding.json").exists()


def test_legacy_cached_stage_keeps_unchanged_payload(tmp_path):
    (tmp_path / "director_shots__beat_01_00.json").write_text("{}", encoding="utf-8")
    w = Harness([None], tmp_path)
    generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    assert "upcoming_beats" not in w.seen[0][1]
    assert "upcoming_beats" not in w.seen[1][1]
    assert not (tmp_path / "director_shots__beat_01_00__context_binding.json").exists()


def test_new_stage_binding_replays_identically_with_cached_receipt(tmp_path):
    w = Harness([None], tmp_path)
    generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    (tmp_path / "director_shots__beat_01_00.json").write_text("{}", encoding="utf-8")
    resumed = Harness([None], tmp_path)
    generate_reviewed_beats(resumed, resumed.answers[2], resumed.answers[1], {})
    assert resumed.seen == w.seen


def test_new_revision_gets_future_context_without_changing_cached_attempt(tmp_path):
    (tmp_path / "director_shots__beat_01_00.json").write_text("{}", encoding="utf-8")
    w = Harness([[{"owner": "director"}], None], tmp_path)
    generate_reviewed_beats(w, w.answers[2], w.answers[1], {})
    assert "upcoming_beats" not in w.seen[0][1]
    assert w.seen[2][1]["upcoming_beats"] == w.answers[2]["beats"][1:]
    assert w.seen[3][1]["upcoming_beats"] == w.seen[2][1]["upcoming_beats"]
