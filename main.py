import argparse
import sys
import os
from src.shared.logger import logger
from src.shared.output_manager import finalize_output
from src.content_factory.book_processor import BookProcessor
from src.content_factory.wisdom_extractor import WisdomExtractor
from src.content_factory.wisdom_extractor_rag import WisdomExtractorRAG
from src.rag_engine.wisdom_retriever import WisdomRetriever
from src.content_factory.script_generator import ScriptGenerator
from src.content_factory.tts_engine import TTSEngine
from src.content_factory.audio_mixer import AudioMixer

DEFAULT_BGM_PATH = r"d:\IT\ai_douyin\data\ref_audio\Morning-Routine-Lofi-Study-Music(chosic.com).mp3"

def generate_video_pipeline(args):
    """
    Executes the video generation pipeline.
    """
    logger.info("=== Starting Video Generation Pipeline ===")
    
    script_content = ""
    
    # 0. Direct Text Mode (Skips Wisdom/Script Gen)
    if hasattr(args, 'text') and args.text:
        logger.info("[Step 0] Direct Text Mode Activated")
        script_content = args.text
    else:
        wisdom = None
        
        # 1. Wisdom Acquisition (RAG or Random)
        if args.topic:
            logger.info(f"[Step 1] RAG Mode: Searching wisdom for topic '{args.topic}'...")
            retriever = WisdomRetriever()
            chunks = retriever.search_wisdom(args.topic, top_k=3)
            
            if not chunks:
                logger.warning("No relevant chunks found. Falling back to random extraction.")
            else:
                logger.info(f"[Step 2] RAG Mode: Extracting wisdom from {len(chunks)} chunks...")
                rag_extractor = WisdomExtractorRAG()
                wisdom = rag_extractor.extract_wisdom(args.topic, chunks)

        # Fallback to Random Book Mode if no topic or RAG failed
        if not wisdom:
            logger.info("[Step 1] Random Mode: Reading Book...")
            book_proc = BookProcessor()
            chunk = book_proc.read_random_chunk(book_name=args.book)
            
            if not chunk:
                logger.error("Failed to read book chunk.")
                return None
            
            logger.info(f"Book: {chunk['book_name']}")
            
            logger.info("[Step 2] Random Mode: Extracting Wisdom...")
            extractor = WisdomExtractor()
            wisdom = extractor.extract_wisdom(chunk['content'])
        
        if not wisdom:
            logger.error("Failed to extract wisdom.")
            return None
        
        logger.info(f"Wisdom Title: {wisdom.get('title')}")

        # 3. Script Generation
        logger.info("[Step 3] Generating Script...")
        script_gen = ScriptGenerator()
        generation_hints = {
            "keywords": getattr(args, "keywords", ""),
            "emotion_type": getattr(args, "emotion_type", ""),
            "positive_energy_type": getattr(args, "positive_energy_type", ""),
            "target_audience": getattr(args, "target_audience", ""),
        }
        script_data = script_gen.generate_script(wisdom, generation_hints=generation_hints)
        
        if not script_data:
            logger.error("Failed to generate script.")
            return None
            
        script_content = script_data.get("script_content", "")
        logger.info("Script generated.")

    # 4. TTS Synthesis
    logger.info("[Step 4] Synthesizing Audio...")
    tts = TTSEngine(provider_type=args.tts_provider)
    
    extension = "wav" if args.tts_provider == "gpt_sovits" else "mp3"
    audio_filename = f"output_{int(os.times().system)}.{extension}"
    
    # Pass no_merge option to TTS engine
    tts_kwargs = {}
    if hasattr(args, 'no_merge') and args.no_merge:
        tts_kwargs['no_merge'] = True
        
    audio_path = tts.generate_audio(
        text=script_content,
        filename=audio_filename,
        voice=args.voice,
        **tts_kwargs
    )
    
    if not audio_path:
        logger.error("Pipeline failed at TTS stage.")
        return None

    # 5. Audio Mixing (BGM)
    if hasattr(args, 'bgm') and args.bgm:
        logger.info(f"[Step 5] Mixing BGM: {args.bgm}")
        mixer = AudioMixer()
        
        # Handle list of files if no_merge is active
        if isinstance(audio_path, list):
            mixed_paths = []
            for idx, path in enumerate(audio_path):
                mixed_path = f"{os.path.splitext(path)[0]}_mixed.mp3"
                final_path = mixer.mix_audio(path, args.bgm, mixed_path, bgm_volume=args.bgm_volume)
                if final_path:
                    mixed_paths.append(final_path)
                else:
                    logger.warning(f"BGM mixing failed for {path}, using original.")
                    mixed_paths.append(path)
            audio_path = mixed_paths
        else:
            mixed_path = f"{os.path.splitext(audio_path)[0]}_mixed.mp3"
            final_path = mixer.mix_audio(audio_path, args.bgm, mixed_path, bgm_volume=args.bgm_volume)
            if final_path:
                audio_path = final_path
            else:
                logger.warning("BGM mixing failed, using original speech audio.")

    logger.info(f"Pipeline Success! Audio saved to: {audio_path}")
    return audio_path


