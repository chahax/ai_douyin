"""A checked radio inside the title-bound non-ARIA modal is not committed."""
import pytest

from src.platform_adapter.ai_content_declaration import read_ai_declaration, set_ai_declaration


class Items:
    def __init__(self, values=()): self.values = list(values)
    def count(self): return len(self.values)
    def nth(self, index): return self.values[index]


class Option:
    def __init__(self, form):
        self.form, self.checked, self.connected = form, True, True
        self.label, self.native_clicks = '内容由AI生成', 0
    def is_visible(self): return self.form.open and self.connected
    def is_checked(self): return self.checked
    def element_handle(self, **_): return self
    def evaluate(self, script, original=None):
        if 'connected:el.isConnected' in script:
            return dict(connected=self.connected, tag='INPUT', type='radio', checked=self.checked,
                aria_label=self.label, labels=[])
        if 'el.isConnected' in script:return self.connected
        if 'el === original' in script:return self is original
        return False
    def set_checked(self, value, **_):
        self.native_clicks += 1; self.checked=value


class Button:
    def __init__(self, form, name):self.form,self.name,self.clicks=form,name,0
    def is_visible(self):return self.form.open
    def click(self, **_):
        self.clicks += 1
        if self.name=='确定' and self.form.responsive:
            self.form.open=False
            if self.form.destroy:self.form.option.connected=False


class Container:
    def __init__(self, form, *, body=False):self.form,self.body=form,body
    def count(self):return 1
    def is_visible(self):return self.form.open
    def element_handle(self, **_):return self
    def locator(self, selector):
        assert selector=='xpath=..'
        return Container(self.form,body=True)
    def evaluate(self, script, original=None):
        if 'container.contains(original)' in script:
            return original is self.form.option and original.connected
        return 'BODY' if self.body else 'DIV'
    def get_by_text(self, text, exact=True):return self.form.get_by_text(text,exact=exact)
    def get_by_role(self, role, name=None):return self.form.get_by_role(role,name=name)
    def wait_for(self, state, timeout):
        assert state=='hidden'
        if self.form.open:raise TimeoutError('modal did not close')


class Title:
    def __init__(self, form):self.form=form
    def is_visible(self):return self.form.open and self.form.title_visible
    def locator(self, selector):
        assert selector=='xpath=..'
        return self.form.container


class Form:
    url='http://loopback.invalid/original-upload'
    def __init__(self, *, duplicate=False, responsive=True, destroy=False, duplicate_confirm=False):
        self.open,self.title_visible=True,True
        self.duplicate,self.responsive,self.destroy=duplicate,responsive,destroy
        self.option=Option(self);self.container=Container(self)
        self.confirm=Button(self,'确定');self.cancel=Button(self,'取消')
        self.duplicate_confirm=duplicate_confirm
    def get_by_text(self, text, exact=True):
        return Items([Title(self)]*(2 if self.duplicate else 1)) if text=='对作品内容添加声明' else Items()
    def get_by_role(self, role, name=None):
        if role=='radio':return Items([self.option])
        if role=='button':
            values=[x for x in (self.confirm,self.cancel) if name.fullmatch(x.name)]
            if self.duplicate_confirm and name.fullmatch('确定'):values.append(Button(self,'确定'))
            return Items(values)
        return Items()
    def wait_for_timeout(self, ms):assert ms==200


def test_open_nonrole_dialog_checked_radio_is_not_committed():
    form=Form()
    assert read_ai_declaration(form)['verified'] is False
    assert form.confirm.clicks==0 and form.option.native_clicks==0


def test_unique_confirmation_then_independent_reads_bind_hidden_original_native_control():
    form=Form()
    result=set_ai_declaration(form)
    assert result['verified'] is True and result['method']=='confirmed_hidden_original_control'
    assert form.confirm.clicks==1 and form.cancel.clicks==0 and form.option.native_clicks==0
    assert not form.option.is_visible()
    assert read_ai_declaration(form)['verified'] is True
    assert set_ai_declaration(form)['verified'] is True
    assert form.confirm.clicks==1


@pytest.mark.parametrize('change', ['unchecked','label','destroyed','replaced','navigation','reopened','hidden_title_open_modal'])
def test_hidden_original_is_revalidated_on_every_independent_read(change):
    form=Form();assert set_ai_declaration(form)['verified'] is True
    if change=='unchecked':form.option.checked=False
    elif change=='label':form.option.label='内容为个人观点或见解'
    elif change=='destroyed':form.option.connected=False
    elif change=='replaced':
        form.option.connected=False;form.option=Option(form)
    elif change=='navigation':form.url='http://loopback.invalid/other'
    elif change=='reopened':form.open=True
    else:form.open=True;form.title_visible=False
    assert read_ai_declaration(form)['verified'] is False
    assert form.confirm.clicks==1


def test_control_destroyed_on_confirm_and_plain_ai_text_do_not_prove_committed_state():
    form=Form(destroy=True)
    assert set_ai_declaration(form)['verified'] is False
    assert form.confirm.clicks==1


@pytest.mark.parametrize('kind', ['duplicate_title','duplicate_confirm'])
def test_ambiguous_nonrole_dialog_does_not_click_any_confirm(kind):
    form=Form(duplicate=kind=='duplicate_title',duplicate_confirm=kind=='duplicate_confirm')
    assert read_ai_declaration(form)['verified'] is False
    with pytest.raises(ValueError):set_ai_declaration(form)
    assert form.confirm.clicks==form.cancel.clicks==0


def test_confirm_without_disappearance_never_commits():
    form=Form(responsive=False)
    with pytest.raises(TimeoutError):set_ai_declaration(form)
    assert read_ai_declaration(form)['verified'] is False
    assert form.confirm.clicks==1


def test_unknown_structure_blocks_read_even_when_radio_is_checked():
    form=Form()
    form.container=Container(form,body=True)
    assert read_ai_declaration(form)['verified'] is False
    with pytest.raises(ValueError):set_ai_declaration(form)
    assert form.confirm.clicks==0


def test_confirmed_original_cannot_transfer_to_another_page():
    first=Form();assert set_ai_declaration(first)['verified'] is True
    other=Form();other.open=False
    assert read_ai_declaration(other)['verified'] is False
