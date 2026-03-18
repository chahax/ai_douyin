import os
import re
import shutil
import sys
import requests
from src.content_factory.tts_providers.base import TTSProvider
from src.shared.logger import logger


class GPTSoVITSProvider(TTSProvider):
    def __init__(self, api_url="http://127.0.0.1:9880"):
        self.api_url = api_url
        self.sdk_root = os.path.abspath(os.environ.get("GPT_SOVITS_SDK_ROOT", r"D:\IT\GPT-SoVITS-main\GPT-SoVITS-main"))
        self.default_ref_audio = os.path.join(self.sdk_root, "output", "ref_audio_denoised", "ttsmaker-file-2026-3-14-16-10-15.mp3")
        if not os.path.exists(self.default_ref_audio):
            self.default_ref_audio = os.path.abspath("data/ref_audio/mature_male_ref.wav")
        self.default_ref_text = "是的，爱情的症状和霍乱一模一样，突如其来摧枯拉朽让人失去控制。"
        self.default_lang = "zh"
        self.default_gpt_weights = "GPT_weights_v2ProPlus/xxx-e10.ckpt"
        self.default_sovits_weights = "SoVITS_weights_v2ProPlus/xxx_e12_s192.pth"
        # 语音风格参数（与 quick_start.py 对齐）
        self.default_speed_factor = 0.9  # 语速系数：<1 更慢，>1 更快
        self.default_top_k = 6  # 采样候选数：越大随机性越强
        self.default_top_p = 0.9  # 核采样阈值：越大越开放，越小越稳定
        self.default_temperature = 1.0  # 温度：越高更有变化，越低更保守
        self.default_repetition_penalty = 1.4  # 重复惩罚：越高越抑制重复与电音
        self.default_text_split_method = "cut5"  # 文本切分策略：控制长文本如何分句生成
        self.default_tts_config = os.path.join(self.sdk_root, "GPT_SoVITS", "configs", "tts_infer.yaml")
        self._sdk_client = None

    def _split_text_by_limit(self, text: str, max_len: int = 480):
        text = (text or "").strip()
        if not text:
            return []
        if len(text) <= max_len:
            return [text]
        sentences = re.split(r'(?<=[。！？.!?\n])', text)
        sentences = [s.strip() for s in sentences if s and s.strip()]
        chunks = []
        buf = ""
        for s in sentences:
            if len(s) > max_len:
                if buf:
                    chunks.append(buf)
                    buf = ""
                for i in range(0, len(s), max_len):
                    part = s[i:i + max_len].strip()
                    if part:
                        chunks.append(part)
                continue
            if len(buf) + len(s) <= max_len:
                buf = f"{buf}{s}"
            else:
                if buf:
                    chunks.append(buf)
                buf = s
        if buf:
            chunks.append(buf)
        return chunks

    def _resolve_ref_audio(self, voice, ref_audio_path):
        if ref_audio_path and os.path.exists(ref_audio_path):
            return os.path.abspath(ref_audio_path)
        if voice:
            potential_path = os.path.abspath(os.path.join("data/ref_audio", f"{voice}.wav"))
            if os.path.exists(potential_path):
                return potential_path
            if os.path.exists(voice):
                return os.path.abspath(voice)
        return self.default_ref_audio

    def _init_sdk_client(self, kwargs):
        if self._sdk_client is not None:
            return self._sdk_client
        if not os.path.isdir(self.sdk_root):
            return None
        sdk_paths = [
            self.sdk_root,
            os.path.join(self.sdk_root, "GPT_SoVITS"),
            os.path.join(self.sdk_root, "GPT_SoVITS", "eres2net"),
            os.path.join(self.sdk_root, "GPT_SoVITS", "BigVGAN"),
        ]
        # modelscope logic removed to avoid ERes2NetV2 conflict
        
        for p in sdk_paths:
            if os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)
        
        # Aggressively remove conflicting ERes2NetV2 from modelscope if present
        if "ERes2NetV2" in sys.modules:
            mod = sys.modules["ERes2NetV2"]
            if "modelscope" in getattr(mod, "__file__", ""):
                logger.warning(f"Removing conflicting ERes2NetV2 module from modelscope: {mod.__file__}")
                del sys.modules["ERes2NetV2"]
                # Also clean up sv if it depends on it
                if "sv" in sys.modules:
                    del sys.modules["sv"]

        try:
            from sdk.tts_client import ClientConfig, TTSClient

            # Patch GPT-SoVITS TTS to fix float16/float32 mismatch on CPU
            try:
                from GPT_SoVITS.TTS_infer_pack.TTS import TTS
                
                if not getattr(TTS.init_cnhuhbert_weights, "_is_patched", False):
                    original_init_cnhuhbert = TTS.init_cnhuhbert_weights
                    def patched_init_cnhuhbert(self, base_path: str):
                        original_init_cnhuhbert(self, base_path)
                        if str(self.configs.device) == "cpu" and not self.configs.is_half:
                            if hasattr(self, "cnhuhbert_model") and self.cnhuhbert_model is not None:
                                self.cnhuhbert_model = self.cnhuhbert_model.float()
                    patched_init_cnhuhbert._is_patched = True
                    TTS.init_cnhuhbert_weights = patched_init_cnhuhbert

                if not getattr(TTS.init_bert_weights, "_is_patched", False):
                    original_init_bert = TTS.init_bert_weights
                    def patched_init_bert(self, base_path: str):
                        original_init_bert(self, base_path)
                        if str(self.configs.device) == "cpu" and not self.configs.is_half:
                            if hasattr(self, "bert_model") and self.bert_model is not None:
                                self.bert_model = self.bert_model.float()
                    patched_init_bert._is_patched = True
                    TTS.init_bert_weights = patched_init_bert
                
                logger.info("Successfully patched GPT-SoVITS TTS for CPU float32 compatibility")
            except ImportError:
                pass # SDK structure might differ
            except Exception as e:
                logger.warning(f"Failed to patch GPT-SoVITS TTS: {e}")

            config = ClientConfig(
                gpt_weights=kwargs.get("gpt_weights", self.default_gpt_weights),
                sovits_weights=kwargs.get("sovits_weights", self.default_sovits_weights),
                output_dir=kwargs.get("sdk_output_dir", "output/sdk"),
                default_text_lang=kwargs.get("text_lang", self.default_lang),
                default_prompt_lang=kwargs.get("prompt_lang", self.default_lang),
                default_output_format=kwargs.get("output_format", "wav"),
                default_request_version=kwargs.get("request_version", "v2ProPlus"),
                default_ref_audio_path=kwargs.get("ref_audio_path", self.default_ref_audio),
            )
            self._sdk_client = TTSClient(config=config)
            return self._sdk_client
        except Exception as e:
            logger.warning(f"GPT-SoVITS SDK init failed: {e}")
            return None

    def _generate_with_sdk(self, text, output_file, ref_audio_path, prompt_text, kwargs):
        client = self._init_sdk_client(kwargs)
        if client is None:
            return False
        
        # Temporarily change CWD to SDK root to handle relative paths in config
        original_cwd = os.getcwd()
        
        # Ensure output_file is absolute before changing CWD
        output_file = os.path.abspath(output_file) if not os.path.isabs(output_file) else output_file
        ref_audio_path = os.path.abspath(ref_audio_path) if not os.path.isabs(ref_audio_path) else ref_audio_path

        try:
            if os.path.exists(self.sdk_root):
                os.chdir(self.sdk_root)
            
            # Use SDK to synthesize
            # Check if we need to return list of files (no_merge)
            no_merge = kwargs.get("no_merge", False)
            
            result = client.synthesize(
                text=text,
                ref_audio_path=ref_audio_path,
                prompt_text=prompt_text,
                text_lang=kwargs.get("text_lang", self.default_lang),
                prompt_lang=kwargs.get("prompt_lang", self.default_lang),
                output_format=kwargs.get("output_format", "wav"),
                speed_factor=float(kwargs.get("speed_factor", self.default_speed_factor)),
                speaker_preset=kwargs.get("speaker_preset", ""),
                trace_id=kwargs.get("trace_id", ""),
                request_version=kwargs.get("request_version", "v2ProPlus"),
                top_k=kwargs.get("top_k", self.default_top_k),
                top_p=kwargs.get("top_p", self.default_top_p),
                temperature=kwargs.get("temperature", self.default_temperature),
                text_split_method=kwargs.get("text_split_method", self.default_text_split_method),
                sample_steps=kwargs.get("sample_steps", 32),
                repetition_penalty=kwargs.get("repetition_penalty", self.default_repetition_penalty),
                seed=kwargs.get("seed", -1),
                is_half=kwargs.get("is_half", False),
                device=kwargs.get("device", "cpu"),
                tts_config=kwargs.get("tts_config", self.default_tts_config),
                gpt_weights=kwargs.get("gpt_weights", self.default_gpt_weights),
                sovits_weights=kwargs.get("sovits_weights", self.default_sovits_weights),
                return_files=no_merge # Pass return_files=True to get list of paths if SDK supports it, or handle result
            )
            
            if not result.get("success"):
                error_code = result.get("error_code")
                error_msg = result.get("error_msg", "")
                logger.error(f"GPT-SoVITS SDK error: {error_code} - {error_msg}")
                if error_code == "E_TEXT_TOO_LONG" or "text length exceeds" in str(error_msg):
                    chunks = self._split_text_by_limit(text, max_len=480)
                    if len(chunks) > 1:
                        logger.warning(f"Text too long, auto split into {len(chunks)} chunks.")
                        base_name, ext = os.path.splitext(output_file)
                        audio_paths = []
                        for i, part in enumerate(chunks):
                            seg_output = f"{base_name}_{i+1}{ext}"
                            kwargs_copy = kwargs.copy()
                            kwargs_copy["no_merge"] = False
                            seg_ok = self._generate_with_sdk(part, seg_output, ref_audio_path, prompt_text, kwargs_copy)
                            if isinstance(seg_ok, str):
                                audio_paths.append(seg_ok)
                            elif seg_ok is True and os.path.exists(seg_output):
                                audio_paths.append(seg_output)
                            elif isinstance(seg_ok, list):
                                audio_paths.extend(seg_ok)
                        if audio_paths:
                            return audio_paths
                return False if not no_merge else []
            
            if no_merge:
                # If SDK result has 'audio_paths' (list), use that.
                audio_paths = result.get("audio_paths", [])
                
                # If SDK doesn't support list return, we implement split logic here
                if not audio_paths:
                    # Simple sentence splitting
                    sentences = re.split(r'([。！？.!?\n])', text)
                    sentences = ["".join(i) for i in zip(sentences[0::2], sentences[1::2])]
                    if len(sentences) * 2 < len(re.split(r'([。！？.!?\n])', text)):
                         sentences.append(re.split(r'([。！？.!?\n])', text)[-1])
                    sentences = [s.strip() for s in sentences if s.strip()]
                    
                    audio_paths = []
                    base_name, ext = os.path.splitext(output_file)
                    
                    for i, sent in enumerate(sentences):
                        seg_output = f"{base_name}_{i+1}{ext}"
                        # Recursive call without no_merge to generate individual segment
                        kwargs_copy = kwargs.copy()
                        kwargs_copy["no_merge"] = False
                        if self._generate_with_sdk(sent, seg_output, ref_audio_path, prompt_text, kwargs_copy):
                            audio_paths.append(seg_output)
                    
                    return audio_paths if audio_paths else []
                
                return audio_paths
            
            audio_path = result.get("audio_path", "")
            if not audio_path or not os.path.exists(audio_path):
                logger.error("GPT-SoVITS SDK returned empty audio_path")
                return False if not no_merge else []
            
            if no_merge:
                return [] # Should have returned above if successful
                
            shutil.copyfile(audio_path, output_file)
            return os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception as e:
            logger.error(f"GPT-SoVITS SDK synthesize failed: {e}")
            return False if not no_merge else []
        finally:
            os.chdir(original_cwd)

    def _generate_with_http(self, text, output_file, ref_audio_path, prompt_text, kwargs):
        payload = {
            "text": text,
            "text_lang": kwargs.get("text_lang", self.default_lang),
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": kwargs.get("prompt_lang", self.default_lang),
            "output_format": kwargs.get("output_format", "wav"),
            "speed_factor": float(kwargs.get("speed_factor", self.default_speed_factor)),
            "speaker_preset": kwargs.get("speaker_preset", ""),
            "trace_id": kwargs.get("trace_id", ""),
            "request_version": kwargs.get("request_version", "v2ProPlus"),
            "top_k": kwargs.get("top_k", self.default_top_k),
            "top_p": kwargs.get("top_p", self.default_top_p),
            "temperature": kwargs.get("temperature", self.default_temperature),
            "text_split_method": kwargs.get("text_split_method", self.default_text_split_method),
            "sample_steps": kwargs.get("sample_steps", 32),
            "repetition_penalty": kwargs.get("repetition_penalty", self.default_repetition_penalty),
            "seed": kwargs.get("seed", -1),
            "is_half": kwargs.get("is_half", False),
            "device": kwargs.get("device", "cpu"),
        }
        payload["tts_config"] = kwargs.get("tts_config", self.default_tts_config)
        payload["gpt_weights"] = kwargs.get("gpt_weights", self.default_gpt_weights)
        payload["sovits_weights"] = kwargs.get("sovits_weights", self.default_sovits_weights)
        try:
            base_url = self.api_url.rstrip("/")
            if base_url.endswith("/tts"):
                candidate_urls = [base_url]
            else:
                candidate_urls = [f"{base_url}/tts", base_url]
            response = None
            for url in candidate_urls:
                response = requests.post(url, json=payload, timeout=180)
                if response.status_code == 200:
                    break
                logger.warning(f"GPT-SoVITS API attempt failed [{url}] {response.status_code}: {response.text}")
            if response is None or response.status_code != 200:
                logger.error(f"GPT-SoVITS API error: {response.status_code if response is not None else 'N/A'} - {response.text if response is not None else ''}")
                return False
            content_type = response.headers.get("content-type", "").lower()
            if "application/json" in content_type:
                result = response.json()
                if not result.get("success"):
                    logger.error(f"GPT-SoVITS skill error: {result.get('error_code')} - {result.get('error_msg')}")
                    return False
                audio_path = result.get("audio_path", "")
                if not audio_path or not os.path.exists(audio_path):
                    logger.error("GPT-SoVITS skill returned invalid audio_path")
                    return False
                shutil.copyfile(audio_path, output_file)
                return os.path.exists(output_file) and os.path.getsize(output_file) > 0
            with open(output_file, "wb") as f:
                f.write(response.content)
            return os.path.exists(output_file) and os.path.getsize(output_file) > 0
        except Exception as e:
            logger.error(f"GPT-SoVITS HTTP request failed: {e}")
            return False

    def generate_audio(self, text, output_file, voice=None, **kwargs):
        """
        Generate audio from text.
        If 'no_merge' is True in kwargs, returns a list of generated file paths instead of a single boolean/file.
        """
        ref_audio_path = self._resolve_ref_audio(voice, kwargs.get("ref_audio_path", ""))
        prompt_text = kwargs.get("prompt_text", kwargs.get("ref_text", self.default_ref_text))
        if not os.path.exists(ref_audio_path):
            logger.warning(f"Reference audio not found: {ref_audio_path}")
            return False
            
        # Handle no_merge logic for SDK
        if kwargs.get("no_merge", False) and kwargs.get("use_sdk", True):
             return self._generate_with_sdk(text, output_file, ref_audio_path, prompt_text, kwargs)

        if kwargs.get("use_sdk", True):
            sdk_result = self._generate_with_sdk(text, output_file, ref_audio_path, prompt_text, kwargs)
            if sdk_result:
                return sdk_result
        return self._generate_with_http(text, output_file, ref_audio_path, prompt_text, kwargs)

    def list_voices(self):
        ref_dir = "data/ref_audio"
        if not os.path.exists(ref_dir):
            return []
        return [f.replace(".wav", "") for f in os.listdir(ref_dir) if f.endswith(".wav")]
