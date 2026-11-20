"""Account-scoped creator metrics. Missing observations are never zero-filled."""
import math
import re
import json
from datetime import datetime, timezone

from src.services.database import get_db

METRICS = ('play_count', 'like_count', 'comment_count', 'share_count', 'collect_count')
RETENTION = ('completion_rate', 'bounce_2s_rate', 'follower_count')
WATCH_FIELDS = {
    'avg_watch_seconds': '平均观看时长（秒）',
    'total_watch_seconds': '总观看时长（秒）',
    'video_duration_seconds': '视频时长（秒）',
    'watch_5s_rate': '5秒观看率(%)',
    'avg_watch_percent': '平均观看比例(%)',
    'unique_viewers': '观看人数',
    'impression_count': '曝光量',
    'profile_visit_count': '主页访问量',
}


def _scope(account_uuid):
    if not account_uuid or account_uuid in ('*', '?'):
        raise ValueError('请选择具体运营账号')


def _number(value, *, percent=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (percent and value > 100):
        return None
    if integer and not float(value).is_integer():
        return None
    return value


def normalize_metrics(raw):
    result = {}
    for key in METRICS:
        value = raw.get(key)
        if value is None and key == 'like_count':
            value = raw.get('digg_count')
        try:
            number = float(value) if value is not None and not isinstance(value, bool) else float('nan')
            result[key] = int(number) if math.isfinite(number) and number >= 0 and number.is_integer() else None
        except (ValueError, TypeError, OverflowError):
            result[key] = None
    return result


def _ensure_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS creator_metric_snapshots (
        id INTEGER PRIMARY KEY, account_uuid TEXT NOT NULL, video_id TEXT NOT NULL,
        title TEXT, publish_time TEXT, collected_at TEXT NOT NULL, source TEXT NOT NULL,
        play_count INTEGER, like_count INTEGER, comment_count INTEGER,
        share_count INTEGER, collect_count INTEGER)''')
    columns = {row[1] for row in db.execute('PRAGMA table_info(creator_metric_snapshots)')}
    for key, kind in [('completion_rate', 'REAL'), ('bounce_2s_rate', 'REAL'),
                      ('follower_count', 'INTEGER'), ('evidence', 'TEXT'),
                      *((key, 'REAL') for key in WATCH_FIELDS),
                      ('metric_details_json', "TEXT NOT NULL DEFAULT '{}'"),
                      ('raw_metrics_json', "TEXT NOT NULL DEFAULT '{}'"),
                      ('period', "TEXT NOT NULL DEFAULT 'lifetime'"),
                      ('period_start', "TEXT NOT NULL DEFAULT ''"),
                      ('period_end', "TEXT NOT NULL DEFAULT ''"),
                      ('source_url', "TEXT NOT NULL DEFAULT ''")]:
        if key not in columns:
            db.execute(f'ALTER TABLE creator_metric_snapshots ADD COLUMN {key} {kind}')
    db.execute('''CREATE INDEX IF NOT EXISTS creator_metrics_account_video
        ON creator_metric_snapshots(account_uuid, video_id, id)''')


def record_snapshot(video):
    _scope(video.account_uuid)
    if not video.video_id:
        raise ValueError('指标快照必须有已绑定的账号和作品 ID')
    metrics = normalize_metrics(video.creator_metrics or {})
    payload = video.creator_metrics or {}
    period = payload.get('_period', 'lifetime')
    start, end = payload.get('_period_start', ''), payload.get('_period_end', '')
    if period not in ('lifetime', 'daily', 'range'):
        raise ValueError('统计口径必须为 lifetime、daily 或 range')
    if period != 'lifetime':
        from datetime import date
        if date.fromisoformat(start) > date.fromisoformat(end) or (period == 'daily' and start != end):
            raise ValueError('统计起止日期不匹配')
    elif start or end:
        raise ValueError('累计指标不能指定日统计区间')
    details = payload.get('_details', {})
    raw = payload.get('_raw_metrics', {})
    if not isinstance(details, dict) or not isinstance(raw, dict):
        raise ValueError('扩展指标和原始统计必须为 JSON 对象')
    details_json = json.dumps(details, ensure_ascii=False, allow_nan=False)
    raw_json = json.dumps(raw, ensure_ascii=False, allow_nan=False)
    retention = []
    for key in RETENTION:
        value = payload.get(key)
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
        valid = valid and (value <= 100 if key != 'follower_count' else float(value).is_integer())
        retention.append(value if valid else None)
    with get_db() as db:
        _ensure_table(db)
        db.execute('''INSERT INTO creator_metric_snapshots
            (account_uuid, video_id, title, publish_time, collected_at, source,
             play_count, like_count, comment_count, share_count, collect_count,
             completion_rate, bounce_2s_rate, follower_count, evidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (video.account_uuid, video.video_id, video.title, video.publish_time,
             datetime.now(timezone.utc).isoformat(), payload.get('_source', 'creator_work_list'),
             *(metrics[key] for key in METRICS), *retention, payload.get('_evidence', '')))
        snapshot_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        extra = {key: _number(payload.get(key), percent=key in ('watch_5s_rate', 'avg_watch_percent'),
                              integer=key in ('unique_viewers', 'impression_count', 'profile_visit_count'))
                 for key in WATCH_FIELDS}
        extra.update(metric_details_json=details_json, raw_metrics_json=raw_json, period=period,
                     period_start=start, period_end=end, source_url=payload.get('_source_url', 'https://creator.douyin.com/creator-micro/content/manage'))
        db.execute('UPDATE creator_metric_snapshots SET ' + ','.join(f'{key}=?' for key in extra) + ' WHERE id=?',
                   (*extra.values(), snapshot_id))
        db.commit()
        return snapshot_id


def latest_snapshots(account_uuid):
    if not account_uuid or account_uuid in ('*', '?'):
        return []
    with get_db() as db:
        _ensure_table(db)
        return [dict(row) for row in db.execute('''SELECT s.* FROM creator_metric_snapshots s
            JOIN (SELECT MAX(id) id FROM creator_metric_snapshots
                  WHERE account_uuid = ? AND period = 'lifetime' GROUP BY video_id) latest ON s.id = latest.id
            ORDER BY s.id DESC''', (account_uuid,))]


def latest_metric_totals(account_uuid):
    """Sum the latest lifetime counters while preserving missing-value coverage."""
    rows = latest_snapshots(account_uuid)
    totals = {}
    for key in METRICS:
        known = [row[key] for row in rows if row[key] is not None]
        totals[key] = sum(known) if known else None
        totals[key + '_coverage'] = len(known)
    totals['video_count'] = len(rows)
    return totals


def snapshot_history(account_uuid, video_id=None):
    _scope(account_uuid)
    with get_db() as db:
        _ensure_table(db)
        clause, params = (' AND video_id=?', (account_uuid,video_id)) if video_id else ('', (account_uuid,))
        return [dict(row) for row in db.execute('SELECT * FROM creator_metric_snapshots WHERE account_uuid=?' +
            clause + ' ORDER BY collected_at, id', params)]


def analyze_snapshot(row):
    plays = row.get('play_count')
    rates = {}
    for key in METRICS[1:]:
        value = row.get(key)
        rates[key] = value / plays * 100 if plays and value is not None else None
    if plays is None:
        note = '缺少播放量，暂不能计算互动率'
    elif plays == 0:
        note = '播放量为零，暂不能计算互动率'
    elif plays < 100:
        note = '播放样本较少，暂不判断内容优劣'
    else:
        note = '可观察互动与留存表现，避免将早期数据当作最终结论'
    return rates, note


def review_prompts(row):
    """Evidence-grounded review questions, not causal verdicts or automatic approval."""
    plays = row.get('play_count')
    if plays is None or plays < 100:
        return ['当前播放样本不足，先积累同发布时长的数据，再评估是否改变生产流程。']
    prompts = []
    if row.get('bounce_2s_rate') is not None:
        prompts.append(f"2秒跳出率 {row['bounce_2s_rate']:g}%：回看前2秒的信息是否清楚，可试验提前展示人物目标或争议点。")
    if row.get('completion_rate') is not None:
        prompts.append(f"完播率 {row['completion_rate']:g}%：结合逐秒留存查找流失段，再试验对白长度、冲突出现时间或镜头节奏。")
    if row.get('avg_watch_seconds') is not None:
        prompts.append(f"平均观看 {row['avg_watch_seconds']:g} 秒：对照视频时长和关键情节时间点，核对观众是否到达转折。")
    rates, _ = analyze_snapshot(row)
    if rates['share_count'] is not None:
        prompts.append(f"转发 / 分享率 {rates['share_count']:.2f}%：结合评论与参考视频，检验题材是否提供值得转发的信息或情绪。")
    return prompts or ['观看详情尚不完整，先补充留存和观看时长，再制定生产改动。']


def parse_manage_card(card):
    """Labels and units observed on creator content/manage, 2026-09-14."""
    lines = [line.strip() for line in card['text'].splitlines() if line.strip()]
    labels = {'播放': 'play_count', '点赞': 'like_count', '评论': 'comment_count',
              '分享': 'share_count', '收藏': 'collect_count', '完播率': 'completion_rate',
              '2秒跳出率': 'bounce_2s_rate', '吸粉量': 'follower_count'}
    metrics = dict.fromkeys((*METRICS, *RETENTION))
    for index, line in enumerate(lines[:-1]):
        key = labels.get(line)
        if not key:
            continue
        text = lines[index + 1].replace(',', '')
        if key in ('completion_rate', 'bounce_2s_rate'):
            if re.fullmatch(r'\d+(?:\.\d+)?%', text) and 0 <= float(text[:-1]) <= 100:
                metrics[key] = float(text[:-1])
        elif re.fullmatch(r'\d+', text):
            metrics[key] = int(text)
    date = next((line for line in lines if re.fullmatch(r'\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}', line)), '')
    metrics.update(_source='creator_manage_dom', _evidence=card['text'])
    metrics['_details'] = {'page_lines': lines}
    return {'title': card.get('title', ''), 'publish_time': date, 'metrics': metrics}


def attach_manage_cards(videos, cards):
    """Join unique full descriptions + publication minutes (UI prepends a short title)."""
    def key(title, date):
        return (''.join((title or '').split()), date or '')
    parsed = [parse_manage_card(c) for c in cards]
    def matches(video, card):
        title, date = key(video.title, video.publish_time)
        card_title, card_date = key(card['title'], card['publish_time'])
        return bool(title and date and date == card_date and
                    (title == card_title or (len(title) >= 30 and card_title.endswith(title))))
    count = 0
    for video in videos:
        candidates = [c for c in parsed if matches(video, c)]
        if len(candidates) == 1 and sum(matches(v, candidates[0]) for v in videos) == 1:
            previous = video.creator_metrics or {}
            video.creator_metrics = {**previous, **candidates[0]['metrics']}
            count += 1
    return count
