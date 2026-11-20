"""Recommendation-feed viewing, independent of keyword collection."""
import math
import re
import time

from .douyin_challenge import confirmed_douyin_challenge
from .douyin_playback import PlaybackItemResult, PlaybackRunResult

FEED_URL = "https://www.douyin.com/?recommend=1"
FEED_LOCATION_JS = "() => ({origin:location.origin,path:location.pathname})"

# Observed in the original account's IAB on 2026-10-20. Pick the card
# intersecting the viewport centre, never an off-screen preloaded video/live.
_ACTIVE_CARD = r"""
const cx = innerWidth / 2, cy = innerHeight / 2;
const cards = Array.from(document.querySelectorAll('[data-e2e="feed-item"]')).filter(n => {
  const r=n.getBoundingClientRect(), s=getComputedStyle(n);
  return s.display!=='none' && s.visibility!=='hidden' && Number(s.opacity)!==0 &&
    r.width>100 && r.height>100 && r.left<=cx && r.right>=cx && r.top<=cy && r.bottom>=cy;
});
if(cards.length!==1) return {found:false, reason:'active_card_ambiguous'};
const card=cards[0];
const root=card.querySelector('[data-e2e="feed-active-video"][data-e2e-vid]');
if(!root) return {found:true,kind:card.querySelector('[data-e2e="feed-live"]')?'live':'unsupported',
 card_key:card.querySelector('a[href*="/user/"]')?.getAttribute('href')||''};
const id=root.getAttribute('data-e2e-vid');
if(!/^\d{8,}$/.test(id||'')) return {found:false,reason:'video_identity_missing'};
const videos=Array.from(root.querySelectorAll('video')).filter(v=>{
 const r=v.getBoundingClientRect(),s=getComputedStyle(v);
 return s.display!=='none' && s.visibility!=='hidden' && Number(s.opacity)!==0 &&
   r.width>8 && r.height>8 && r.left<innerWidth && r.right>0 && r.top<innerHeight && r.bottom>0;
});
if(videos.length!==1) return {found:false,reason:'video_ambiguous'};
const video=videos[0];
"""

FEED_SNAPSHOT_JS = "() => {" + _ACTIVE_CARD + r"""
return {found:true,kind:'video',video_id:id,
 title:(root.querySelector('[data-e2e="video-desc"]')?.innerText||'').slice(0,2000),
 author:(root.querySelector('[data-e2e="feed-video-nickname"]')?.innerText||'').slice(0,200),
 current_time:Number(video.currentTime||0),duration:Number.isFinite(video.duration)?video.duration:0,
 paused:video.paused,ended:video.ended,seeking:video.seeking,ready_state:video.readyState,
 playback_rate:video.playbackRate};
}"""

FEED_PLAY_JS = "() => {" + _ACTIVE_CARD + """
video.muted=true;
video.play().catch(()=>{});
return {found:true,video_id:id};
}"""


def measured_delta(previous, current, elapsed):
    """Count only plausible forward media progress; seeks/card changes count zero."""
    if (previous.get("video_id") != current.get("video_id")
            or previous.get("paused") or current.get("seeking")
            or previous.get("seeking") or current.get("ready_state", 0) < 2
            or previous.get("playback_rate") != 1 or current.get("playback_rate") != 1):
        return 0.0
    before, after = float(previous.get("current_time", 0)), float(current.get("current_time", 0))
    duration = float(previous.get("duration", 0))
    delta = after - before
    if delta < 0 and duration > 0 and before >= duration - 1.5:
        delta = duration - before + after
    if not all(math.isfinite(x) for x in (delta, elapsed)) or elapsed <= 0:
        return 0.0
    return max(0.0, min(delta, elapsed + 0.25)) if 0 <= delta <= elapsed + 0.75 else 0.0


