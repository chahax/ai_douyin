"""Select the creator's AI declaration and verify a committed form control.

Text in a caption, hashtag, help message or platform-generated badge is never
evidence of the author's declaration. Unknown/custom UI fails closed.
"""
import re


AI_LABEL = re.compile(r"^(?:内容由\s*AI\s*生成|内容含\s*AI\s*生成|包含\s*AI\s*生成内容|含有\s*AI\s*生成内容)$", re.I)
ENTRY_LABELS = ("发文助手自主声明", "添加自主声明", "自主声明", "作品声明", "内容声明")
ENTRY = re.compile("^(?:" + "|".join(ENTRY_LABELS) + ")$")
CONTROL_ROLES = ("checkbox", "radio", "switch")


def _visible(locator):
    return [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]


def _controls(page):
    found = []
    for role in CONTROL_ROLES:
        found.extend((role, item) for item in _visible(page.get_by_role(role, name=AI_LABEL)))
    return found


def _selected(role, control):
    if role == "switch":
        return control.get_attribute("aria-checked") == "true"
    return control.is_checked()


def _popup(control):
    return control.evaluate("el => !!el.closest('[role=dialog], [role=listbox], [role=menu]')")


def read_ai_declaration(page):
    """Read only. An unchecked option or an unconfirmed dialog is not success."""
    controls = _controls(page)
    if len(controls) == 1:
        role, control = controls[0]
        if _selected(role, control) and not _popup(control):
            return {"verified": True, "label": "内容由AI生成", "method": role + "_checked"}
    # Native selects expose their selected option; custom comboboxes must expose
    # both a declaration label and the committed value, with the popup closed.
    for control in _visible(page.get_by_role("combobox", name=ENTRY)):
        if control.get_attribute("aria-expanded") == "true" or _popup(control):
            continue
        value = control.evaluate("""el => el.tagName === 'SELECT'
            ? (el.selectedOptions[0]?.textContent || '')
            : (el.innerText || el.getAttribute('aria-valuetext') || '')""")
        if AI_LABEL.fullmatch((value or "").strip()):
            return {"verified": True, "label": value.strip(), "method": "declaration_selected_value"}
    return {"verified": False, "reason": "未读到已生效的作者 AI 声明控件；页面出现 AI 字样不算声明成功"}


def _choose(page):
    controls = _controls(page)
    if len(controls) > 1:
        raise ValueError("AI 声明控件不唯一，停止以免选择错误")
    if controls:
        role, control = controls[0]
        if not _selected(role, control):
            if role == "switch":
                control.click(timeout=5000)
            else:
                control.set_checked(True, timeout=5000)
        return True
    for control in _visible(page.get_by_role("combobox", name=ENTRY)):
        if control.evaluate("el => el.tagName") == "SELECT":
            labels = control.locator("option").all_text_contents()
            matches = [label for label in labels if AI_LABEL.fullmatch(label.strip())]
            if len(matches) != 1:
                raise ValueError("AI 声明下拉项缺失或不唯一")
            control.select_option(label=matches[0], timeout=5000)
            return True
        control.click(timeout=5000)
        break
    options = _visible(page.get_by_role("option", name=AI_LABEL))
    if len(options) == 1:
        options[0].click(timeout=5000)
        return True
    if len(options) > 1:
        raise ValueError("AI 声明选项不唯一")
    return False


def _confirm_dialog(page):
    # Only confirm a dialog actually containing the named AI declaration control.
    # Never click a page-wide '确认', '发布' or unrelated agreement button.
    for dialog in _visible(page.get_by_role("dialog")):
        if not _controls(dialog):
            continue
        buttons = _visible(dialog.get_by_role("button", name=re.compile(r"^(确定|确认|完成|保存)$")))
        if len(buttons) == 1:
            buttons[0].click(timeout=5000)
            dialog.wait_for(state="hidden", timeout=5000)
        elif len(buttons) > 1:
            raise ValueError("声明弹窗有多个确认按钮，停止发布")


def set_ai_declaration(page):
    current = read_ai_declaration(page)
    if current["verified"]:
        return current  # Do not toggle a declaration already selected.
    chosen = _choose(page)
    if not chosen:
        # Support the publishing-page entry and the older Advanced Settings entry.
        for title in (*ENTRY_LABELS, "高级设置", *ENTRY_LABELS):
            entries = _visible(page.get_by_text(title, exact=True))
            if len(entries) > 1:
                raise ValueError("声明入口不唯一，停止发布")
            if entries:
                entries[0].click(timeout=5000)
                if _choose(page):
                    chosen = True
                    break
    if chosen:
        _confirm_dialog(page)
    # Allow the committed form state to render, but never infer it from a click.
    for _ in range(10):
        current = read_ai_declaration(page)
        if current["verified"]:
            return current
        page.wait_for_timeout(200)
    return current
