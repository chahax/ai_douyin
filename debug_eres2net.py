import sys
import os

# Add paths as done in gpt_sovits_provider
sdk_root = r"D:\IT\GPT-SoVITS-main\GPT-SoVITS-main"
sys.path.insert(0, sdk_root)
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS"))
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS", "eres2net"))
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS", "BigVGAN"))

try:
    import ERes2NetV2
    print(f"ERes2NetV2 file: {ERes2NetV2.__file__}")
    if hasattr(ERes2NetV2.ERes2NetV2, 'forward3'):
        print("ERes2NetV2 has forward3")
    else:
        print("ERes2NetV2 DOES NOT have forward3")
except ImportError as e:
    print(f"Import failed: {e}")