def run_quick_pipeline(args):
    final_paths = []
    # If using direct text, we usually run once unless count is specified
    loop_count = args.count
    
    for i in range(loop_count):
        logger.info(f"--- Quick Generating {i+1}/{loop_count} ---")
        
        # Determine prompt/text usage
        # If --text is used, prompt is ignored for generation but used for filename if prompt exists
        # If --prompt is used without --text, we generate script
        
        topic_value = getattr(args, "prompt", None) or getattr(args, "keywords", None)
        bgm_value = getattr(args, 'bgm', None)
        if not bgm_value and os.path.exists(DEFAULT_BGM_PATH):
            bgm_value = DEFAULT_BGM_PATH
        pipeline_args = {
            "book": None,
            "topic": topic_value,
            "count": 1,
            "tts_provider": args.tts_provider,
            "voice": args.voice,
            "text": getattr(args, 'text', None),
            "bgm": bgm_value,
            "bgm_volume": getattr(args, 'bgm_volume', 0.2),
            "no_merge": getattr(args, 'no_merge', False),
            "keywords": getattr(args, "keywords", ""),
            "emotion_type": getattr(args, "emotion_type", ""),
            "positive_energy_type": getattr(args, "positive_energy_type", ""),
            "target_audience": getattr(args, "target_audience", ""),
        }
        
        mapped_args = argparse.Namespace(**pipeline_args)
        
        source_audio_path = generate_video_pipeline(mapped_args)
        if not source_audio_path:
            logger.error("Quick pipeline failed to generate audio.")
            continue
            
        # Use prompt or first 10 chars of text for filename topic
        topic_for_filename = args.prompt if args.prompt else (args.keywords if getattr(args, "keywords", None) else (args.text[:10] if args.text else "unknown"))
            
        # Handle archiving for single file or list of files
        if isinstance(source_audio_path, list):
            for idx, path in enumerate(source_audio_path):
                # Append index to topic for unique filenames
                sub_topic = f"{topic_for_filename}_{idx+1}"
                archived_path = finalize_output(
                    source_path=path,
                    output_dir=args.output_dir,
                    topic=sub_topic,
                    provider=args.tts_provider,
                    keep_temp=args.keep_temp,
                )
                if archived_path:
                    final_paths.append(archived_path)
                    logger.info(f"Quick pipeline output {idx+1}: {archived_path}")
        else:
            archived_path = finalize_output(
                source_path=source_audio_path,
                output_dir=args.output_dir,
                topic=topic_for_filename,
                provider=args.tts_provider,
                keep_temp=args.keep_temp,
            )
            if archived_path:
                final_paths.append(archived_path)
                logger.info(f"Quick pipeline output: {archived_path}")
    return final_paths

def main():
    parser = argparse.ArgumentParser(description="WisdomAI - Life Inspiration Video Generator")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate Command
    gen_parser = subparsers.add_parser("generate", help="Generate a video")
    gen_parser.add_argument("--book", type=str, help="Specific book filename (optional, random mode only)")
    gen_parser.add_argument("--topic", type=str, help="Topic for RAG search (e.g. '人生迷茫')")
    gen_parser.add_argument("--count", type=int, default=1, help="Number of videos to generate")
    gen_parser.add_argument("--tts-provider", type=str, default="edge", choices=["edge", "gpt_sovits"], help="TTS Provider")
    gen_parser.add_argument("--voice", type=str, help="Voice ID (optional)")

    quick_parser = subparsers.add_parser("quick", help="Generate by prompt in one command")
    quick_parser.add_argument("--prompt", type=str, help="Prompt/topic text (Optional if --text is provided)")
    quick_parser.add_argument("--text", type=str, help="Direct text input (skips script generation)")
    quick_parser.add_argument("--bgm", type=str, help=f"Background music file path (default: {DEFAULT_BGM_PATH})")
    quick_parser.add_argument("--bgm-volume", type=float, default=0.2, help="BGM volume (0.0-1.0)")
    quick_parser.add_argument("--output-dir", type=str, help="Archive output directory")
    quick_parser.add_argument("--tts-provider", type=str, default="gpt_sovits", choices=["edge", "gpt_sovits"], help="TTS Provider")
    quick_parser.add_argument("--voice", type=str, help="Voice ID or reference audio path")
    quick_parser.add_argument("--count", type=int, default=1, help="Number of audios to generate")
    quick_parser.add_argument("--keep-temp", action="store_true", help="Keep temp file in original output dir")
    quick_parser.add_argument("--no-merge", action="store_true", help="Do not merge sentences into one file")
    quick_parser.add_argument("--keywords", type=str, help="Required keywords, comma separated")
    quick_parser.add_argument("--emotion-type", type=str, help="Emotion type, e.g. 顿悟/低谷/鼓励")
    quick_parser.add_argument("--positive-energy-type", type=str, help="Positive energy type")
    quick_parser.add_argument("--target-audience", type=str, help="Target audience")

    args = parser.parse_args()

    if args.command == "generate":
        for i in range(args.count):
            logger.info(f"--- Generating Video {i+1}/{args.count} ---")
            generate_video_pipeline(args)
    elif args.command == "quick":
        if not args.text and not args.prompt and not args.keywords:
            logger.error("quick 命令至少需要 --prompt 或 --keywords 或 --text 其中一个参数。")
            sys.exit(1)
        outputs = run_quick_pipeline(args)
        if outputs:
            logger.info("Quick command completed.")
            for path in outputs:
                print(path)
        else:
            logger.error("Quick command failed with no outputs.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
