"""Read-only rendered upload UI evidence through an existing bound Page.

No browser construction, navigation, file selection, form edit or submission.
The caller owns identity verification and the fixed page it chooses to inspect.
"""
import hashlib
import json
from pathlib import Path
import re

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def capture_upload_surface(page, evidence_dir, *, artifact_name='surface'):
    """Save bounded visible UI and an original-page screenshot inside the project.

    Returns UI plus SHA-bound evidence/screenshot references. Errors propagate;
    neither a preview nor diagnostics success means an upload has completed.
    """
    target = Path(evidence_dir).resolve()
    workspace = WORKSPACE_ROOT.resolve()
    if target == workspace or not target.is_relative_to(workspace):
        raise ValueError('upload surface evidence directory must be inside the project')
    if not isinstance(artifact_name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,179}', artifact_name):
        raise ValueError('upload surface artifact name must be a bounded local basename')
    target.mkdir(parents=True, exist_ok=True)
    evidence_path = target / (artifact_name + '.json')
    screenshot_path = target / (artifact_name + '.png')
    if (evidence_path.exists() or screenshot_path.exists()
            or evidence_path.is_symlink() or screenshot_path.is_symlink()):
        raise FileExistsError('upload surface evidence already exists; do not overwrite')
    observed = page.evaluate("""() => {
        const visible = (element) => {
            const rect = element.getBoundingClientRect();
            if (!(rect.width > 0 && rect.height > 0)) return false;
            for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
                const style = getComputedStyle(ancestor);
                if (style.display === 'none' || style.visibility === 'hidden'
                    || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
            }
            return true;
        };
        const text = (element, limit) => {
            const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
            let value = '', node, scanned = 0;
            const maximumNodes = limit > 256 ? 2000 : 64;
            while ((node = walker.nextNode()) && scanned++ < maximumNodes && value.length < limit) {
                const parent = node.parentElement;
                if (parent && visible(parent) && !parent.closest('script,style,noscript,template,video,audio,canvas')) {
                    const part = (node.textContent || '').trim();
                    if (part) value += (value ? '\\n' : '') + part;
                }
            }
            return value.slice(0, limit);
        };
        const buttons = Array.from(document.querySelectorAll('button,[role="button"]'))
            .filter(visible).slice(0, 40).map(element => ({
                text: text(element, 256), disabled: element.disabled === true,
                aria_disabled: (element.getAttribute('aria-disabled') || '').slice(0, 64)
            }));
        const progress = Array.from(document.querySelectorAll(
            '[role="progressbar"],progress,[class*="progress"],[class*="loading"],[class*="spinner"]'))
            .filter(visible).slice(0, 24).map(element => ({
                text: text(element, 256),
                aria_label: (element.getAttribute('aria-label') || '').slice(0, 256),
                aria_valuenow: (element.getAttribute('aria-valuenow') || '').slice(0, 64),
                aria_valuemin: (element.getAttribute('aria-valuemin') || '').slice(0, 64),
                aria_valuemax: (element.getAttribute('aria-valuemax') || '').slice(0, 64),
                aria_valuetext: (element.getAttribute('aria-valuetext') || '').slice(0, 256),
                aria_busy: (element.getAttribute('aria-busy') || '').slice(0, 64)
            }));
        return {visible_text: document.body ? text(document.body, 12000) : '', buttons, progress};
    }""")
    if (not isinstance(observed, dict) or not isinstance(observed.get('visible_text'), str)
            or not isinstance(observed.get('buttons'), list) or not isinstance(observed.get('progress'), list)):
        raise ValueError('upload_diagnostic_ui_shape_invalid')
    def rows(values, keys, maximum):
        result = []
        for row in values[:maximum]:
            if not isinstance(row, dict):
                raise ValueError('upload_diagnostic_ui_row_invalid')
            result.append({key: row.get(key) is True if key == 'disabled'
                else str(row.get(key) or '')[:256] for key in keys})
        return result
    ui = {'visible_text': observed['visible_text'][:12000],
        'buttons': rows(observed['buttons'], ('text', 'disabled', 'aria_disabled'), 40),
        'progress': rows(observed['progress'], ('text', 'aria_label', 'aria_valuenow',
            'aria_valuemin', 'aria_valuemax', 'aria_valuetext', 'aria_busy'), 24)}
    screenshot = getattr(page, 'screenshot', None)
    if callable(screenshot):
        screenshot(path=str(screenshot_path), full_page=False)
    else:
        # Project Page routes this existing command through its pinned
        # tab and the original owner/dispatch guard.
        page._cmd('screenshot', path=str(screenshot_path), full_page=False)
    if not screenshot_path.is_file() or screenshot_path.stat().st_size == 0:
        raise RuntimeError('upload_diagnostic_screenshot_missing')
    screenshot_sha = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    evidence = {'schema': 'publish_upload_visible_ui/v1', 'ui': ui,
        'screenshot': {'path': str(screenshot_path.resolve()), 'sha256': screenshot_sha},
        'upload_completion_assessed_by_diagnostic': False}
    with evidence_path.open('x', encoding='utf-8') as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2)
    return dict(evidence, evidence={'path': str(evidence_path.resolve()),
        'sha256': hashlib.sha256(evidence_path.read_bytes()).hexdigest()})
