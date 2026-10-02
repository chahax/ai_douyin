"""One recorded text-model diagnostic; redact credentials before saving errors."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.shared.llm_providers.openai_compatible_provider import OpenAICompatibleProvider
from scripts.test_director_pipeline import author_stage

def main():
    source=Path(sys.argv[1]).resolve()
    output=Path(sys.argv[2]).resolve()
    original=OpenAICompatibleProvider.__init__
    def instrument(self,*args,**kwargs):
        original(self,*args,**kwargs)
        invoke=self.client.chat.completions.create
        def diagnostic(*a,**k):
            try:
                return invoke(*a,**k)
            except Exception as exc:
                body=getattr(exc,'body',None)
                err=body.get('error',body) if isinstance(body,dict) else {}
                message=str(err.get('message','')) if isinstance(err,dict) else str(err)
                for secret in (getattr(self.client,'api_key',None), str(getattr(self.client,'base_url',''))):
                    if secret:
                        message=message.replace(secret,'[REDACTED]')
                record={'type':type(exc).__name__,'status':getattr(exc,'status_code',None),'message':message[:1000]}
                (output/'diagnostic.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
                raise
        self.client.chat.completions.create=diagnostic
    OpenAICompatibleProvider.__init__=instrument
    messages=json.loads(source.read_text(encoding='utf-8'))
    settings=json.loads((source.parent/'run.json').read_text(encoding='utf-8'))
    author_stage(output,messages[0]['content'],json.loads(messages[1]['content']),'diagnostic',thinking=settings.get('thinking','disabled'),temperature=settings.get('temperature',1.0))

if __name__=='__main__':
    main()
