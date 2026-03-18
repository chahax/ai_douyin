from abc import ABC, abstractmethod

class TTSProvider(ABC):
    @abstractmethod
    def generate_audio(self, text: str, output_file: str, voice: str, **kwargs) -> bool:
        """
        Generates audio from text.
        :param text: Text content.
        :param output_file: Absolute path to save the audio.
        :param voice: Voice ID/Name.
        :return: True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def list_voices(self):
        """Returns a list of available voices."""
        pass
