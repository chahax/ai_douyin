"""Pinned sound-prompt repair over the unchanged private H3 asset transport.

Preparation stages images only when explicitly invoked by Root. The controller
executor never prepares, approves, changes service state, or resubmits unknown
work. Raw native audio and the delivery clock remain separate truths.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import wave

from . import h3_asset_flow_v2 as flow
from . import h3_universal_direction_execution_v1 as universal
from . import visual_h3_handoff_v3 as native

VERSION = 'h3_repair_generation_adapter/v1'
RECIPE = 'h3_repair_generation_recipe/v1'
ACTIVE = ('ye_xijue', 'ye_dong')
SID = 'S03'
read, bind, digest = flow.read, flow.bind, flow.digest


def require(value, reason):
    if not value:
        raise ValueError(reason)


def freeze(path, value):
    path = Path(path).resolve(); path.parent.mkdir(parents=True, exist_ok=True)
    native.freeze(path, value)
    return bind(path)


def recipe_value(binding):
    value = flow._bound(binding)
    require(value.get('schema') == RECIPE and value.get('segment_id') == SID,
            'explicit_S03_sound_repair_recipe_required')
    for name in ('original_native_plan', 'source_case', 'asset_manifest', 'policy', 'origin_profiles', 'active_profiles'):
        flow.core.check(value[name])
    require(isinstance(value.get('evidence'), list) and bool(value['evidence']), 'bound_sound_defect_evidence_required')
    for item in value['evidence']:
        flow.core.check(item)
    old_plan = flow._bound(value['original_native_plan'])
    old_folder = Path(value['original_native_plan']['path']).parent/'shots'/SID
    state = read(old_folder/'STATE.json')
    old_result = native._verify_result(old_folder, old_plan, old_plan['shots'][0], state)
    event = read(old_folder/'HISTORY.json').get(old_result['prompt_id'], {})
    original_graph = read(old_folder/'workflow_api.json')
    hp = event.get('prompt', [])
    require(state.get('status') == 'technical_saved' and len(hp) >= 3 and hp[1] == old_result['prompt_id']
            and event.get('status', {}).get('completed') is True
            and event['status'].get('status_str') == 'success'
            and native.native_graph_equivalence(original_graph, hp[2]) is not None
            and read(old_folder/'REQUEST.json').get('prompt') == original_graph,
            'actually_saved_original_S03_and_matching_native_history_required')
    out = Path(value['offline_output']).resolve()
    require(str(out) == old_plan.get('offline_output')
            and value['origin_profiles'] == old_plan.get('prompt_profiles')
            and value['asset_manifest'] == bind(out / 'INPUT_MANIFEST.json'),
            'repair_must_derive_exact_original_verified_offline_package')
    manifest = flow._bound(value['asset_manifest'])
    old_live = flow._bound(old_plan['live_manifest'])
    require(manifest['source_case'] == value['source_case'] and len(manifest['references']) == 9
            and manifest['references'][-1]['kind'] == 'dynamic_guide'
            and manifest['guide']['image'] == manifest['references'][-1]['image'],
            'same_source_nine_assets_and_actual_predecessor_guide_required')
    require(old_live['source_case'] == value['source_case']
            and old_live['directing_policy']['policy_binding'] == value['policy'],
            'original_source_and_directing_policy_must_remain_pinned')
    entry = flow.core._entries(value['source_case'])[0]
    flow.core.validate_entry(entry)
    require(entry['shot_id'] == SID and entry['duration'] == 15
            and [a['speaker'] for a in entry['audio']] == list(ACTIVE)
            and all(a['mode'] == 'onscreen' for a in entry['audio'])
            and [(a['start'], a['end']) for a in entry['audio']] == [(0.3, 10.8), (11.3, 12.6)],
            'original_two_S03_quotes_modes_and_time_windows_required')
    original_profiles, profiles = (flow._bound(value[k]) for k in ('origin_profiles', 'active_profiles'))
    require(profiles.get('schema') == 'library_voice_profiles/v1'
            and set(profiles.get('profiles', {})) == set(ACTIVE), 'only_actual_two_speakers_profiles_required')
    for cid in ACTIVE:
        profile = profiles['profiles'][cid]
        require(profile == original_profiles['profiles'][cid] and profile.get('actor') == cid
                and profile.get('type') == 'male_child' and bool(profile.get('description'))
                and not flow.core.QUOTE.search(profile['description']),
                'source_pinned_active_child_text_voice_profiles_required')
    return value


def audio_presentation(manifest, graph, recipe_binding):
    """Move the two original timed audio lines forward; leave visual prose intact."""
    recipe = recipe_value(recipe_binding)
    require(manifest['source_case'] == recipe['source_case']
            and manifest['guide']['image'] == flow._bound(recipe['asset_manifest'])['guide']['image']
            and flow.digest(graph) == manifest['graph_sha256']
            and graph['condition']['inputs']['prompt'] == manifest['compiled_prompt'],
            'verified_same_source_and_guide_template_required')
    entry = flow.core._entries(recipe['source_case'])[0]
    parsed = flow.core.validate_entry(entry)
    names, original = entry['character_names'], manifest['compiled_prompt']
    lines = original.splitlines()
    profiles = flow._bound(recipe['active_profiles'])['profiles']
    voice_lines = [names[cid] + '的声线：' + profiles[cid]['description'] for cid in ACTIVE]
    old_voices = [line for line in lines if any(line.startswith(names[c] + '的声线：') for c in names)]
    require(len(old_voices) == len(names), 'expected_original_full_cast_voice_block_required')
    spoken = []
    for audio in entry['audio']:
        quote = parsed['quotes'][audio['quote_index']].group()
        matched = [line for line in lines if quote in line]
        require(len(matched) == 1 and matched[0].startswith(f"{audio['start']:g}—{audio['end']:g}秒，")
                and names[audio['speaker']] in matched[0], 'exact_original_timed_dialogue_line_required')
        spoken.append(matched[0])
    remove = set(old_voices + spoken + ['声音设计：以下署名人物各自自然说出其台词，其他人在旁倾听与反应。'])
    retained = [line for line in lines if line not in remove]
    require(bool(retained), 'original_visual_presentation_required')
    opening = ['声音与画面从叶西决的叙述开始，普通话男童声自然连贯。', *voice_lines, *spoken]
    text = '\n'.join([retained[0], *opening, *retained[1:]])
    require(flow.core.QUOTE.findall(text) == flow.core.QUOTE.findall(original)
            and [line for line in text.splitlines() if '的声线：' in line] == voice_lines
            and text.index(spoken[0]) < text.index('<Picture 1>'),
            'two_original_quotes_and_only_active_voice_lines_required')
    patched = deepcopy(graph); patched['condition']['inputs']['prompt'] = text
    value = deepcopy(manifest)
    value.update(compiled_prompt=text, compiled_prompt_utf8_sha256=flow.core.sha(text), graph_sha256=digest(patched),
        repair_generation=dict(schema=VERSION, recipe=recipe_binding, origin_profiles=recipe['origin_profiles'],
            active_profiles=recipe['active_profiles'], active_speaker_ids=list(ACTIVE),
            origin_graph_sha256=manifest['graph_sha256'], origin_prompt_sha256=manifest['compiled_prompt_utf8_sha256'],
            source_facts_camera_assets_contact_unchanged=True, voice_control_mode='prompt_only',
            voice_identity_locked=False, audio_reference_inputs=0, first_original_audio_front_loaded=True))
    restored = deepcopy(patched); restored['condition']['inputs']['prompt'] = original
    require(restored == graph and all(value[k] == v for k, v in manifest.items()
            if k not in ('compiled_prompt', 'compiled_prompt_utf8_sha256', 'graph_sha256')),
            'sound_repair_cannot_modify_nonprompt_graph_or_source_assets_state')
    flow.validate_graph(patched, value['references'], value['voice_resolution'], value['scope'])
    return dict(manifest=value, graph=patched)


def for_run(run, recipe_binding):
    """A one-run isolated factory; shared old modules and artifacts stay frozen."""
    bound = Path(run).resolve(); recipe = recipe_value(recipe_binding)
    api = universal.asset_for_run(bound, recipe['policy'])
    original_derive, original_codes = api._derive, api._codes
    def derive(out, actual_run, profiles):
        require(Path(actual_run).resolve() == bound and Path(out).resolve() == Path(recipe['offline_output']).resolve()
                and profiles == recipe['active_profiles'], 'one_bound_repair_run_draft_and_active_profiles_required')
        # The old renderer supplies the proven source/visual template. Its full
        # cast voice block is replaced before the final prompt is ever staged.
        before_m, before_g, entry, scope = original_derive(out, actual_run, recipe['origin_profiles'])
        result = audio_presentation(before_m, before_g, recipe_binding)
        return result['manifest'], result['graph'], entry, scope
    def codes(profiles, extra):
        result = original_codes(profiles, extra)
        value = bind(__file__)
        if value not in result: result.append(value)
        return result
    api._derive, api._codes = derive, codes
    return api


def _command(args):
    result = subprocess.run(args, capture_output=True, check=True, timeout=180, encoding=None)
    return result.stdout


def _probe(path, *, count_frames=False):
    return json.loads(_command(['ffprobe', '-v', 'error', *(['-count_frames'] if count_frames else []),
                               '-show_streams', '-show_format', '-of', 'json', str(path)]))


def audio_clock_receipt(run, native_result_binding, output):
    """CPU-verify raw clock and a complete resample/pad derivation, never cut it."""
    run, output = Path(run).resolve(), Path(output).resolve()
    require(output.is_relative_to(run), 'clock_proof_must_stay_inside_native_repair_run')
    result = flow._bound(native_result_binding)
    media = {k: result['files']['video'][k] for k in ('path', 'sha256')}
    audio = {k: result['files']['audio'][k] for k in ('path', 'sha256')}
    for item in (media, audio): flow.core.check(item)
    target = output / 'AUDIO_CLOCK_RECEIPT.json'
    if target.exists():
        prior = read(target)
        require(prior['result'] == native_result_binding and prior['media'] == media
                and prior.get('nominal_frame_clock') == dict(frames=362, fps=24)
                and prior.get('delivery_clock') == dict(rate=48000, samples=724000)
                and prior.get('normalization_verified') is True and prior.get('content_trimmed') is False,
                'existing_candidate_clock_binding_changed')
        for item in prior['evidence']: flow.core.check(item)
        raw, normalized = (flow._bound(prior['evidence'][i]) for i in (0,1))
        require(prior.get('native_audio_clock') == dict(rate=raw['rate'], samples=raw['decoded_samples'], media=audio)
                and raw['result'] == native_result_binding and raw['media'] == media and raw['audio_media'] == audio
                and normalized['source'] == audio and normalized['file'] == prior['evidence'][2]
                and (normalized['rate'], normalized['samples']) == (48000,724000),
                'cached_three_clocks_must_match_actual_bound_CPU_evidence')
        with wave.open(normalized['file']['path'], 'rb') as wav:
            require((wav.getframerate(),wav.getnchannels(),wav.getnframes()) == (48000,2,724000),
                    'cached_normalization_must_still_have_actual_delivery_samples')
        return bind(target)
    output.mkdir(parents=True, exist_ok=True)
    video_probe = _probe(media['path'], count_frames=True)
    video = next(s for s in video_probe['streams'] if s['codec_type']=='video')
    require((int(video['width']),int(video['height']),int(video['nb_read_frames'])) == (736,1312,362)
            and Fraction(video.get('avg_frame_rate',video.get('r_frame_rate'))) == 24,
            'candidate_video_must_actually_decode_original_362_frame_clock')
    probe = _probe(audio['path']); stream = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    rate, channels = int(stream['sample_rate']), int(stream['channels'])
    require(rate in (32000, 44100, 48000) and channels == 2, 'supported_actual_native_stereo_audio_required')
    pcm = _command(['ffmpeg', '-nostdin', '-v', 'error', '-i', audio['path'], '-map', '0:a:0',
                    '-f', 's16le', '-acodec', 'pcm_s16le', '-'])
    require(len(pcm) % (channels * 2) == 0, 'complete_decoded_native_audio_samples_required')
    samples = len(pcm) // (channels * 2)
    seconds, duration = Fraction(samples, rate), Fraction(362, 24)
    require(0 <= duration-seconds <= Fraction(1, 24), 'native_audio_cannot_be_content_trimmed_to_fit_video')
    raw_proof = freeze(output / 'RAW_AUDIO_PROBE.json', dict(native_id=result['prompt_id'], result=native_result_binding,
        media=media, audio_media=audio, probe=probe, video_probe=video_probe, rate=rate, channels=channels, decoded_samples=samples,
        decoded_PCM_sha256=hashlib.sha256(pcm).hexdigest(), frame_clock=dict(frames=362, fps=24)))
    normalized = output / 'DELIVERY_CLOCK_AUDIO.wav'
    conversion = ['ffmpeg', '-nostdin', '-v', 'error', '-i', audio['path'], '-map', '0:a:0', '-af',
        'aresample=48000,apad,atrim=end_sample=724000,asetpts=N/SR/TB', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le']
    existed = normalized.exists()
    if not existed:
        _command([*conversion, str(normalized)])
    with wave.open(str(normalized), 'rb') as wav:
        require((wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (48000, 2, 724000),
                'actual_delivery_clock_export_must_have_exact_samples')
        if existed:
            require(wav.readframes(wav.getnframes()) == _command([*conversion, '-f', 's16le', '-']),
                    'existing_unreceipted_clock_export_must_match_same_full_source_PCM')
    flow.core.check(audio); flow.core.check(media)
    normalized_probe = freeze(output / 'NORMALIZED_AUDIO_PROBE.json', dict(file=bind(normalized),
        actual_probe=_probe(normalized), rate=48000, samples=724000, source=audio,
        operation='resample_full_source_then_tail_pad', meaningful_content_trimmed=False,
        resample_input_samples=samples, resample_input_rate=rate))
    value = dict(schema='media_repair_candidate_clock/v1', native_id=result['prompt_id'], result=native_result_binding,
        media=media, nominal_frame_clock=dict(frames=362, fps=24),
        native_audio_clock=dict(rate=rate, samples=samples, media=audio), delivery_clock=dict(rate=48000, samples=724000),
        normalization_verified=True, content_trimmed=False, evidence=[raw_proof, normalized_probe, bind(normalized)])
    return freeze(target, value)


class GenerationExecutor:
    """Controller protocol for one already prepared, explicitly approved native."""
    def __init__(self, native_run, recipe_binding):
        self.run = Path(native_run).resolve(); self.recipe_binding = recipe_binding
        self.recipe = recipe_value(recipe_binding); self.api = for_run(self.run, recipe_binding)

    def _request(self, request, phase):
        require(request.get('schema') == 'media_repair_request/v1' and request.get('attempt_id') == 'A001'
                and request.get('segment_id') == SID and request.get('mode') == 'regen_segment'
                and request.get('phase') == phase, 'one_controller_S03_A001_regeneration_request_required')
        case_run = Path(request['run']).resolve()
        require(self.run.parent.name == 'visual_h3_v3' and self.run.parent.parent == case_run
                and Path(request['attempt_dir']).resolve() == case_run/'attempts/A001',
                'controller_attempt_and_native_must_share_same_new_repair_run')
        spec = flow._bound(request['spec'])
        require(spec.get('max_attempts') == 1 and spec.get('repair_segment_id') == SID
                and spec.get('mode') == 'regen_segment'
                and request['case_binding'] == spec['case_binding'] == self.recipe['source_case']
                and request['asset_manifest'] == spec['asset_manifest'] == self.recipe['asset_manifest']
                and request['evidence'] == spec['evidence'] == self.recipe['evidence']
                and request['authorization'] == spec['authorization'], 'controller_spec_case_assets_evidence_authority_changed')
        for item in (request['case_binding'], request['asset_manifest'], request['authorization'], *request['evidence']):
            flow.core.check(item)
        old_plan = flow._bound(self.recipe['original_native_plan'])
        original = request['original']; plan = read(self.run/'PLAN.json')
        require(original == next(r for r in spec['segments'] if r['id'] == SID)
                and original['source_case'] == self.recipe['source_case']
                and original['result'] == bind(Path(self.recipe['original_native_plan']['path']).parent/'shots/S03/RESULT.json')
                and plan['user_authorization'] == request['authorization']
                and plan['prompt_profiles'] == self.recipe['active_profiles']
                and old_plan['shots'][0]['id'] == SID, 'original_S03_and_prepared_authority_binding_required')
        freeze(self.run/('CONTROLLER_'+phase.upper()+'_REQUEST.json'),
               {k: deepcopy(request[k]) for k in ('schema','run','spec','attempt_id','attempt_dir','segment_id','mode',
                    'original','case_binding','asset_manifest','evidence','authorization')})
        return spec

    def status(self, request):
        self._request(request, request.get('phase'))
        return self.api.status(self.run)

    def submit(self, request):
        self._request(request, 'submission')
        state = self.api.status(self.run)
        if not (self.run/'shots/S03/CLAIM.json').exists():
            state = self.api.submit(self.run)
        pid = state.get('prompt_id')
        if pid and state['status'] in ('submitted', 'running', 'technical_saved'):
            return dict(status='submitted', native_id=pid, native_run=str(self.run), recipe=self.recipe_binding)
        if state['status'] in ('outcome_unknown', 'rejected', 'failed', 'interrupted') or (self.run/'shots/S03/CLAIM.json').exists():
            return dict(status='outcome_unknown', native_run=str(self.run), original_state=state, no_resubmit=True)
        raise ValueError('native_not_submitted_controller_claim_retained_for_review')

    def collect(self, request):
        self._request(request, 'collection')
        pid = request.get('native_id')
        require(isinstance(pid, str) and request.get('submission', {}).get('native_id') == pid,
                'collection_requires_original_returned_native_ID')
        require(read(self.run/'shots/S03/STATE.json').get('prompt_id') == pid, 'no_collect_of_another_native_ID')
        state = self.api.collect_known(self.run, pid)
        if state['status'] in ('failed', 'interrupted', 'rejected', 'outcome_unknown'):
            return dict(status='outcome_unknown', native_id=pid, original_state=state, no_resubmit=True)
        if state['status'] != 'technical_saved': return dict(status='pending', native_id=pid)
        result_binding = bind(self.run/'shots/S03/RESULT.json'); result = flow._bound(result_binding)
        require(result['prompt_id'] == pid and result['technical_status'] == 'technical_saved', 'saved_original_candidate_required')
        receipt_binding = audio_clock_receipt(self.run, result_binding, self.run/'candidate_clock')
        clock = flow._bound(receipt_binding)
        candidate = dict(schema='media_repair_candidate/v1', attempt_id='A001', segment_id=SID, native_id=pid,
            result=result_binding, media={k:result['files']['video'][k] for k in ('path','sha256')},
            source_case=request['case_binding'], asset_manifest=request['asset_manifest'],
            nominal_frame_clock=clock['nominal_frame_clock'], native_audio_clock=clock['native_audio_clock'],
            delivery_clock=clock['delivery_clock'], audio_clock_receipt=receipt_binding,
            completion_known=True, outcome_unknown=False)
        binding = freeze(self.run/'CANDIDATE.json', candidate)
        return dict(status='saved', native_id=pid, candidate=binding)


def build_executor(config):
    return GenerationExecutor(config['native_run'], config['recipe'])