class DouyinRecommendationPlaybackController:
    def __init__(self, session, *, clock=time.monotonic, wall_clock=time.time):
        self.session, self.clock = session, clock
        self.wall_clock = wall_clock
        self._challenge_evidence = {}
        self._feed_surface_evidence = {}

    def _block(self, page):
        evidence = confirmed_douyin_challenge(page)
        self._challenge_evidence = dict(evidence) if evidence.get("blocking") else {}
        if evidence.get("blocking"):
            return ("human_required" if evidence.get("confirmations", 0) > 0
                    else "verification_ui_unconfirmed")
        # A visible login modal is an access failure; do not inspect captions
        # for generic words such as “风控”, which may simply be video content.
        return page.locator("").evaluate(r"""() => {
          const nodes=Array.from(document.querySelectorAll('[role="dialog"]'));
          return nodes.some(n=>{const r=n.getBoundingClientRect();
            return r.width>20 && r.height>20 && /扫码登录|验证码登录/.test(n.innerText||'');
          }) ? 'login_expired' : '';
        }""") or ""

    def _snapshot(self, page):
        return page.locator("").evaluate(FEED_SNAPSHOT_JS) or {}

    def _ready(self, page):
        # The challenge iframe can arrive several seconds after document load.
        # Give the feed a bounded loading window and classify the late overlay.
        for _ in range(30):
            code = self._block(page)
            if code:
                return {}, code
            if not getattr(self, '_entry_followed', False):
                from .recommendation_entry import enter_recommendation
                entry = enter_recommendation(page)
                self._last_entry = entry
                if entry.get('clicked'):
                    self._entry_followed = True
            state = self._snapshot(page)
            if state.get("found") and (state.get("kind") != "video" or (
                    state.get("ready_state", 0) >= 2
                    and isinstance(state.get('current_time'), (int,float))
                    and math.isfinite(state['current_time']) and state['current_time'] >= 0)):
                return state, ""
            page.wait_for_timeout(500)
        code = self._block(page) or "feed_not_ready"
        self._capture_failure_surface(page)
        return {}, code

    def _capture_failure_surface(self, page):
        try:
            raw = page._cmd('inspect_feed_surface').get('evidence', {})
            self._feed_surface_evidence.update({k:raw[k] for k in ('page','active_feed','video_layout') if k in raw})
            self._feed_surface_evidence['entry'] = getattr(self, '_last_entry', {})
        except Exception as exc:
            self._feed_surface_evidence['diagnostic_error_type'] = type(exc).__name__

    @staticmethod
    def _state_evidence(state):
        return {k: state[k] for k in ('found', 'kind', 'video_id', 'reason', 'current_time',
            'duration', 'paused', 'ended', 'seeking', 'ready_state', 'playback_rate')
            if k in state and isinstance(state[k], (str, bool, int, float))}

    @staticmethod
    def _valid_video(state):
        value = state.get('current_time')
        return (state.get('found') is True and state.get('kind') == 'video'
            and re.fullmatch(r'\d{8,}', str(state.get('video_id') or '')) is not None
            and state.get('ready_state', 0) >= 2 and type(value) in (int, float)
            and math.isfinite(value) and value >= 0)

    @staticmethod
    def _feed_location(page):
        value = page.locator('').evaluate(FEED_LOCATION_JS) or {}
        return {k: str(value.get(k) or '') for k in ('origin', 'path')} if isinstance(value, dict) else {}

    def _observe_change(self, page, profile, previous, current, old_id):
        """Separate an unready DOM from a verified, same-account feed transition."""
        event = {'before': self._state_evidence(previous), 'observed': self._state_evidence(current),
                 'rechecks': [], 'watch_time_during_recheck': 0}
        events = self._feed_surface_evidence.setdefault('transitions', [])
        events.append(event)
        if len(events) > 20:
            del events[:-20]  # Keep the failure's latest before/after evidence.
        for _ in range(3):
            if self._valid_video(current):
                break
            page.wait_for_timeout(250)
            code = self._block(page)
            if code:
                event['decision'] = code
                return current, code, False
            current = self._snapshot(page)
            event['rechecks'].append(self._state_evidence(current))
        if not self._valid_video(current):
            event['decision'] = 'feed_identity_unavailable'
            self._capture_failure_surface(page)
            return current, 'feed_identity_unavailable', False
        if current['video_id'] == old_id:
            event['decision'] = 'same_video_after_dom_recheck'
            return current, '', False
        event['location_before_identity'] = self._feed_location(page)
        if event['location_before_identity'] != {'origin': 'https://www.douyin.com', 'path': '/'}:
            event['decision'] = 'feed_origin_mismatch'
            return current, 'feed_origin_mismatch', False
        verifier = getattr(self.session, 'verify_feed_transition_identity', None)
        ctx = getattr(self.session, 'origin_context', None)
        if not callable(verifier) or ctx is None:
            event['decision'] = 'feed_transition_identity_unavailable'
            return current, 'feed_transition_identity_unavailable', False
        started = self.wall_clock()
        try:
            proof = verifier()
        except Exception as exc:
            event['identity_error_type'] = type(exc).__name__
            event['decision'] = str(getattr(exc, 'code', '') or 'feed_transition_identity_unavailable')
            return current, event['decision'], False
        finished = self.wall_clock()
        if not isinstance(proof, dict):
            proof = {}
        event['identity'] = {k:proof[k] for k in ('schema', 'account_uuid', 'command_id',
            'owner_id', 'generation', 'binding_version', 'feed_tab_id', 'identity_tab_id',
            'expected_public_uid', 'actual_public_uid', 'healthy', 'status', 'verified_at', 'source') if k in proof}
        stamp = proof.get('verified_at')
        if (proof.get('schema') != 'feed_transition_identity/v1'
                or proof.get('source') != 'runtime.verify_identity'
                or proof.get('account_uuid') != profile.account_uuid
                or proof.get('account_uuid') != ctx.account_id
                or proof.get('command_id') != ctx.task_id
                or proof.get('owner_id') != ctx.actor.owner_id
                or proof.get('generation') != ctx.actor.generation
                or proof.get('binding_version') != ctx.binding_version
                or proof.get('feed_tab_id') != getattr(page, 'tab_id', None)
                or not proof.get('identity_tab_id')
                or proof.get('identity_tab_id') == proof.get('feed_tab_id')
                or type(stamp) not in (int, float) or not math.isfinite(stamp)
                or not started <= stamp <= finished):
            event['decision'] = 'feed_transition_scope_mismatch'
            return current, 'feed_transition_scope_mismatch', False
        if proof.get('healthy') is not True:
            code = str(proof.get('status') or 'identity_unavailable')
            event['decision'] = code if code != 'active' else 'identity_unavailable'
            return current, event['decision'], False
        original_uid = str(ctx.resource.context.binding.public_uid or '')
        if (not original_uid or not proof.get('expected_public_uid') or not proof.get('actual_public_uid')):
            event['decision'] = 'identity_unavailable'
            return current, 'identity_unavailable', False
        if proof['expected_public_uid'] != original_uid or proof['actual_public_uid'] != original_uid:
            event['decision'] = 'identity_mismatch'
            return current, 'identity_mismatch', False
        code = self._block(page)
        event['location_after_identity'] = self._feed_location(page)
        after = self._snapshot(page)
        event['after_identity'] = self._state_evidence(after)
        if code:
            event['decision'] = code
            return after, code, False
        if event['location_after_identity'] != {'origin': 'https://www.douyin.com', 'path': '/'}:
            event['decision'] = 'feed_origin_mismatch'
            return after, 'feed_origin_mismatch', False
        if not self._valid_video(after) or after['video_id'] != current['video_id']:
            event['decision'] = 'feed_transition_unstable'
            return after, 'feed_transition_unstable', False
        event['decision'] = 'verified_same_account_feed_transition'
        return after, '', True

    def _advance(self, page, old):
        page.locator('[data-e2e="video-switch-next-arrow"]').click()
        for attempt in range(2):
            if attempt:
                # One ordinary keyboard fallback only after the original card
                # remained loaded and clear. Never repeat clicks blindly.
                page.locator('body').press('ArrowDown')
            for _ in range(10):
                page.wait_for_timeout(400)
                state, code = self._ready(page)
                if code:
                    return {}, code
                if (state.get("kind") != old.get("kind")
                        or state.get("video_id") != old.get("video_id")
                        or state.get("card_key") != old.get("card_key")):
                    return state, ""
        self._capture_failure_surface(page)
        return {}, "feed_did_not_advance"

    def run(self, profile, options, *, recent_video_ids=()):
        options.validate()
        if options.auto_like or options.auto_comment:
            raise ValueError("推荐流自动观看不执行点赞或评论。")
        result = PlaybackRunResult()
        self._challenge_evidence = {}
        self._feed_surface_evidence = {}
        try:
            return self._run(result, profile, options, recent_video_ids)
        except Exception as exc:
            result.status = "failed"
            result.error_code = str(getattr(exc, "code", "") or "feed_page_error")
            result.warnings.append("推荐流页面操作失败：" + type(exc).__name__)
            result.verified_videos = sum(int(item.playback_verified) for item in result.items)
            result.actual_watch_seconds = round(sum(item.actual_watch_seconds for item in result.items), 2)
            return result
        finally:
            result.challenge_evidence = dict(self._challenge_evidence)
            result.feed_surface_evidence = dict(self._feed_surface_evidence)
            if getattr(self,'_background_window',None):
                result.feed_surface_evidence['background_window']=self._background_window

    def _run(self, result, profile, options, recent_video_ids):
        from src.trend_intelligence.content_analysis.classification import score_account_relevance
        from src.operations_accounts.browser_control_runtime import background_safe_point
        deadline = self.clock() + options.total_minutes * 60
        seen = set(recent_video_ids)
        page = self.session.open_page(FEED_URL)
        # Dismiss only the observed navigation tutorial, never a verification.
        if not self._block(page):
            from .recommendation_entry import enter_recommendation
            self._entry_followed = bool(enter_recommendation(page).get('clicked'))
            page.interact_visible_exact_text("我知道了", operation="click")
        state, code = self._ready(page)
        max_cards = min(200, max(20, options.max_videos * 5))
        for index in range(max_cards):
            if code or self.clock() >= deadline or result.verified_videos >= options.max_videos:
                break
            deadline += background_safe_point({
                "stage": "recommendation_before_card", "next_candidate_index": index,
                "completed": result.to_dict(), "seen_video_ids": sorted(seen),
                "remaining_wall_seconds": max(0, deadline - self.clock()),
            })
            state, code = self._ready(page)
            if code:
                break
            if state.get("kind") == "video" and state["video_id"] not in seen:
                seen.add(state["video_id"])
                relevance = score_account_relevance(profile, title=state["title"],
                    hashtags=[], content_text=state["title"], evidence=[]).score
                if relevance >= options.min_relevance_score:
                    duration = state.get('duration',0)
                    known_duration = isinstance(duration,(int,float)) and math.isfinite(duration) and duration > 0
                    seconds = min(options.per_video_seconds, max(1, int(duration)) if known_duration else options.per_video_seconds,
                                  max(1, int(deadline - self.clock())))
                    item = PlaybackItemResult(video_id=state["video_id"], title=state["title"],
                        author=state["author"], url="https://www.douyin.com/video/" + state["video_id"],
                        relevance_score=relevance, planned_watch_seconds=seconds,
                        watch_plan_basis="recommend_feed_visible_caption" if known_duration else "recommend_feed_visible_caption_duration_unavailable",
                        start_current_time=state["current_time"], duration_seconds=duration if known_duration else 0)
                    result.items.append(item)
                    keep_background = getattr(self.session,'keep_background',None)
                    if callable(keep_background):
                        self._background_window = keep_background()
                    page.locator("").evaluate(FEED_PLAY_JS)
                    previous, sample_at = self._snapshot(page), self.clock()
                    stop = min(deadline, sample_at + seconds + 5)
                    transitioned = False
                    while self.clock() < stop:
                        page.wait_for_timeout(1000)
                        code = self._block(page)
                        if code:
                            break
                        current, now = self._snapshot(page), self.clock()
                        if current.get("video_id") != item.video_id:
                            current, code, transitioned = self._observe_change(
                                page, profile, previous, current, item.video_id)
                            # Rechecks/identity loading never count as watched time.
                            previous, sample_at = current, self.clock()
                            if code or transitioned:
                                break
                            continue
                        item.actual_watch_seconds += measured_delta(previous, current, now - sample_at)
                        item.end_current_time = current.get("current_time", 0)
                        previous, sample_at = current, now
                        if item.actual_watch_seconds >= seconds - 0.5:
                            break
                    item.actual_watch_seconds = round(item.actual_watch_seconds, 2)
                    item.playback_verified = not code and not transitioned and item.actual_watch_seconds >= max(1, seconds * .75)
                    item.completion_ratio = min(1, item.actual_watch_seconds / item.duration_seconds) if known_duration else 0
                    item.error_code = code or ("" if item.playback_verified or transitioned else "playback_unverified")
                    result.verified_videos += int(item.playback_verified)
                    result.actual_watch_seconds += item.actual_watch_seconds
                    if item.error_code:
                        code = item.error_code
                        break
                    if transitioned:
                        # The next card is already active. An extra arrow would skip it.
                        state = current
                        continue
                # Irrelevant captions and previously seen videos advance without
                # an artificial viewing delay. They are never successful watches.
            if result.verified_videos >= options.max_videos or self.clock() >= deadline:
                break
            state, code = self._advance(page, state)
        result.error_code = code
        result.actual_watch_seconds = round(result.actual_watch_seconds, 2)
        result.status = "blocked" if code else ("completed" if result.verified_videos else "skipped")
        if not result.verified_videos and not code:
            # Existing scheduler semantics distinguish no verified candidate
            # from a failed/uncertain account operation; never invent a watch.
            result.error_code = "no_playback_candidates"
        return result
