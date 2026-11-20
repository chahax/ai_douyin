"""Assemble only an accepted, version-bound segment replacement. CPU only."""
from fractions import Fraction
import json
from pathlib import Path
import subprocess

from . import media_repair_loop_v1 as loop
from . import visual_spatial_clock_v30 as spatial

VERSION = 'media_repair_assembly_adapter/v1'


def _command(rows, target, filters, width, height, fps, rate):
    command = ['ffmpeg', '-nostdin', '-n', '-v', 'warning', '-filter_complex_threads', '1']
    lines, joined = [], []
    for i, row in enumerate(rows):
        command += ['-threads', '1', '-i', row['media']['path']]
        samples = Fraction(row['frames'], fps)*rate
        loop.require(samples.denominator == 1 and samples == row['audio_samples'], 'exact_segment_delivery_clock_required')
        lines += [f'[{i}:v:0]trim=end_frame={row["frames"]},setpts=N/({fps}*TB),setsar=1[v{i}]',
                  f'[{i}:a:0]aresample={rate}:async=0:first_pts=0,aformat=channel_layouts=stereo,apad=whole_len={samples.numerator},atrim=end_sample={samples.numerator},asetpts=N/SR/TB[a{i}]']
        joined += [f'[v{i}]', f'[a{i}]']
    lines += [''.join(joined)+f'concat=n={len(rows)}:v=1:a=1[vjoined][ajoined]',
              f'[vjoined]settb=1/{fps},setpts=N[video]', f'[ajoined]asettb=1/{rate},asetpts=N[audio]']
    command += ['-filter_complex_script', str(filters), '-map', '[video]', '-map', '[audio]',
                '-fps_mode', 'passthrough', '-enc_time_base:v', f'1:{fps}', '-c:v', 'libx264',
                '-preset', 'medium', '-crf', '18', '-threads', '2', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-ar', str(rate), '-ac', '2',
                '-video_track_timescale', str(fps*512), '-movie_timescale', str(rate),
                '-movflags', '+faststart', str(target)]
    return command, ';\n'.join(lines)+'\n'


def _verify_output(file, clock, width, height):
    metadata = spatial._probe(file)
    v = next(s for s in metadata['streams'] if s['codec_type']=='video')
    a = next(s for s in metadata['streams'] if s['codec_type']=='audio')
    loop.require((v['width'], v['height'], int(v['nb_read_frames']), Fraction(v['avg_frame_rate']))
                 == (width, height, clock['frames'], Fraction(clock['fps'])), 'assembled_geometry_or_frame_clock_changed')
    loop.require(Fraction(v['start_time']) == Fraction(a['start_time']) == 0, 'assembly_AV_starts_must_be_zero')
    actual_samples = Fraction(a['duration_ts'])*Fraction(a['time_base'])*int(a['sample_rate'])
    loop.require(int(a['sample_rate']) == clock['audio_rate'] and actual_samples == clock['audio_samples']
                 and a['channels'] == 2,
                 'assembled_effective_audio_clock_changed')
    proof = spatial._frame_proof(spatial._probe_frames(file), v['time_base'], clock['frames'], clock['fps'])
    raw = spatial._decode_audio(file, clock['audio_rate'])
    loop.require(len(raw) % 4 == 0 and 0 <= len(raw)//4-int(actual_samples) < 1024,
                 'complete_audio_decode_and_bounded_AAC_tail_padding_required')
    return dict(metadata=metadata, decoded_frame_proof=proof,
                effective_audio_samples=int(actual_samples), raw_decoded_samples=len(raw)//4,
                AAC_tail_padding_samples=len(raw)//4-int(actual_samples), effective_AV_start_difference=0,
                effective_AV_tail_difference=0)


