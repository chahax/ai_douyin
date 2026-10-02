from scripts.audit_cohort_pacing import audit

def script():
    return '\n'.join(f'- 租客【{i}-{i+1}秒】：甲乙丙丁戊' for i in range(30))

def test_readable_active_timing_is_only_text_pass():
    result=audit(script(),'short')
    assert result['passed'] and result['declared_dialogue_characters']==150
    assert 'Not actual audio' in result['scope']

def test_dense_and_stretched_speech_are_blocked():
    fast=audit(script().replace('【0-1秒】','【0-0.5秒】'),'short')
    slow=audit(script()+'\n- 房东【31-35秒】：甲乙丙丁戊己庚辛','short')
    assert any('too dense' in e for e in fast['errors'])
    assert any('too stretched' in e for e in slow['errors'])

def test_overlap_spoken_digits_and_out_of_range_are_blocked():
    result=audit(script()+'\n- 房东【28-46秒】：退1000元','short')
    assert not result['passed']
    assert any('overlapping' in e for e in result['errors'])
    assert any('Chinese numbers' in e for e in result['errors'])
    assert any('Invalid speech range' in e for e in result['errors'])

def test_long_version_cannot_be_short_dialogue_stretched():
    assert any('Insufficient' in e for e in audit(script(),'long')['errors'])
