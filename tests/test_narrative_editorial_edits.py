import pytest
from scripts.revise_narrative_readable import apply_replacements

def test_exact_model_edit_preserves_unrelated_text():
    original='opening\nold prop position\nending'
    result=apply_replacements(original,{'replacements':[{'before':'old prop position','after':'correct prop position','reason':'continuity'}]})
    assert result=='opening\ncorrect prop position\nending'
    assert original=='opening\nold prop position\nending'

@pytest.mark.parametrize('before,body',[('missing','old'),('old','old old')])
def test_reject_ambiguous_or_missing_target(before,body):
    with pytest.raises(ValueError):apply_replacements(body,{'replacements':[{'before':before,'after':'new','reason':'test'}]})

def test_cannot_silently_delete_or_add_unexpected_fields():
    with pytest.raises(ValueError):apply_replacements('old',{'replacements':[{'before':'old','after':'','reason':'test'}]})
    with pytest.raises(ValueError):apply_replacements('old',{'replacements':[{'before':'old','after':'new','reason':'test','approved':True}]})
