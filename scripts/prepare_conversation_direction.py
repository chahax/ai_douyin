"""Generate execution direction with the project's configured script model."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.shared.config import settings
from src.shared.llm_client import LLMClient
from src.content_factory.conversation_direction import generate_plan

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('script');p.add_argument('output_dir')
    p.add_argument('--north-person',required=True);p.add_argument('--south-person',required=True)
    p.add_argument('--draft');p.add_argument('--feedback-file')
    p.add_argument('--baseline-plan', help='Previous script plan for a targeted revision with distinct provenance')
    args=p.parse_args()
    extra=({'thinking':{'type':settings.SCRIPT_LLM_THINKING},'reasoning_split':True}
           if settings.SCRIPT_LLM_THINKING else None)
    client=LLMClient(model=settings.SCRIPT_LLM_MODEL or None,timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                     max_retries=0,max_tokens=12000,preserve_invalid_json=True,extra_body=extra)
    feedback=Path(args.feedback_file).read_text(encoding='utf-8') if args.feedback_file else ''
    generate_plan(args.script,args.output_dir,args.north_person,args.south_person,client,args.draft,feedback,args.baseline_plan)
    print(str(Path(args.output_dir)/'direction_plan.json'))
