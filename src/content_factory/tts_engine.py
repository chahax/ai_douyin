import os
from src.shared.config import settings
from src.shared.logger import logger
from src.content_factory.tts_providers.edge_tts_provider import EdgeTTSProvider
from src.content_factory.tts_providers.gpt_sovits_provider import GPTSoVITSProvider

class TTSEngine:
    def __init__(self, output_dir=None, provider_type="edge"):
        """
        :param output_dir: Directory to save generated audio.
        :param provider_type: 'edge' or 'gpt_sovits'.
        """
        self.output_dir = output_dir or settings.VIDEOS_DIR
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        
        self.provider_type = provider_type
        if provider_type == "gpt_sovits":
            self.provider = GPTSoVITSProvider()
            logger.info("TTSEngine initialized with GPT-SoVITS Provider")
        else:
            self.provider = EdgeTTSProvider()
            logger.info("TTSEngine initialized with Edge-TTS Provider")

    def generate_audio(self, text, filename="audio.mp3", voice=None, **kwargs):
        """
        Generates audio from text using the selected provider.
        """
        output_path = os.path.join(self.output_dir, filename)
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        result = self.provider.generate_audio(text, output_path, voice, **kwargs)

        if isinstance(result, list):
            if result:
                logger.info(f"Audio generated successfully: {len(result)} files")
                return result
            logger.error("Audio generation failed.")
            return None

        if result:
            logger.info(f"Audio generated successfully at {output_path}")
            return output_path
        logger.error("Audio generation failed.")
        return None

    def list_voices(self):
        return self.provider.list_voices()

if __name__ == "__main__":
    # Test Edge TTS
    tts = TTSEngine(output_dir="./data/voices", provider_type="edge")
    path = tts.generate_audio("你好，我是Edge TTS。", "test_edge.mp3")
    
    # Test GPT-SoVITS (Will fail if service not running)
    tts_gpt = TTSEngine(output_dir="./data/voices", provider_type="gpt_sovits")
    path_gpt = tts_gpt.generate_audio("你好，我是GPT-SoVITS。", "test_gpt.wav", voice="mature_male_ref")
