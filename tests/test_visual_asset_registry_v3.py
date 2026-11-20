from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
from PIL.PngImagePlugin import PngInfo
import pytest

from src.content_factory import visual_asset_registry_v3 as a


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def image(path, color='gray', graph=None):
    metadata=PngInfo()
    if graph is not None:metadata.add_text('prompt',json.dumps(graph))
    Image.new('RGB',(32,48),color).save(path,pnginfo=metadata)
    return path


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def register(tmp_path, color='gray', **kwargs):
    source=image(tmp_path/(color+'.png'),color)
    params=dict(book_id='book1',entity_id='actor',kind='character',view='front',
                design_version='design1',input_sha256='a'*64,expected_sha256=sha(source))
    params.update(kwargs)
    return a.register(tmp_path/'library',source,**params)


def review(tmp_path,row,decision='accepted',**kwargs):
    params=dict(book_id=row['book_id'],asset_id=row['asset_id'],version=row['version'],
        file_sha256=row['sha256'],decision=decision,reviewer='vision-test-model',
        checks={k:True for k in a.REVIEW_CHECKS[row['kind']]},
        evidence=dict(image_sha256=row['sha256'],observations=['actually inspected subject and reference']))
    params.update(kwargs)
    return a.review(tmp_path/'library',**params)


def test_readonly_missing_library_does_not_create(tmp_path):
    folder=tmp_path/'absent'
    assert a.get(folder,book_id='book1')==[]
    result=a.requirements_status(folder,book_id='book1',requirements=[dict(entity_id='actor')])
    assert not result['ready'] and len(result['missing'])==9
    assert not folder.exists()


def test_same_design_input_output_registration_is_idempotent(tmp_path):
    row=register(tmp_path)
    before=(tmp_path/'library/INDEX.json').read_bytes()
    again=register(tmp_path)
    assert (again['asset_id'],again['version'])==(row['asset_id'],1)
    assert (tmp_path/'library/INDEX.json').read_bytes()==before
    assert len(a.get(tmp_path/'library',book_id='book1'))==1


def test_new_content_and_upstream_input_have_immutable_versions(tmp_path):
    row=register(tmp_path);second=register(tmp_path,'red')
    third=register(tmp_path,'red',input_sha256='b'*64)
    assert {r['asset_id'] for r in [row,second,third]}=={row['asset_id']}
    assert [r['version'] for r in a.get(tmp_path/'library',book_id='book1')]==[1,2,3]
    assert sha(Path(row['path']))==row['sha256']
    assert a.get(tmp_path/'library',book_id='book1',version=2)[0]['file']==third['file']


def test_wrong_expected_sha_never_creates_library(tmp_path):
    source=image(tmp_path/'source.png')
    with pytest.raises(ValueError,match='sha_mismatch'):
        a.register(tmp_path/'library',source,book_id='b',entity_id='a',kind='character',view='front',expected_sha256='f'*64)
    assert not (tmp_path/'library').exists()


def test_cross_book_get_and_review_are_rejected(tmp_path):
    row=register(tmp_path)
    assert a.get(tmp_path/'library',book_id='other',entity_id='actor')==[]
    with pytest.raises(ValueError,match='scope'):
        a.get(tmp_path/'library',book_id='other',asset_id=row['asset_id'])
    with pytest.raises(ValueError,match='scope'):
        review(tmp_path,row,book_id='other')


def test_exact_views_aliases_and_twins_separate_roles(tmp_path):
    front=register(tmp_path,entity_id='twin_a',identity_group='twins')
    other=register(tmp_path,entity_id='twin_b',identity_group='twins')
    face=register(tmp_path,entity_id='twin_b',identity_group='twins',view='face_detail')
    assert front['asset_id']!=other['asset_id'] and front['identity_group']==other['identity_group']
    assert a.get(tmp_path/'library',book_id='book1',entity_id='twin_b',view='face')[0]['asset_id']==face['asset_id']
    assert a.get(tmp_path/'library',book_id='book1',entity_id='twin_a',view='face')==[]
    with pytest.raises(ValueError,match='unsupported_character_view'):register(tmp_path,view='side_full')


def test_review_is_bound_append_only_and_cannot_replay_old_acceptance(tmp_path):
    row=register(tmp_path);original=(tmp_path/'library'/f"{row['asset_id']}_v1.json").read_bytes()
    accepted=review(tmp_path,row)
    assert accepted['status']=='reviewed' and not accepted['production_approved']
    assert review(tmp_path,row,decision='unavailable',checks={},evidence={'reason':'provider unavailable'})['status']=='candidate'
    assert review(tmp_path,row)['status']=='candidate'  # Old same event is not a fresh re-review.
    assert (tmp_path/'library'/f"{row['asset_id']}_v1.json").read_bytes()==original
    assert len(json.loads((tmp_path/'library/INDEX.json').read_text())['reviews'])==2


