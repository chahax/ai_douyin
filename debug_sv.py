import sys
import os
import torch

# Add paths as done in gpt_sovits_provider
sdk_root = r"D:\IT\GPT-SoVITS-main\GPT-SoVITS-main"
sys.path.insert(0, sdk_root)
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS"))
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS", "eres2net"))
sys.path.insert(0, os.path.join(sdk_root, "GPT_SoVITS", "BigVGAN"))

# Simulate CWD change
os.chdir(sdk_root)

try:
    import sv
    print(f"SV module file: {sv.__file__}")
    
    # Try to instantiate SV
    # sv.SV(device, is_half)
    # But it loads weights, so we need to be careful.
    # Just check ERes2NetV2 inside sv
    
    from ERes2NetV2 import ERes2NetV2
    print(f"ERes2NetV2 imported from: {sys.modules['ERes2NetV2'].__file__}")
    
    model = ERes2NetV2(baseWidth=24, scale=4, expansion=4)
    if hasattr(model, 'forward3'):
        print("Model instance has forward3")
    else:
        print("Model instance DOES NOT have forward3")
        print(dir(model))

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
