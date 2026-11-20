"""Read-only presentation of manual tasks; never settles or takes over an owner."""
from math import isfinite


def _stamp(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def present_manual_liveness(public, command, owner, *, now, ttl=90):
    """A persisted waiting_human row alone does not prove a usable window.

    All changes are to the returned public dictionary. Stale heartbeat is not
    evidence of process exit and must never authorize a new owner or window.
    """
    result = dict(public)
    if command.get('state') not in {'running', 'waiting_human'}:
        return result
    status = 'unavailable'
    if isinstance(owner, dict) and owner:
        matched = all(owner.get(key) == command.get(key) and command.get(key) is not None
                      for key in ('account_id', 'owner_id', 'generation', 'binding_version'))
        heartbeat = owner.get('heartbeat')
        if not matched:
            status = 'mismatch'
        elif owner.get('state') != 'active':
            status = 'inactive'
        elif _stamp(heartbeat) and _stamp(now) and 0 <= now - heartbeat <= ttl:
            status = 'fresh'
        else:
            status = 'stale'
        if _stamp(heartbeat):
            result['owner_heartbeat_at'] = heartbeat
    result['owner_status'] = status
    if status != 'fresh':
        result.update(phase='window_owner_unconfirmed', handoff_ready=False)
        # Old page observations must not be rendered as current verification.
        result.pop('current_verification', None)
        result.pop('feed_observation', None)
    elif (command.get('state') == 'waiting_human'
          and result.get('phase', '').startswith('window_')
          and result.get('phase') != 'window_display_unconfirmed'
          and (not _stamp(command.get('updated_at')) or now - command['updated_at'] > 180
               or command['updated_at'] > now)):
        result.update(phase='window_observation_stale')
        result.pop('current_verification', None)
    return result
