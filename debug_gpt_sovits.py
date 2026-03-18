import sys
import os
import torch

# Add SDK paths
sdk_root = r"D:\IT\GPT-SoVITS-main\GPT-SoVITS-main"
# Change CWD to SDK root to fix relative path issues
os.chdir(sdk_root)
print(f"Changed CWD to {os.getcwd()}", flush=True)

sys.path.insert(0, sdk_root)
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS"))
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS", "eres2net"))
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS", "BigVGAN"))

print("Start importing...", flush=True)
from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
print("Import success.", flush=True)

config_path = os.path.join(sdk_root, "GPT_SoVITS", "configs", "tts_infer.yaml")
print(f"Loading config from {config_path}", flush=True)

tts_config = TTS_Config(config_path)
print(f"Config is_half: {tts_config.is_half}", flush=True)
print(f"Config device: {tts_config.device}", flush=True)

tts = TTS(tts_config)
print("Models loaded successfully.", flush=True)

# Check types
if tts.t2s_model:
    print(f"T2S Model type: {next(tts.t2s_model.parameters()).dtype}", flush=True)
if tts.vits_model:
    print(f"VITS Model type: {next(tts.vits_model.parameters()).dtype}", flush=True)
if tts.cnhuhbert_model:
    print(f"CNHubert Model type: {next(tts.cnhuhbert_model.parameters()).dtype}", flush=True)
if tts.bert_model:
    print(f"BERT Model type: {next(tts.bert_model.parameters()).dtype}", flush=True)
