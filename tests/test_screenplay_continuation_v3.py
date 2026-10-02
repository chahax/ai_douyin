from scripts.run_screenplay_trial import prompt_for


def test_compact_continuation_preserves_dialogue_action_and_terminal_state_once():
    story={'characters':[{'name':'甲','appearance':'短发','wardrobe':'灰衣','voice':'男中音'},
                         {'name':'乙','appearance':'眼镜','wardrobe':'米衣','voice':'女中音'}],
           'version':{'props':[{'id':'P1','name':'合同'}],'shots':[
               {'shot_id':'S01','end_state':{'state':'旧状态'}},
               {'shot_id':'S02','dialogue_speaker':'乙','dialogue':'先核清楚！','action':'按住P1。',
                'end_state':{'state':'保持按住P1'}}]}}
    production={'shots':[{'shot_id':'S01'}, {'shot_id':'S02','emotion_and_performance':'抬高声量反击','composition':'固定双人中景'}]}
    prompt=prompt_for(story,production,'S02','screenplay_continuation/v3')
    assert prompt.count('先核清楚！')==1
    assert '抬高声量反击' in prompt and '按住合同。' in prompt and '保持按住合同' in prompt
    assert '女中音' in prompt and '男中音' not in prompt and '旧状态' not in prompt
