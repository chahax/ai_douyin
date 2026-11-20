"""Retain an incomplete local response before the caller rejects its contract."""
def native_response(*,text,token_ids,prompt_tokens,eos_token_ids,output_limit,model,seconds,image_count,quantization):
    from .visual_asset_review_v3 import ReviewProtocolError
    ids=list(map(int,token_ids));eos=list(map(int,eos_token_ids))
    completed=bool(ids) and ids[-1] in eos
    value=dict(text=text,model=model,usage=dict(prompt_tokens=int(prompt_tokens),completion_tokens=len(ids)),
        seconds=seconds,image_count=image_count,quantization=quantization,
        finish_reason='stop' if completed else 'max_tokens' if len(ids)>=output_limit else 'missing_completion_marker',
        completion_marker_present=completed,output_limit=output_limit,
        last_token_id=ids[-1] if ids else None,eos_token_ids=eos)
    if not completed:
        error=ReviewProtocolError('local visual output exhausted limit without completion marker')
        error.native_response=value
        raise error
    return value
