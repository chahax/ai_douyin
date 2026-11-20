"""Prepare a source-faithful two-person opening after the four-person candidate."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_image_jobs_v3 as jobs
from src.content_factory import visual_asset_feature_cards_v1 as features
from prepare_h3_continuation_scene_stage import build_graph, RUN, PREVIOUS, ASSETS

REFERENCES=(
    ('children_room','front','3ecd2f25a1239422641b21e44664e50b_v2.png'),
    ('children_room','side','01e90320888fdadf1431ba33c3e9f98d_v1.png'),
    ('ye_yaner','front','fb87c343c91175a9b9534efd082d2b94_v1.png'),
    ('ye_xijue','front','c961d00790d5975b2bff11f4975fcb46_v1.png'),
)
PROMPT="""Edit Image1 into a candid photographic medium two-shot at the wooden bed in the children's shared bedroom. Image1 and Image2 show this same room from two viewpoints; keep the worn gray painted walls, cracked concrete floor, wooden beds with plain bedding, old wooden stool and square ceiling light.
Image3 identifies Ye Yaner, a young Chinese girl with two neatly tied small pigtails, the same delicate round-oval face, pale small-floral cotton dress, white ankle socks and old black shoes. Image4 identifies Ye Xijue, a young Chinese boy with the same round face and short black fringe, old worn beige cotton short-sleeve shirt and gray knee-length shorts. These are two different siblings.
Ye Xijue is seated at the wooden bed edge on the left of the composition, shown from head through knees, his brows pinched with discomfort and jaw held tense. His beige shirt is lifted slightly at his side, only enough for a small non-graphic bruise to be gently dabbed. Ye Yaner kneels at the bed edge beside him on the right, shown from head through waist, facing him and looking with concern at the small treatment action. She gently supports his arm with one hand and holds one small cotton swab with the other. One nearly empty small iodine bottle is on the old wooden stool beside her. The girl is the caregiver and the short-haired beige-shirt boy is receiving care. Their faces, hair and clothing remain their own matching identities from Images3 and4. The frame captures the instant before she softly asks him about the pain, their attention on each other and on the cotton swab. Natural real skin, everyday family-drama photography, coherent hands and anatomy, realistic photographic light and room materials."""


def prepare():
    graph,_,job_id=build_graph(RUN)
    for key in list(graph):
        if any(key.startswith('initial__'+p) for p in ('image_','encode_','positive_ref_','negative_ref_')):del graph[key]
    inputs=[]
    for i,(_,_,name) in enumerate(REFERENCES):
        image=features.bind(ASSETS/name);input_name=f'library_next_minute/{RUN.name}/children_focus/reference_{i+1}.png'
        inputs.append(dict(input_name=input_name,**image))
        graph[f'initial__image_{i}']=dict(class_type='LoadImage',inputs=dict(image=input_name))
        graph[f'initial__encode_{i}']=dict(class_type='VAEEncode',inputs=dict(pixels=[f'initial__image_{i}',0],vae=['vae',0]))
        for polarity in ('positive','negative'):
            prev=f'initial__{polarity}' if i==0 else f'initial__{polarity}_ref_{i-1}'
            graph[f'initial__{polarity}_ref_{i}']=dict(class_type='ReferenceLatent',inputs=dict(conditioning=[prev,0],latent=[f'initial__encode_{i}',0]))
    graph['initial__positive']['inputs']['text']=PROMPT
    graph['initial__noise']['inputs']['noise_seed']=202611130603
    for polarity in ('positive','negative'):graph['initial__guider']['inputs'][polarity]=[f'initial__{polarity}_ref_3',0]
    graph['initial__save']['inputs']['filename_prefix']='visual_assets_v3/'+job_id+'/children_focus'
    folder=RUN/'scene_stages/children_room_start/A02'
    features.freeze(folder/'SOURCE_REFERENCES.json',dict(schema='library_scene_start_references/v1',references=[dict(entity_id=e,view=v,image=features.bind(ASSETS/name)) for e,v,name in REFERENCES],
        source_selection=features.bind(RUN/'script_selection.json'),construction_code=features.bind(__file__),
        earlier_candidate=features.bind(RUN/'scene_stages/children_room_start/SCENE_GUIDE.json'),
        decision='Source camera opening focuses on treatment pair; other two brothers remain full-clip actors in every video packet. This image does not claim they appear in the opening frame.',production_approved=False))
    config=features.read(PREVIOUS/'initial_scene/job/PLAN.json')['config']
    return jobs.prepare_job(folder/'job',graph,config,inputs=inputs,job_id=job_id)


if __name__=='__main__':print(json.dumps(prepare(),ensure_ascii=False,indent=2))
