"""One render-only completion control; no new creative native values."""
from copy import deepcopy
import json

from tests.test_creative_world_scene_context_v1 import case, w


def test_existing_character_context_profile_and_want_render_without_invention(case):
    goal, script = case
    original = deepcopy((goal, script))
    before_goal_sha, before_script_sha = w.digest(goal), w.digest(script)
    text = w.render_script(script, goal)
    for actor in goal['whole_plan']['characters']:
        assert '### ' + actor['name'] in text and '身份：' + actor['role'] in text
        for label, key in (('人物档案', 'profile'), ('开场处境', 'initial_state'), ('当下目标', 'want')):
            value = actor[key]
            shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            assert label + '：\n' + shown in text
    assert text.count('当拍情境：') == len(script['beats'])
    assert (goal, script) == original and (w.digest(goal), w.digest(script)) == (before_goal_sha, before_script_sha)
