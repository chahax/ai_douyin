import asyncio
import edge_tts
import os
from src.content_factory.tts_providers.base import TTSProvider
from src.shared.logger import logger

class EdgeTTSProvider(TTSProvider):
    def __init__(self):
        self.default_voice = "zh-CN-YunyangNeural"
        self.default_rate = "+0%"
        self.default_volume = "+0%"

    async def _generate_async(self, text, output_file, voice, rate, volume):
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
        await communicate.save(output_file)

    def generate_audio(self, text, output_file, voice=None, **kwargs) -> bool:
        voice = voice or self.default_voice
        rate = kwargs.get("rate", self.default_rate)
        volume = kwargs.get("volume", self.default_volume)

        try:
            # Handle nested loops if necessary (though better to call this in a clean sync context)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import nest_asyncio
                    nest_asyncio.apply()
                loop.run_until_complete(self._generate_async(text, output_file, voice, rate, volume))
            except RuntimeError:
                asyncio.run(self._generate_async(text, output_file, voice, rate, volume))
            
            return os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception as e:
            logger.error(f"Edge-TTS Error: {e}")
            return False

    def list_voices(self):
        async def _list():
            voices = await edge_tts.list_voices()
            return [v for v in voices if "zh-CN" in v["ShortName"]]
        
        try:
            return asyncio.run(_list())
        except:
            # Fallback for nested loop
            loop = asyncio.get_event_loop()
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(_list())
