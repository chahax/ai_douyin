"""Prepare source-bound story opening frames and CPU staging; never submit media."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_opening_frame as opening
from src.content_factory import visual_spatial_reanchor_v34 as spatial

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT / 'data/qa/h3_story_openings_20261110_v1'


def _freeze(path, value):
    """Create a preparation record, or verify an identical prior preparation."""
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError('existing_preparation_record_changed:' + str(path))
        return core.binding(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as output:
        output.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    return core.binding(path)


def prepare(source=spatial.SPEC, out=DEFAULT_OUT):
    source = Path(source).resolve()
    out = Path(out).resolve()
    # Protect the input file and every containing directory. The derived case
    # must be a separate child/sibling root, never the original source root.
    if source == out or source.is_relative_to(out):
        raise ValueError('output_cannot_be_source_or_source_ancestor')
    source_binding = core.binding(source)
    originals = core._entries(source_binding)
    rows, contracts, summaries = [], [], []
    for original in originals:
        validated = core.validate_entry(original)
        row = deepcopy(original)
        row['first_frame_policy'] = opening.POLICY
        core.validate_entry(row)
        contract = opening.contract(row)
        rows.append(row)
        contracts.append(contract)
        summaries.append(dict(
            shot_id=row['shot_id'],
            framing=contract['opening_camera_beat']['framing'],
            first_frame_visible_actors=contract['opening_visible_actors'],
            first_frame_required_faces=contract['required_faces'],
            clip_visible_actors=validated['visible_actors'],
            clip_required_faces=validated['required_faces'],
            later_identity_context_only=contract['later_identity_context_only'],
            opening_contract_sha256=opening.digest(contract),
            existing_first_image=row['actual_first_image'],
            existing_coverage_review=row['coverage_review'],
            existing_observation_is_not_new_opening_approval=True,
        ))
    derived = _freeze(out / 'SOURCE_CASE.json', dict(schema=core.SCHEMA, shots=rows))
    contracts_binding = _freeze(out / 'OPENING_CONTRACTS.json', dict(
        schema='h3_story_opening_contracts/v1', source=source_binding,
        derived_source=derived, first_frame_policy=opening.POLICY,
        shots=contracts, model_calls=0, production_approved=False,
    ))
    staging = spatial.prepare(out / 'spatial', spec_path=out / 'SOURCE_CASE.json',
                              first_frame_policy=opening.POLICY)
    if core.binding(source) != source_binding:
        raise ValueError('original_source_changed_during_preparation')
    report = dict(
        schema='h3_story_opening_plan_report/v1', status='opening_planning_prepared',
        source=source_binding, derived_source=derived,
        opening_contracts=contracts_binding, first_frame_policy=opening.POLICY,
        spatial=staging, shots=summaries, model_calls=0, http_calls=0,
        media_dispatched=False, no_video_trim=True,
        new_image_observation_created=False, production_approved=False,
        next='Render new opening stages, generate new first images, and observe those actual images against the opening contracts before any video dispatch. Existing coverage reviews are preserved context, not new approval.',
        scheduler_limit='The v34 scheduler retains its source-state, image and dispatch review gates; this preparation does not implement an unattended visual-review loop.',
    )
    _freeze(out / 'PLAN_REPORT.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=['prepare'], default='prepare')
    parser.add_argument('--source', type=Path, default=spatial.SPEC,
                        help='Existing v33 source SPEC; all original bindings remain unchanged.')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                        help='Separate output root; conflicting existing records are rejected.')
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.source, args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
