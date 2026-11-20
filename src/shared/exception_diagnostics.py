"""Safe structural evidence; never persist exception text or arbitrary attributes."""
import re

from .browser_navigation import clean_navigation_evidence


def exception_causes(error):
    causes, seen = [], {id(error)}
    current = error.__cause__ or (
        None if error.__suppress_context__ else error.__context__)
    while current is not None and id(current) not in seen and len(causes) < 6:
        seen.add(id(current))
        item = {'error_type': type(current).__name__}
        # Only project-owned codes are persisted; arbitrary code attributes may
        # contain credentials even if syntactically valid identifiers.
        try:
            code = getattr(current, 'code', None)
        except Exception:
            code = None
        if isinstance(code, str) and code in {'browser_navigation_timeout', 'browser_start_timeout',
                    'owner_unknown', 'owner_fenced', 'late_task_callback',
                    'verification_ui_unconfirmed', 'human_required',
                    'recovery_probe_failed'}:
            item['code'] = code
        if code == 'browser_navigation_timeout':
            try:
                proof = getattr(current, 'navigation_evidence', None)
            except Exception:
                proof = None
            item['navigation_evidence'] = clean_navigation_evidence(proof)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,99}', item['error_type']):
            item['error_type'] = 'Exception'
        causes.append(item)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__)
    return causes
