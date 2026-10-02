"""Independent local acoustic emotion evidence; no approval or external upload."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory import video_campaign as c


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',action='append',required=True)
    parser.add_argument('--model',default='.local_models/video_analysis/emotion2vec_plus_large')
    args=parser.parse_args();model_path=Path(args.model).resolve()
    if not (model_path/'model.pt').is_file():raise ValueError('Download the model first')
    jobs=[]
    for name in args.run_dir:
        folder=Path(name).resolve();m=c.read(folder/'production.json');shot=m['test_shot'];r=c.read(folder/(shot+'.json'))
        packet_path=Path(r['review_packet']);packet=c.read(packet_path);wav=packet_path.parent/packet['audio'];output=folder/(shot+'.speech_emotion.json')
        if output.exists():raise ValueError('Preserve existing emotion evidence')
        evidence=next(e for e in packet['evidence'] if e['file']==packet['audio'])
        if c.file_sha(r['local_video'])!=r['video_sha256'] or c.file_sha(wav)!=evidence['sha256']:
            raise ValueError('Original audio/video bytes changed')
        jobs.append((r,wav,output))
    from funasr import AutoModel
    import soundfile as sf
    model=AutoModel(model=str(model_path),device='cuda',disable_update=True)
    for r,wav,output in jobs:
        samples,sr=sf.read(wav,dtype='float32')
        windows=[(0.,len(samples)/sr)]+[(float(start),min(float(start+3),len(samples)/sr)) for start in range(0,int(len(samples)/sr),3)]
        results=[]
        for start,end in windows:
            if end-start<1:continue
            res=model.generate(input=samples[int(start*sr):int(end*sr)],fs=sr,granularity='utterance',extract_embedding=False)
            results.append({'start_seconds':start,'end_seconds':end,'result':res})
        report={'schema':'local_speech_emotion_evidence/v1','created_at_bjt':c.beijing_now(),
                'source_video':r['local_video'],'source_sha256':r['video_sha256'],'audio':str(wav),'audio_sha256':c.file_sha(wav),
                'model':str(model_path),'model_sha256':c.file_sha(model_path/'model.pt'),'results':results,
                'external_media_upload':False,'automatic_campaign_approval':False,
                'limitations':'Classifier scores are model evidence, not calibrated probabilities or proof of acting quality, speaker identity or lip-sync.'}
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda x:x.tolist()),encoding='utf8')
        print(str(output),flush=True)


if __name__=='__main__':main()
