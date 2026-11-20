"""Account run counts are audit statistics, not a default admission budget.

The legacy cap is opt-in for installations that explicitly retain it. This
does not change per-command authorization, identity, locks, or model budgets.
"""
import os


def daily_limit_reached(runs, limit):
    legacy_enabled = os.environ.get('AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT', '0').strip().lower()
    return legacy_enabled in {'1', 'true', 'yes', 'on'} and runs >= max(1, limit)
