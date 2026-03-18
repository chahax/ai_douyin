import os
try:
    from moviepy.editor import AudioFileClip, CompositeAudioClip, afx
except ImportError:
    # MoviePy 2.0+ structure
    from moviepy import AudioFileClip, CompositeAudioClip, afx

from src.shared.logger import logger

class AudioMixer:
    """
    Mixes speech audio with background music.
    """
    def mix_audio(self, speech_path: str, bgm_path: str, output_path: str, bgm_volume: float = 0.2) -> str:
        """
        Mixes speech audio with background music.
        """
        if not os.path.exists(speech_path):
            logger.error(f"Speech file not found: {speech_path}")
            return None
        
        if not bgm_path or not os.path.exists(bgm_path):
            logger.warning(f"BGM file not found or not provided: {bgm_path}. Skipping mix.")
            return speech_path

        try:
            logger.info(f"Mixing audio: Speech={speech_path}, BGM={bgm_path}, Vol={bgm_volume}")
            
            # Load audio clips
            speech_clip = AudioFileClip(speech_path)
            bgm_clip = AudioFileClip(bgm_path)
            
            # Ensure BGM loops if shorter than speech
            if bgm_clip.duration < speech_clip.duration:
                n_loops = int(speech_clip.duration / bgm_clip.duration) + 1
                try:
                    bgm_clip = bgm_clip.loop(n=n_loops)
                except AttributeError:
                    # Try afx loop
                    try:
                        bgm_clip = afx.audio_loop(bgm_clip, n=n_loops)
                    except Exception:
                        try:
                            from moviepy.audio.fx.AudioLoop import AudioLoop
                            bgm_clip = bgm_clip.with_effects([AudioLoop(n_loops=n_loops)])
                        except Exception:
                            pass
            
            # Trim BGM to match speech duration
            bgm_clip = bgm_clip.subclipped(0, speech_clip.duration)
            
            fade_seconds = min(3.0, max(0.0, speech_clip.duration / 2.0))
            try:
                from moviepy.audio.fx.MultiplyVolume import MultiplyVolume
                from moviepy.audio.fx.AudioFadeIn import AudioFadeIn
                from moviepy.audio.fx.AudioFadeOut import AudioFadeOut
                effects = [MultiplyVolume(factor=bgm_volume)]
                if fade_seconds > 0:
                    effects.append(AudioFadeIn(duration=fade_seconds))
                    effects.append(AudioFadeOut(duration=fade_seconds))
                bgm_clip = bgm_clip.with_effects(effects)
            except Exception:
                try:
                    bgm_clip = bgm_clip.volumex(bgm_volume)
                except AttributeError:
                    try:
                        bgm_clip = bgm_clip.multiply_volume(bgm_volume)
                    except Exception:
                        try:
                            bgm_clip = afx.volumex(bgm_clip, bgm_volume)
                        except Exception:
                            logger.warning("Could not adjust volume: volumex/multiply_volume missing.")
                if fade_seconds > 0:
                    try:
                        bgm_clip = bgm_clip.audio_fadein(fade_seconds).audio_fadeout(fade_seconds)
                    except AttributeError:
                        try:
                            bgm_clip = afx.audio_fadein(bgm_clip, fade_seconds)
                            bgm_clip = afx.audio_fadeout(bgm_clip, fade_seconds)
                        except Exception:
                            logger.warning("Could not apply fade in/out to BGM.")

            # Composite (layer BGM under speech)
            final_audio = CompositeAudioClip([speech_clip, bgm_clip])
            
            # Write output
            # MoviePy 2.0+ changed write_audiofile signature, removed verbose
            try:
                final_audio.write_audiofile(output_path, codec='libmp3lame', verbose=False, logger=None)
            except TypeError:
                # Fallback for newer versions without verbose/logger args or different names
                 final_audio.write_audiofile(output_path, codec='libmp3lame')
            
            # Close clips
            speech_clip.close()
            bgm_clip.close()
            final_audio.close()
            
            logger.info(f"Mixed audio saved to: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Audio mixing failed: {e}")
            import traceback
            traceback.print_exc()
            return None
