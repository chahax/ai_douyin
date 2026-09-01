import os

from src.content_factory.tts_providers.gpt_sovits_provider import GPTSoVITSProvider
from src.shared.config import settings
from src.shared.logger import logger


class TTSEngine:
    def __init__(self, output_dir=None, provider_type=None):
        """
        :param output_dir: Directory to save generated audio.
        :param provider_type: Primary supported provider is 'gpt_sovits'.
        """
        self.output_dir = output_dir or settings.VIDEOS_DIR
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

        # Empty/current values follow the active workflow profile.  Explicit
        # provider IDs remain per-run overrides for backward compatibility.
        from src.workflow.runtime import resolve_node_implementation

        requested_provider = provider_type or "workflow_default"
        self.provider_type = resolve_node_implementation("tts", requested_provider)
        if self.provider_type == "gpt_sovits":
            self.provider = GPTSoVITSProvider()
            logger.info("TTSEngine initialized with GPT-SoVITS Provider")
        elif self.provider_type == "edge":
            from src.content_factory.tts_providers.edge_tts_provider import EdgeTTSProvider

            self.provider = EdgeTTSProvider()
            logger.info("TTSEngine initialized with Edge-TTS Provider")
        else:
            raise ValueError(f"Unsupported TTS provider: {self.provider_type}")

    def generate_audio(self, text, filename="audio.wav", voice=None, **kwargs):
        """
        Generates audio from text using the selected provider.
        """
        output_path = os.path.join(self.output_dir, filename)

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
