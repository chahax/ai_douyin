"""Prepare one library-referenced children-room scene start, without submitting."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_image_jobs_v3 as jobs
from src.content_factory import visual_asset_feature_cards_v1 as features

PROJECT = Path(__file__).resolve().parents[1]
RUN = PROJECT / 'data/video_generation/h3_library_bound_next_minute_20261113_v1'
PREVIOUS = PROJECT / 'data/video_generation/h3_library_bound_minute_20261112_v1'
ASSETS = PROJECT / 'data/serial_story_assets'
REFERENCES = (
    ('children_room', 'front', '3ecd2f25a1239422641b21e44664e50b_v2.png'),
    ('children_room', 'side', '01e90320888fdadf1431ba33c3e9f98d_v1.png'),
    ('ye_dong', 'front', '91247396f8a4ff737220c17f59b8abfb_v1.png'),
    ('ye_nan', 'front', '131fdd0b6c917c1cee40301d89958c5e_v1.png'),
    ('ye_yaner', 'front', 'fb87c343c91175a9b9534efd082d2b94_v1.png'),
    ('ye_xijue', 'front', 'c961d00790d5975b2bff11f4975fcb46_v1.png'),
)

PROMPT = """Edit Image1 into the first instant of a live-action Chinese family drama in the children's shared bedroom. Image1 and Image2 are two views of this same children's bedroom, with the same worn gray walls, cracked concrete floor, square ceiling lamp, wooden beds and plain bedding, old wooden table and stools. Use their same furniture, materials, and layout as the environment.
Image3 identifies Ye Dong, the eldest boy: the same angular-oval face, short rough black hair, faded dusty blue oversized short-sleeve cotton shirt and old charcoal trousers. Image4 identifies Ye Nan, his younger brother: the same narrow oval face, side-swept black fringe, brown-gray short-sleeve collared cotton shirt and old dark gray-green trousers. Image5 identifies Ye Yaner, their sister: the same round-oval child face, neatly tied small pigtails, faded pale small-floral cotton dress, white ankle socks and old black shoes. Image6 identifies Ye Xijue, the youngest boy: the same round youthful face, soft black fringe, old beige short-sleeve shirt with worn seams and gray knee-length shorts.
Compose a candid medium-wide view of these four distinct siblings in their room. Ye Xijue sits at the edge of a wooden bed, with his beige shirt lifted only slightly at the side for a tiny bruise to be gently dabbed. Ye Yaner kneels at the bed edge beside him, gently supporting his arm with one hand and holding a small cotton swab with the other, her brows knit with concern. A nearly empty small iodine bottle rests on the old wooden stool beside her. Ye Dong stands farther back near the room's exit, shoulders tense and hands held close to his sides, watching his youngest brother with anger and concern. Ye Nan stands nearby watching the treatment, worried. Their attention and shoulders turn toward each other and toward the small treatment action, as an observed family moment. The faces remain distinct and match their own individual reference images. Natural photographic light and skin, realistic everyday clothing, clear continuous anatomy. This photograph establishes the moment before Ye Yaner softly asks her brother about the pain."""


def build_graph(run=RUN):
    run = Path(run).resolve()
    old = json.loads((PREVIOUS / 'initial_scene/job/workflow_api.json').read_text(encoding='utf-8'))
    graph = {k: deepcopy(old[k]) for k in ('unet', 'clip', 'vae', 'sampler')}
    # This uses the same known native Klein graph as the prior opening, with six
    # independently staged assets instead of substituting a group portrait.
    for k, node in old.items():
        if k.startswith('initial__') and not any(k.startswith('initial__'+prefix) for prefix in
                ('image_', 'encode_', 'positive_ref_', 'negative_ref_')):
            graph[k] = deepcopy(node)
    graph['initial__positive']['inputs']['text'] = PROMPT
    graph['initial__noise']['inputs']['noise_seed'] = 202611130602
    inputs = []
    for i, (entity, view, name) in enumerate(REFERENCES):
        image = features.bind(ASSETS / name)
        input_name = f'library_next_minute/{run.name}/children_start/reference_{i+1}.png'
        inputs.append(dict(input_name=input_name, **image))
        graph[f'initial__image_{i}'] = dict(class_type='LoadImage', inputs=dict(image=input_name))
        graph[f'initial__encode_{i}'] = dict(class_type='VAEEncode', inputs=dict(pixels=[f'initial__image_{i}', 0], vae=['vae', 0]))
        for polarity in ('positive', 'negative'):
            previous = f'initial__{polarity}' if i == 0 else f'initial__{polarity}_ref_{i-1}'
            graph[f'initial__{polarity}_ref_{i}'] = dict(class_type='ReferenceLatent', inputs=dict(
                conditioning=[previous, 0], latent=[f'initial__encode_{i}', 0]))
    for polarity in ('positive', 'negative'):
        graph['initial__guider']['inputs'][polarity] = [f'initial__{polarity}_ref_{len(inputs)-1}', 0]
    job_id = run.name + '_children_start'
    graph['initial__save']['inputs']['filename_prefix'] = 'visual_assets_v3/' + job_id + '/children_start'
    assert len({x['sha256'] for x in inputs}) == 6
    assert len([v for v in graph.values() if v['class_type'] == 'LoadImage']) == 6
    return graph, inputs, job_id


def prepare(run=RUN):
    run = Path(run).resolve()
    graph, inputs, job_id = build_graph(run)
    config = json.loads((PREVIOUS / 'initial_scene/job/PLAN.json').read_text(encoding='utf-8'))['config']
    folder = run / 'scene_stages/children_room_start'
    features.freeze(folder / 'SOURCE_REFERENCES.json', dict(
        schema='library_scene_start_references/v1', references=[dict(entity_id=e, view=v, image=features.bind(ASSETS/n)) for e,v,n in REFERENCES],
        screenplay_selection=features.bind(run/'script_selection.json'), previous_template=features.bind(PREVIOUS/'initial_scene/job/workflow_api.json'),
        construction_code=features.bind(__file__), native_image_calls_requested=1, media_posts=0, production_approved=False))
    return jobs.prepare_job(folder/'job', graph, config, inputs=inputs, job_id=job_id)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,default=RUN);a=p.parse_args()
    if a.run.resolve()!=RUN.resolve():p.error('only explicitly authorized next-minute run')
    print(json.dumps(prepare(a.run),ensure_ascii=False,indent=2))
