"""Quick check of RVC model configs — run in WSL conda rvc."""

import torch

models = [
    "/home/servasily/Applio/logs/jarvis_v1/jarvis_v1_300e_4500s_best_epoch.pth",
    "/home/servasily/Applio/logs/jarvis_v2/jarvis_v2_400e_4400s.pth",
    "/home/servasily/Applio/logs/jarvis_v2/jarvis_v2_50e_550s.pth",
]

for path in models:
    try:
        cpt = torch.load(path, map_location="cpu", weights_only=False)
        keys = list(cpt.keys())
        config = list(cpt.get("config", []))
        sr = cpt.get("sr", "N/A")
        version = cpt.get("version", "N/A")
        print(f"\n{path.split('/')[-1]}:")
        print(f"  keys: {keys}")
        print(f"  config: {config}")
        print(f"  sr: {sr}")
        print(f"  version: {version}")
    except Exception as e:
        print(f"\n{path.split('/')[-1]}: ERROR {e}")
