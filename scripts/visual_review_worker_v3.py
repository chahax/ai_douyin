"""Short-lived offline Qwen3-VL worker. Loads once; source-bound per-item receipts.

The caller owns the GPU lease. This worker never starts services, installs packages,
downloads weights, generates assets, or touches an existing video batch.
"""
from __future__ import annotations
import argparse
import gc
import io
import json
import os
from pathlib import Path
import sys
import time

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from src.content_factory.visual_asset_review_v3 import (
    _read, _write, _png, _review_one, _unavailable, _unchanged, model_binding,
    ReviewProtocolError, ReviewUnavailable, DEFAULT_MODEL, digest, _verify_roi_artifacts,
)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); request=_read(args.request); config=request['config']
    if request.get('review_mode'):
        from src.content_factory import visual_residence_review_v5 as style
        if request['review_mode']!=style.VERSION:
            from src.content_factory import visual_residence_appearance_v6 as appearance
            if request['review_mode']!=appearance.VERSION:
                from src.content_factory import visual_known_capacity_extension_v17 as capacity
                if request['review_mode']!=capacity.VERSION:
                    from src.content_factory import visual_room_contract_successor_v18 as compact_successor
                    if request['review_mode']!=compact_successor.VERSION:raise ValueError('unknown visual review mode')
                    style=compact_successor
                else:style=capacity
            else:style=appearance
        check_unchanged,review_one,unavailable=style._unchanged,style._review_one,style._unavailable
    else:
        check_unchanged,review_one,unavailable=_unchanged,_review_one,_unavailable
    folder=args.output.parent.resolve()
    if args.output.resolve()!=folder/'RESULTS.json' or args.request.resolve()!=folder/'REQUEST.json':
        raise ValueError('worker only accepts the job evidence layout')
    if args.output.exists():raise ValueError('completed output retained, no overwrite')
    expected=request['model_binding'];actual=model_binding(config.get('model_path',DEFAULT_MODEL))
    if any(expected.get(k)!=v for k,v in actual.items()):raise ValueError('visual model changed before loading')
    if not _read(folder/'CLAIM.json')['request_binding_sha256']==request['request_binding_sha256']:
        raise ValueError('worker claim mismatch')
    from src.content_factory import visual_worker_runtime_v6 as worker_runtime
    worker_runtime.save_runtime(folder,request['request_binding_sha256'])
    for p in request['prepared']:check_unchanged(p)
    _write(folder/'WORKER_STATE.json',dict(pid=os.getpid(),stage='loading',at=time.time()))
    model=processor=torch=None;inference_calls=0
    try:
        from src.trend_intelligence.content_analysis.resource_policy import probe_resources
        resources=probe_resources()
        if (resources['available_ram_gib']<6 or resources['available_vram_gib'] is None
                or resources['available_vram_gib']<5):
            raise ReviewUnavailable('local vision resources insufficient; need >=6GiB free RAM and >=5GiB VRAM')
        import torch
        from PIL import Image
        from transformers import AutoProcessor,Qwen3VLForConditionalGeneration,BitsAndBytesConfig
        if not torch.cuda.is_available():raise ReviewUnavailable('local vision CUDA unavailable')
        torch.set_num_threads(2);torch.manual_seed(0)
        path=actual['model'];processor=AutoProcessor.from_pretrained(path,local_files_only=True)
        processor.image_processor.size={'shortest_edge':65536,'longest_edge':config.get('image_max_pixels',262144)}
        quant=config.get('quantization','nf4')
        options={}
        if quant=='nf4':
            options['quantization_config']=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16)
        elif quant!='bf16':raise ValueError('unsupported local vision quantization')
        model=Qwen3VLForConditionalGeneration.from_pretrained(path,dtype=torch.bfloat16,
            device_map='cuda:0',local_files_only=True,low_cpu_mem_usage=True,attn_implementation='sdpa',**options).eval()
        _write(folder/'WORKER_STATE.json',dict(pid=os.getpid(),stage='ready',at=time.time(),quantization=quant,model_binding=actual,resources_before_load=resources))
        def infer(payload):
            nonlocal inference_calls
            content=[dict(type='text',text=payload['prompt']+'\nJSON_SCHEMA:\n'+json.dumps(payload['schema'],ensure_ascii=False))]
            for spec in payload['images']:
                content.append(dict(type='text',text='Image role: '+spec['role']))
                content.append(dict(type='image',image=Image.open(io.BytesIO(_png(spec))).convert('RGB')))
            started=time.monotonic()
            inputs=processor.apply_chat_template([dict(role='user',content=content)],tokenize=True,
                add_generation_prompt=True,return_dict=True,return_tensors='pt').to(model.device)
            if inputs.input_ids.shape[-1]>12288:raise ReviewProtocolError('visual input capacity exceeded')
            inference_calls+=1
            with torch.inference_mode():
                output=model.generate(**inputs,max_new_tokens=config.get('max_tokens',1800),do_sample=False,use_cache=True)
            generated=output[0,inputs.input_ids.shape[-1]:]
            eos=model.generation_config.eos_token_id
            eos=[eos] if isinstance(eos,int) else eos or []
            text=processor.tokenizer.decode(generated,skip_special_tokens=True)
            from src.content_factory.visual_review_output_v17 import native_response
            return native_response(text=text,token_ids=generated.tolist(),prompt_tokens=int(inputs.input_ids.shape[-1]),
                eos_token_ids=eos,output_limit=config.get('max_tokens',1800),model=actual['model'],
                seconds=round(time.monotonic()-started,3),image_count=len(payload['images']),quantization=quant)
        results=[]
        for i,prepared in enumerate(request['prepared']):
            item=folder/f'item_{i:04}';item.mkdir(exist_ok=True)
            saved=item/'RESULT.json'
            # Resume keeps completed native-bound items; it never silently repeats them.
            if saved.exists():
                result=_read(saved)
                if result.get('binding_sha256')!=digest(prepared):raise ValueError('saved review binding changed')
                check_unchanged(prepared)
                if prepared.get('reference_roi_evidence'):_verify_roi_artifacts(prepared,item,result)
            else:
                _write(folder/'WORKER_STATE.json',dict(pid=os.getpid(),stage='reviewing',item=i,at=time.time()))
                try:result=review_one(prepared,infer,expected,item)
                except (OSError,ValueError,KeyError,ReviewUnavailable) as error:result=unavailable(prepared,error,expected)
                _write(saved,result)
            results.append(result)
        if model_binding(path)!=actual:raise ValueError('model files changed during inference')
        for p in request['prepared']:check_unchanged(p)
        _write(args.output,dict(request_binding_sha256=request['request_binding_sha256'],results_sha256=digest(results),results=results))
        _write(folder/'WORKER_STATE.json',dict(pid=os.getpid(),stage='completed',at=time.time(),items=len(results)))
        print('Visual reviews saved:',len(results),flush=True)
        return 0
    except Exception as error:
        _write(folder/'WORKER_FAILURE.json',dict(type=type(error).__name__,message=str(error),at=time.time(),inference_calls=inference_calls))
        print(type(error).__name__+': '+str(error),flush=True)
        return 2
    finally:
        model=processor=None;gc.collect()
        if torch is not None:torch.cuda.empty_cache()


if __name__=='__main__':raise SystemExit(main())
