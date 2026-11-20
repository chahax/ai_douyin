"""Check explicit reviewed speech/action order against executed scene events."""
def normalized_utterance(text):
    return ''.join(ch for ch in text if ch.isalnum())


def validate(scene,rules):
    for rule in rules:
        anchors=[(i,j,a) for i,b in enumerate(scene['beats']) for j,a in enumerate(b['audio'])
                 if a['speaker']==rule['speaker'] and a['kind']=='dialogue' and
                 normalized_utterance(a['text'])==normalized_utterance(rule['utterance'])]
        if len(anchors)!=1:raise ValueError('temporal_speech_anchor_ambiguous_or_missing')
        ai,aj,a=anchors[0]
        for recipe in rule['recipes_after_speech']:
            actions=[(i,t) for i,b in enumerate(scene['beats']) for t in b.get('transforms',[]) if t['recipe']==recipe]
            if len(actions)!=1:raise ValueError('temporal_action_missing_or_repeated:'+recipe)
            i,event=actions[0]
            phase=event.get('phase','start')
            after=(i>ai or (i==ai and (phase=='end' or (phase=='after_audio' and event['after_audio_index']>=aj))))
            if not after:raise ValueError('action_precedes_required_speech:'+recipe)
