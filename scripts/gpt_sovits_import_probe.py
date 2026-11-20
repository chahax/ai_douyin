from __future__ import annotations

import os
import sys
import time
import faulthandler
from pathlib import Path


def mark(label: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {label}", flush=True)


root = Path(sys.argv[1]).resolve()
faulthandler.dump_traceback_later(30, repeat=True)
os.chdir(root)
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "GPT_SoVITS"))

mark("start")
import torch

mark(f"torch imported cuda={torch.cuda.is_available()}")
import torchaudio

mark("torchaudio imported")
import ffmpeg
mark("ffmpeg imported")
import librosa
mark("librosa imported")
import yaml
mark("yaml imported")
from AR.models.t2s_lightning_module import Text2SemanticLightningModule
mark("AR imported")
from BigVGAN.bigvgan import BigVGAN
mark("BigVGAN imported")
from feature_extractor.cnhubert import CNHubert
mark("CNHubert imported")
from module.mel_processing import mel_spectrogram_torch, spectrogram_torch
mark("mel processing imported")
from module.models import Generator, SynthesizerTrn, SynthesizerTrnV3
mark("module models imported")
from peft import LoraConfig, get_peft_model
mark("peft imported")
from process_ckpt import get_sovits_version_from_path_fast, load_sovits_new
mark("process_ckpt imported")
from transformers import AutoModelForMaskedLM, AutoTokenizer
mark("transformers imported")
from tools.audio_sr import AP_BWE
mark("audio_sr imported")
from tools.i18n.i18n import I18nAuto, scan_language_list
mark("i18n imported")
from TTS_infer_pack.text_segmentation_method import splits
mark("segmentation imported")
from TTS_infer_pack.TextPreprocessor import TextPreprocessor
mark("TextPreprocessor imported")
from sv import SV
mark("SV imported")
from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
mark("GPT-SoVITS TTS modules imported")
config = TTS_Config(str(Path(sys.argv[2]).resolve()))
mark("TTS_Config created")
pipeline = TTS(config)
mark("TTS pipeline created")
pipeline.init_t2s_weights(sys.argv[3])
mark("GPT weights loaded")
pipeline.init_vits_weights(sys.argv[4])
mark("SoVITS weights loaded")
