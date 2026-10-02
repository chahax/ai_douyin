"""Local objective audio features and emotion2vec hypotheses for a frozen cohort."""
import argparse, json, sys, math
from pathlib import Path
from datetime import datetime, timezone, timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.trend_intelligence.narrative_workflow import digest


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('sources');p.add_argument('output');a=p.parse_args()
    out=Path(a.output);out.mkdir(exist_ok=False)
    sources={s['source_id']:s for s in json.loads(Path(a.sources).read_text(encoding='utf-8'))}
    rows=json.loads(Path(a.manifest).read_text(encoding='utf-8'))['items']
    import numpy as np, soundfile as sf
    from funasr import AutoModel
    model=AutoModel(model=str(ROOT/'.local_models/video_analysis/emotion2vec_plus_large'),device='cuda',disable_update=True)
    for row in rows:
        s=sources[row['item_id']];t=json.loads(Path(row['transcript']).read_text(encoding='utf-8'));pr=t['provenance'];wav=Path(pr['audio_path'])
        if pr['source_video_sha256']!=s['media_evidence']['source_video_sha256'] or digest(wav)!=pr['audio_sha256']:raise ValueError('Audio identity changed')
        samples,sr=sf.read(wav,dtype='float32')
        if samples.ndim>1:samples=samples.mean(axis=1)
        results=[]
        for start in range(0,len(samples),sr*8):
            chunk=samples[start:start+sr*8]
            if len(chunk)<sr//4:continue
            pred=model.generate(input=chunk,fs=sr,granularity='utterance',extract_embedding=False)
            rms=float(np.sqrt(np.mean(chunk.astype('float64')**2)))
            results.append({'start':start/sr,'end':min(start+sr*8,len(samples))/sr,'rms_dbfs':round(20*math.log10(max(rms,1e-10)),2),'classifier':pred})
        report={'schema':'cohort_local_acoustics/v1','source_id':row['item_id'],'created_at_bjt':datetime.now(timezone(timedelta(hours=8))).isoformat(),
          'source_video_sha256':pr['source_video_sha256'],'audio_path':str(wav),'audio_sha256':pr['audio_sha256'],'sample_rate':sr,'windows':results,
          'limitations':['RMS measures mixed audio amplitude, not vocal anger or perceived loudness.','Emotion2vec scores are classifier hypotheses, not calibrated probabilities or verified acting emotions.','No external audio upload; ASR density is not measured articulation speed.'],'external_media_upload':False}
        (out/(row['video_id']+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda v:v.tolist()),encoding='utf-8')
        print(row['item_id']+' acoustic windows '+str(len(results)),flush=True)


if __name__=='__main__':main()
