import pytest
from src.content_factory.novel_adaptation.prose_patch import prepare,apply

def test_native_prose_outside_fixed_spans_is_unchanged():
    text='头\n（内心）你好。\n好像冻了半年。\n尾'
    p=prepare(text,[{'quote':'（内心）你好。','reason':'spoken'}])
    assert apply(text,p,{'edit_0':'甲：你好。'})=='头\n甲：你好。\n好像冻了半年。\n尾'

@pytest.mark.parametrize('text,quote',[('aa','a'),('aa','b'),('aa','')])
def test_ambiguous_or_missing_span_rejected(text,quote):
    with pytest.raises(ValueError):prepare(text,[{'quote':quote,'reason':'x'}])

def test_extra_edit_or_changed_original_rejected():
    p=prepare('abc',[{'quote':'b','reason':'x'}])
    with pytest.raises(ValueError):apply('abc',p,{'edit_0':'x','edit_1':'y'})
    with pytest.raises(ValueError):apply('adc',p,{'edit_0':'x'})