@pytest.mark.parametrize('override',[
    {'file_sha256':'f'*64}, {'input_sha256':'f'*64}, {'target':'wrong'},
    {'checks':{'identity':True}}, {'checks':{'identity':1}},
    {'evidence':{'observations':['x'],'image_sha256':'f'*64}},
    {'evidence':{'image_sha256':'invalid','observations':[]}},
])
def test_stale_or_structural_only_review_cannot_qualify(tmp_path,override):
    row=register(tmp_path)
    with pytest.raises(ValueError):review(tmp_path,row,**override)
    assert a.get(tmp_path/'library',book_id='book1')[0]['status']=='candidate'


def test_new_candidate_does_not_fall_back_to_old_reviewed(tmp_path):
    old=register(tmp_path);review(tmp_path,old);register(tmp_path,'red')
    result=a.requirements_status(tmp_path/'library',book_id='book1',requirements=[dict(entity_id='actor',view='front',design_version='design1')])
    assert not result['ready'] and result['pending'][0]['version']==2 and not result['selected']


def test_tampered_asset_or_review_is_not_read_as_ready(tmp_path):
    row=register(tmp_path);accepted=review(tmp_path,row)
    e=tmp_path/'library/reviews'/f"{accepted['review']['review_id']}.json"
    e.write_text('{}')
    with pytest.raises(ValueError,match='review_record'):a.get(tmp_path/'library',book_id='book1')
    # A separate library copy of a changed image is also rejected.
    another=register(tmp_path,'red',entity_id='second')
    image(Path(another['path']),'green')
    with pytest.raises(ValueError,match='file_changed'):a.get(tmp_path/'library',book_id='book1',entity_id='second')


def test_review_receipt_survives_interrupted_index_commit(tmp_path,monkeypatch):
    row=register(tmp_path);original=a._atomic
    def interrupted(*args,**kwargs):raise OSError('simulated commit interruption')
    monkeypatch.setattr(a,'_atomic',interrupted)
    with pytest.raises(OSError):review(tmp_path,row)
    assert a.get(tmp_path/'library',book_id='book1')[0]['status']=='candidate'
    monkeypatch.setattr(a,'_atomic',original)
    assert review(tmp_path,row)['status']=='reviewed'
    assert len(list((tmp_path/'library/reviews').glob('*.json')))==1


def test_index_asset_id_traversal_rejected_even_without_hash_reads(tmp_path):
    register(tmp_path);path=tmp_path/'library/INDEX.json';v=json.loads(path.read_text())
    v['assets'][0]['asset_id']='../escape';write(path,v)
    with pytest.raises(ValueError,match='invalid_asset_version'):
        a.get(tmp_path/'library',book_id='book1',verify_file=False)


def test_old_v2_index_read_is_candidate_and_reuses_existing_blob(tmp_path):
    lib=tmp_path/'library';lib.mkdir();p=image(lib/'old_v1.png')
    old=dict(asset_id='old',version=1,book_id='book1',entity_id='actor',kind='character',view='front_full',file=p.name,sha256=sha(p))
    write(lib/'INDEX.json',{'assets':[old]});write(lib/'old_v1.json',old)
    before=(lib/'INDEX.json').read_bytes()
    result=a.get(lib,book_id='book1',view='front')
    assert result[0]['status']=='candidate' and result[0]['design_version']=='legacy'
    assert (lib/'INDEX.json').read_bytes()==before
    newer=a.register(lib,p,book_id='book1',entity_id='actor',kind='character',view='front',design_version='design1')
    assert newer['version']==2 and newer['file']=='old_v1.png'