class AssemblyAdapter:
    def __init__(self, spec):
        self.spec = spec
        context = loop.read(loop.checked(spec['adapter_context']))
        self.run = loop.path(context['run'])
        config = context['assembly']
        loop.require(config.get('schema') == 'media_repair_assembly_config/v1', 'assembly_config_required')
        self.width, self.height = config['width'], config['height']
        loop.require(all(type(n) is int and n > 0 for n in (self.width, self.height)), 'positive_output_dimensions_required')
        self.filename = config.get('filename', 'REPAIRED_FULL_MOVIE.mp4')
        loop.require(Path(self.filename).name == self.filename and self.filename.endswith('.mp4'), 'local_movie_filename_required')

    def assemble(self, request):
        with loop.run_lock(self.run, 'ASSEMBLER_EXECUTION.lock'):
            return self._assemble(request)

    def _assemble(self, request):
        loop.require(request.get('schema') == 'media_repair_assembly_request/v1', 'bound_assembly_request_required')
        run = loop.path(request['run'])
        loop.require(run == self.run, 'assembly_run_must_match_bound_context')
        selected = loop.read(loop.checked(request['selection']))
        loop.require(selected.get('schema') == 'media_repair_selection/v1'
                     and selected.get('effective_decision') == 'accept'
                     and selected.get('selected_only_after_accept') is True,
                     'accepted_selection_required_before_assembly')
        loop.require(request['segments'] == selected['segments']
                     and selected['original_clock'] == request['expected_clock']
                     and loop.read(loop.checked(request['spec'])) == self.spec,
                     'selection_spec_or_clock_changed')
        candidate = loop.read(loop.checked(selected['accepted_candidate']))
        native = loop.read(loop.checked(candidate['result']))
        loop.require(native.get('prompt_id') == candidate['native_id']
                     and native.get('technical_status') == 'technical_saved'
                     and native.get('files', {}).get('video', {}).get('sha256') == candidate['media']['sha256'],
                     'selected_candidate_must_be_saved_native_video')
        audit = loop.read(loop.checked(selected['accepted_audit']))
        loop.require(audit['candidate_media'] == candidate['media'] and audit['candidate_result'] == candidate['result']
                     and audit['native_id'] == candidate['native_id'], 'audit_subject_must_match_selected_candidate')
        if audit['decision'] == 'needs_review':
            review = loop._review(candidate, selected['accepted_audit'], selected['accepted_review'], self.spec)
            loop.require(review['decision'] == 'accept', 'actual_fresh_review_required')
        else:
            loop.require(audit['decision'] == 'accept', 'rejected_candidate_cannot_assemble')
        rows = request['segments']
        originals = self.spec['segments']
        loop.require(len(rows) == len(originals) and [r['id'] for r in rows] == [r['id'] for r in originals],
                     'only_one_ordered_segment_replacement_allowed')
        for row, old in zip(rows, originals):
            for key in ('media', 'result', 'source_case', 'asset_manifest'):
                loop.checked(row[key])
            if row['id'] == self.spec['repair_segment_id']:
                loop.require(row['native_id'] == candidate['native_id'] and row['media'] == candidate['media']
                             and row['result'] == candidate['result'] and row['native_id'] != old['native_id']
                             and row['source_case'] == candidate['source_case'] == self.spec['case_binding']
                             and row['asset_manifest'] == candidate['asset_manifest'] == self.spec['asset_manifest']
                             and all(row[k] == old[k] for k in ('frames', 'fps', 'audio_rate', 'audio_samples')),
                             'only_selected_fresh_target_may_replace_original')
            else:
                loop.require(all(row[key] == old[key] for key in old), 'untargeted_original_segment_changed')
        loop.require(loop._clock(rows) == loop._clock(originals) == request['expected_clock'], 'complete_story_duration_must_be_preserved')
        folder = run/'assembly'
        folder.mkdir(exist_ok=True)
        receipt_path = folder/'RECEIPT.json'
        if receipt_path.exists():
            prior = loop.read(receipt_path)
            loop.require(prior['selection'] == request['selection'], 'existing_assembly_selection_changed')
            loop.checked(prior['file'])
            for item in prior['artifacts']:
                loop.checked(item)
            return dict(status='complete', file=prior['file'], receipt=loop.bind(receipt_path))
        loop.require(not (folder/'CLAIM.json').exists(), 'assembly_adapter_outcome_unknown_do_not_retry')
        target, filters = folder/self.filename, folder/'FILTER.txt'
        loop.require(not target.exists() and not filters.exists(), 'unreceipted_assembly_output_preserved')
        clock = request['expected_clock']
        command, text = _command(rows, target, filters, self.width, self.height, clock['fps'], clock['audio_rate'])
        loop.freeze(run, 'assembly/CLAIM.json', dict(request=request, code=loop.bind(__file__), command=command, filters=text))
        sources = [spatial.clock_input(r['media']['path'], r['media']['sha256'], frames=r['frames'],
                   width=self.width, height=self.height, fps=r['fps'], rate=r['audio_rate']) for r in rows]
        loop.freeze(run, 'assembly/SOURCE_CLOCKS.json', dict(rows=sources))
        with filters.open('x', encoding='utf-8') as f:
            f.write(text)
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=2400)
        loop.freeze(run, 'assembly/PROCESS.json', dict(command=command, exit_code=result.returncode,
                    stdout=result.stdout, stderr=result.stderr))
        result.check_returncode()
        file = loop.bind(target)
        proof = _verify_output(target, clock, self.width, self.height)
        loop.freeze(run, 'assembly/DECODED_CLOCK.json', dict(file=file, **proof))
        for row in rows:
            loop.checked(row['media']); loop.checked(row['result'])
        receipt = dict(schema='media_repair_assembly/v1', selection=request['selection'], file=file,
                       clock=clock, completion_known=True, outcome_unknown=False,
                       decoded_clock=loop.bind(folder/'DECODED_CLOCK.json'), process=loop.bind(folder/'PROCESS.json'),
                       original_files_modified=False, no_story_trim=True, new_ASR_calls=0, new_model_calls=0,
                       content_quality_passed=False, publication=False,
                       artifacts=[loop.bind(folder/name) for name in (
                           'CLAIM.json', 'SOURCE_CLOCKS.json', 'FILTER.txt', 'PROCESS.json', 'DECODED_CLOCK.json')])
        loop.freeze(run, 'assembly/RECEIPT.json', receipt)
        return dict(status='complete', file=file, receipt=loop.bind(receipt_path))


def build_assembler(spec):
    return AssemblyAdapter(spec)
