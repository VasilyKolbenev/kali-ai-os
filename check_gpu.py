import torch
print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA build version: {torch.version.cuda}")
print(f"Device count: {torch.cuda.device_count()}")
for i in range(torch.cuda.device_count()):
    print(f"GPU {i}: {torch.cuda.get_device_name(i)}")

try:
    import onnxruntime as ort
    print(f"\nONNXRuntime: {ort.__version__}")
    print(f"ONNX providers: {ort.get_available_providers()}")
except ImportError:
    print("\nONNXRuntime: not installed")