def test_concurrent_processes_register_once(tmp_path):
    source=image(tmp_path/'source.png')
    code="from src.content_factory.visual_asset_registry_v3 import register;import sys;print(register(sys.argv[1],sys.argv[2],book_id='book',entity_id='actor',kind='character',view='front')['version'])"
    root=Path(__file__).resolve().parents[1]
    processes=[subprocess.Popen([sys.executable,'-B','-c',code,str(tmp_path/'library'),str(source)],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
    for process in processes:
        out,err=process.communicate(timeout=30)
        assert process.returncode==0,err
        assert out.strip()=='1'
    assert len(a.get(tmp_path/'library',book_id='book'))==1


def native_manifest(tmp_path):
    root=tmp_path/'cast';root.mkdir();source=root/'SCRIPT.md';source.write_text('source',encoding='utf-8')
    graph={'save_'+v:{'class_type':'SaveImage','inputs':{}} for v in a.CHARACTER_VIEWS}
    case=root/'cases/batch';case.mkdir(parents=True);wf=case/'workflow_api.json';write(wf,graph)
    items=[];outputs={}
    for n,view in enumerate(a.CHARACTER_VIEWS):
        original=image(case/(view+'.png'),(20*n,50,90),graph)
        output=root/(view+'.png');output.write_bytes(original.read_bytes())
        node='save_'+view;outputs[node]={'images':[dict(filename=original.name,type='output')]}
        items.append(dict(character_id='actor',view=view,identity_group='twins',path=str(output),sha256=sha(output),
            original_generated_path=str(original),execution_case='batch',prompt_id='original',save_node=node,
            workflow_path=str(wf),workflow_sha256=sha(wf),seed=n,prompt='same person',production_approved=False))
    write(case/'HISTORY.json',{'original':dict(prompt=[1,'client',graph],status=dict(completed=True,status_str='success'),outputs=outputs)})
    manifest=dict(selected_images=9,characters=1,source_script=dict(path=str(source),sha256=sha(source)),items=items)
    file=root/'FINAL_MAP.json';write(file,manifest)
    return file,manifest


def test_real_shape_native_manifest_import_twice_stays_candidate(tmp_path):
    path,manifest=native_manifest(tmp_path);lib=tmp_path/'library'
    first=a.import_manifest(lib,path,book_id='book1');second=a.import_manifest(lib,path,book_id='book1')
    assert first['created_count']==9 and second['created_count']==0 and second['reused_count']==9
    assert all(r['status']=='candidate' and not r['production_approved'] for r in first['assets'])
    status=a.requirements_status(lib,book_id='book1',requirements=[dict(entity_id='actor',design_version='v1')])
    assert status['complete'] and not status['ready'] and len(status['pending'])==9


def test_changed_source_facts_create_candidate_versions_without_inheriting_review(tmp_path):
    path,m=native_manifest(tmp_path);lib=tmp_path/'library'
    first=a.import_manifest(lib,path,book_id='book1')
    for row in first['assets']:review(tmp_path,row)
    assert a.requirements_status(lib,book_id='book1',requirements=[dict(entity_id='actor')])['ready']
    Path(m['source_script']['path']).write_text('new source revision',encoding='utf-8')
    m['source_script']['sha256']=sha(Path(m['source_script']['path']));write(path,m)
    next_version=a.import_manifest(lib,path,book_id='book1')
    assert next_version['created_count']==9 and all(x['version']==2 for x in next_version['assets'])
    result=a.requirements_status(lib,book_id='book1',requirements=[dict(entity_id='actor')])
    assert not result['ready'] and all(x['version']==2 for x in result['pending'])


@pytest.mark.parametrize('defect',['missing_view','duplicate_view','changed_source','changed_workflow','wrong_save_node','wrong_native_status','wrong_native_png','wrong_fact_quote'])
def test_invalid_manifest_has_no_partial_registration(tmp_path,defect):
    path,m=native_manifest(tmp_path)
    if defect=='missing_view':m['items'].pop();m['selected_images']=8
    elif defect=='duplicate_view':m['items'][-1]['view']='front'
    elif defect=='changed_source':Path(m['source_script']['path']).write_text('changed')
    elif defect=='changed_workflow':Path(m['items'][0]['workflow_path']).write_text('{}')
    elif defect=='wrong_save_node':m['items'][0]['save_node']='unknown'
    elif defect=='wrong_native_status':
        h=path.parent/'cases/batch/HISTORY.json';v=json.loads(h.read_text());v['original']['status']['status_str']='error';write(h,v)
    elif defect=='wrong_fact_quote':
        m['items'][0]['source_facts']=dict(script=m['source_script']['path'],start=0,end=3,quote='fabricated')
    else:
        e=m['items'][0];image(Path(e['original_generated_path']),'red',{'fake':{}})
        Path(e['path']).write_bytes(Path(e['original_generated_path']).read_bytes());e['sha256']=sha(Path(e['path']))
    write(path,m)
    with pytest.raises(ValueError):a.import_manifest(tmp_path/'library',path,book_id='book1')
    assert not (tmp_path/'library').exists()


def test_place_review_has_layout_checks_instead_of_human_anatomy(tmp_path):
    row=register(tmp_path,kind='place',view='layout')
    accepted=review(tmp_path,row)
    assert accepted['status']=='reviewed'
