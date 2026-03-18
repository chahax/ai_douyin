import json
import os
import time
from src.content_factory.book_processor import BookProcessor
from src.content_factory.wisdom_extractor import WisdomExtractor
from src.content_factory.script_generator import ScriptGenerator
from src.content_factory.tts_engine import TTSEngine
from src.shared.logger import logger

def test_pipeline(book_name=None, use_mock=True):
    """
    Runs a full test of the content generation pipeline:
    Book -> Wisdom -> Script -> Audio
    """
    logger.info("=== Starting Content Pipeline Test ===")

    # 1. Book Processing
    logger.info("\n[Step 1] Reading Book...")
    book_proc = BookProcessor()
    chunk = book_proc.read_random_chunk(book_name=book_name)
    
    if not chunk:
        logger.error("Failed to read book chunk.")
        return
    
    logger.info(f"Book: {chunk['book_name']}")
    logger.info(f"Chunk Preview: {chunk['content'][:50]}...")

    # 2. Wisdom Extraction
    logger.info("\n[Step 2] Extracting Wisdom...")
    extractor = WisdomExtractor()
    wisdom = extractor.extract_wisdom(chunk['content'])
    
    if not wisdom:
        logger.error("Failed to extract wisdom.")
        return
    
    logger.info("Extracted Wisdom Metadata:")
    print(json.dumps(wisdom, indent=2, ensure_ascii=False))

    # 3. Script Generation
    logger.info("\n[Step 3] Generating Script...")
    script_gen = ScriptGenerator()
    script_data = script_gen.generate_script(wisdom)
    
    if not script_data:
        logger.error("Failed to generate script.")
        return
        
    script_content = script_data.get("script_content", "")
    logger.info("Generated Script Content:")
    print("-" * 40)
    print(script_content)
    print("-" * 40)

    # 4. TTS Synthesis
    logger.info("\n[Step 4] Synthesizing Audio...")
    
    # Select TTS Provider: 'edge' or 'gpt_sovits'
    # For integration testing, we might want to default to edge unless GPT-SoVITS is known to be running.
    # But since we are executing Plan B, let's try to use GPT-SoVITS if configured.
    provider_type = "edge" # Change to 'gpt_sovits' when service is ready
    
    tts = TTSEngine(output_dir="./data/voices", provider_type=provider_type)
    
    # Use a timestamped filename to avoid overwriting
    timestamp = int(time.time())
    
    # Test two styles: Mature Male & Cool Female
    # Trying deeper/older voices for "Mature" feeling
    # zh-CN-YunyangNeural: Professional News/Reading (新闻/朗读，更稳重)
    # zh-CN-YunzeNeural: Senior Male (老年男声，更有阅历感)
    styles = [
        ("yunyang_pro", "zh-CN-YunyangNeural"), 
        # ("yunze_senior", "zh-CN-YunzeNeural"), # Failed in previous test
        ("yunjian_sporty", "zh-CN-YunjianNeural")
    ]
    
    for style_name, voice_id in styles:
        filename = f"test_{style_name}_{timestamp}.mp3"
        audio_path = tts.generate_audio(
            text=script_content,
            filename=filename,
            voice=voice_id
        )
        if audio_path:
            logger.info(f"[{style_name}] Audio saved to: {audio_path}")
        else:
            logger.error(f"[{style_name}] Pipeline failed at TTS stage.")

if __name__ == "__main__":
    # You can specify a book name, e.g., "孟子.txt" or leave None for random
    test_pipeline(book_name="孟子.txt")
