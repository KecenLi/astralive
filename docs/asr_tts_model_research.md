# MODVII ASR Low Model and TTS Compute Notes

Date: 2026-06-14

## Current Local State

- Current default ASR is local Whisper `base` on CUDA:
  - `LOCAL_ASR_MODEL=base`
  - `LOCAL_ASR_MODEL_PATH=D:\assist ai\models\whisper\base.pt`
  - `LOCAL_ASR_DEVICE=cuda`
- `large-v3.pt` is still available locally, but it is not the default because it competes with CosyVoice3 for VRAM and increases turn latency.
- Final packaged real-provider smoke on `low_noise` passed end-to-end, but the last run only recognized the wake word (`小七。`) instead of the full request. That means the pipeline is stable, but ASR quality still needs a better light model.
- `white_noise` did not crash the app, but Whisper `base` produced punctuation-only text. MODVII now detects that and returns to listening instead of sending garbage to the LLM.

## ASR Recommendation

Do not spend more effort on Whisper `tiny` as the main Chinese/English assistant recognizer. It is lighter than `base`, but the current `base` result already shows weak robustness under noise, and `tiny` will usually trade away more accuracy.

Recommended next local ASR tests:

1. **SenseVoice-Small via FunASR / OpenAI-compatible local endpoint**
   - Best first candidate for MODVII.
   - Supports multilingual recognition and includes emotion/audio-event metadata.
   - FunASR documentation reports SenseVoice-Small as much faster than Whisper-large-v3 and CPU-viable; it also provides streaming and OpenAI-compatible service modes.

2. **Fun-ASR-Nano**
   - Candidate when VRAM pressure is the top constraint.
   - Lower accuracy expected than SenseVoice-Small, but useful as the lowest-cost fallback.

3. **sherpa-onnx Paraformer-small or Zipformer bilingual**
   - Best candidate for true streaming/on-device endpointing.
   - Especially useful if we want VAD + ASR in one low-latency local pipeline.

4. **faster-whisper `small` or `distil-large-v3`**
   - Good if we want to stay inside the Whisper ecosystem.
   - `small` is a safer accuracy step above `base`; `distil-large-v3`/`turbo` can reduce memory versus full `large-v3`, but they are still larger than `base` and not the lowest-VRAM route.

## TTS Compute Assessment

`Fun-CosyVoice3-0.5B-2512` is not a lightweight TTS model. It is a high-quality, expressive, multilingual zero-shot voice model. In the open-source TTS landscape it sits in the **medium-to-heavy local TTS** category:

- Much heavier than Piper/VITS-style edge TTS.
- Similar class to other zero-shot/few-shot voice cloning systems like GPT-SoVITS in capability target, though implementation details differ.
- Lighter than very large speech/chat stacks, but still heavy enough to require GPU scheduling when ASR also uses CUDA.

Current MODVII mitigation is correct:

- Keep ASR on a lighter model by default.
- Serialize local GPU ASR/TTS work so Whisper and CosyVoice3 do not run inference on the same GPU at the same time.
- Keep CosyVoice3 for personality/voice quality, but use a lighter ASR model for responsiveness.

## Next Test Matrix

- Baseline: current Whisper `base` CUDA on `quiet`, `low_noise`, `white_noise`, `fan_low`.
- Candidate 1: SenseVoice-Small local service on the same profiles.
- Candidate 2: Fun-ASR-Nano local service on the same profiles.
- Candidate 3: sherpa-onnx Paraformer-small or bilingual Zipformer on `low_noise` and live microphone.

Pass criteria:

- ASR final latency p95 under 1.2s after speech end.
- Recognizes `小七` plus at least the main command phrase under `low_noise`.
- Does not return punctuation-only text under `white_noise`; if it cannot recognize speech, it must return empty/low-confidence cleanly.
- Does not push CosyVoice3 into CUDA OOM during back-to-back turns.

## Sources

- OpenAI Whisper model size table: https://github.com/openai/whisper
- faster-whisper benchmark and quantization notes: https://github.com/SYSTRAN/faster-whisper
- SenseVoice / FunAudioLLM notes: https://github.com/FunAudioLLM/SenseVoice
- FunASR benchmark and OpenAI-compatible/streaming notes: https://github.com/modelscope/FunASR
- sherpa-onnx streaming ASR model list: https://github.com/k2-fsa/sherpa-onnx
- CosyVoice3 feature notes: https://github.com/FunAudioLLM/CosyVoice
- Fun-CosyVoice3-0.5B-2512 model card: https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512
- Piper lightweight TTS reference: https://github.com/rhasspy/piper
- GPT-SoVITS reference: https://github.com/RVC-Boss/GPT-SoVITS
