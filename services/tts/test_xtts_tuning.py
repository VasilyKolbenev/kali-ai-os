"""Test XTTS v2 with tuned parameters for better JARVIS voice."""
import os
os.environ['COQUI_TOS_AGREED'] = '1'

import torch
import soundfile as sf
import torchaudio
import time


def _sf_load(filepath, *args, **kwargs):
    data, sr = sf.read(str(filepath))
    if data.ndim == 1:
        data = data[None, :]
    else:
        data = data.T
    return torch.tensor(data, dtype=torch.float32), sr


torchaudio.load = _sf_load

from TTS.api import TTS

tts = TTS('tts_models/multilingual/multi-dataset/xtts_v2').to('cuda')
model = tts.synthesizer.tts_model

text_ru = (
    "Доброе утро сэр. Все системы работают в штатном режиме. "
    "Готов к выполнению ваших команд."
)
out_dir = "/mnt/c/Users/User/Desktop"

# v5: Combined refs (Да сэр + EN morning), temp=0.3, speed=1.05
gpt_cond, spk_emb = model.get_conditioning_latents(
    audio_path=['/tmp/ref_da_sir.wav', '/tmp/ref_en_morning.wav']
)
t0 = time.time()
out = model.inference(
    text_ru, 'ru', gpt_cond, spk_emb,
    temperature=0.3, repetition_penalty=8.0, top_k=30, top_p=0.8, speed=1.05,
)
sf.write(f'{out_dir}/test_xtts_ru_v5.wav', out['wav'], 24000)
print(f"v5 (combined, t=0.3, spd=1.05): {len(out['wav'])/24000:.1f}s in {time.time()-t0:.1f}s")

# v6: Combined refs, temp=0.1, speed=1.08 (more deterministic)
t0 = time.time()
out = model.inference(
    text_ru, 'ru', gpt_cond, spk_emb,
    temperature=0.1, repetition_penalty=10.0, top_k=20, top_p=0.7, speed=1.08,
)
sf.write(f'{out_dir}/test_xtts_ru_v6.wav', out['wav'], 24000)
print(f"v6 (combined, t=0.1, spd=1.08): {len(out['wav'])/24000:.1f}s in {time.time()-t0:.1f}s")

# v7: "Да сэр" ref only, tuned
gpt2, spk2 = model.get_conditioning_latents(audio_path='/tmp/ref_da_sir.wav')
t0 = time.time()
out = model.inference(
    text_ru, 'ru', gpt2, spk2,
    temperature=0.2, repetition_penalty=9.0, top_k=25, top_p=0.75, speed=1.1,
)
sf.write(f'{out_dir}/test_xtts_ru_v7.wav', out['wav'], 24000)
print(f"v7 (Да сэр, t=0.2, spd=1.1): {len(out['wav'])/24000:.1f}s in {time.time()-t0:.1f}s")

# v8: EN morning ref, tuned for younger voice
gpt3, spk3 = model.get_conditioning_latents(audio_path='/tmp/ref_en_morning.wav')
t0 = time.time()
out = model.inference(
    text_ru, 'ru', gpt3, spk3,
    temperature=0.2, repetition_penalty=8.0, top_k=30, top_p=0.8, speed=1.05,
)
sf.write(f'{out_dir}/test_xtts_ru_v8.wav', out['wav'], 24000)
print(f"v8 (EN ref, t=0.2, spd=1.05): {len(out['wav'])/24000:.1f}s in {time.time()-t0:.1f}s")

# v9: Combined ALL good refs + optimal params
gpt4, spk4 = model.get_conditioning_latents(
    audio_path=[
        '/tmp/ref_da_sir.wav',
        '/tmp/ref_en_morning.wav',
        '/tmp/ref_uslugi.wav',
    ]
)
t0 = time.time()
out = model.inference(
    text_ru, 'ru', gpt4, spk4,
    temperature=0.25, repetition_penalty=8.0, top_k=30, top_p=0.8, speed=1.05,
)
sf.write(f'{out_dir}/test_xtts_ru_v9.wav', out['wav'], 24000)
print(f"v9 (3 refs, t=0.25, spd=1.05): {len(out['wav'])/24000:.1f}s in {time.time()-t0:.1f}s")

print("DONE - v5-v9 on Desktop!")
