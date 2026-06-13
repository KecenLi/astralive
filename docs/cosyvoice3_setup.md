# MODVII Fun-CosyVoice3 Local TTS Setup

更新时间：2026-06-13

## 选择

默认本地 TTS 接入 `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`，用于 MODVII 的中文/英文语音输出。

原因：

- Hugging Face 模型页标注 `apache-2.0`。
- 官方说明覆盖中文、英文、日文、韩文、德文、西班牙文、法文、意大利文、俄文，以及 18+ 中文方言/口音。
- 官方说明支持 zero-shot、cross-lingual、bi-streaming 和 instruct 控制。
- 官方对比表中 `Fun-CosyVoice3-0.5B-2512` 属于开源 0.5B 模型，中文、英文与困难集指标都适合作为 MODVII 的本地高质量 TTS 起点。

来源：

- Hugging Face: https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512
- CosyVoice GitHub: https://github.com/FunAudioLLM/CosyVoice
- Demo page: https://funaudiollm.github.io/cosyvoice3/

## 安装

在 Windows PowerShell 里运行：

```powershell
cd "D:\assist ai"
.\scripts\setup-cosyvoice3.ps1
```

脚本会执行：

- 拉取 `FunAudioLLM/CosyVoice` 到 `third_party\CosyVoice`。
- 创建 `third_party\CosyVoice\.venv`。
- 安装 CosyVoice requirements 和 `huggingface_hub`。
- 在 Windows 上过滤 requirements 里的 `openai-whisper`，再用 `setuptools<81` + `--no-build-isolation` 单独安装；这是因为 CosyVoice frontend 会 import whisper，而原始构建隔离在新版 setuptools 下会失败。
- 下载模型到 `models\Fun-CosyVoice3-0.5B`。
- 写入本地 `.env`，把 `TTS_PROVIDER` 切到 `cosyvoice3`。

如果只下载和安装，不想切换当前 TTS provider：

```powershell
.\scripts\setup-cosyvoice3.ps1 -NoEnvWrite
```

如果需要手工安装 PyTorch CUDA 轮子，可以传：

```powershell
.\scripts\setup-cosyvoice3.ps1 -TorchIndexUrl "https://download.pytorch.org/whl/cu121"
```

## 配置

`.env` 关键项：

```dotenv
TTS_PROVIDER=cosyvoice3
COSYVOICE3_PYTHON=D:\assist ai\third_party\CosyVoice\.venv\Scripts\python.exe
COSYVOICE3_REPO_DIR=D:\assist ai\third_party\CosyVoice
COSYVOICE3_MODEL_DIR=D:\assist ai\models\Fun-CosyVoice3-0.5B
COSYVOICE3_SCRIPT=D:\assist ai\scripts\cosyvoice3_synth.py
COSYVOICE3_PROMPT_AUDIO=D:\assist ai\third_party\CosyVoice\asset\zero_shot_prompt.wav
COSYVOICE3_DEVICE=cpu
COSYVOICE3_TIMEOUT_SECONDS=120
```

`COSYVOICE3_PROMPT_AUDIO` 决定 zero-shot 参考音色。要更“可爱、生动”，后续应换成你确认许可可用的短参考 WAV，并在本地 `.env` 指向该文件。该参考音频不要提交到 Git，除非来源许可允许公开分发。

## MODVII 集成点

- 后端 provider: `apps/server/app/providers/tts/cosyvoice3.py`
- 合成桥接脚本: `scripts/cosyvoice3_synth.py`
- 常驻合成 worker: `scripts/cosyvoice3_worker.py`
- 切换方式: `TTS_PROVIDER=cosyvoice3`
- 输出格式: `audio/wav`
- 前端播放: WebAudio 解码 WAV 后计算音量包络，驱动 Live2D `ParamMouthOpenY`

## 注意

- 模型、CosyVoice 仓库、venv 都在 `.gitignore` 内，不进入公开仓库。
- 官方 `CosyVoice-ttsfrd` 是可选资源；不安装时官方说明会使用 wetext。
- 当前机器的 RTX 5080 Laptop 是 `sm_120`，CosyVoice requirements 固定的 PyTorch 2.3.1 CUDA 轮子不支持该架构，所以默认 `COSYVOICE3_DEVICE=cpu`。要用 GPU，需要先换成支持该架构的 PyTorch/CUDA 组合，再改成 `COSYVOICE3_DEVICE=cuda`。
- 默认 `COSYVOICE3_WORKER_ENABLED=true` 会启动常驻 worker，避免每轮重新加载模型。第一次合成仍会包含模型加载时间；第二轮以后应明显快于旧的单次脚本模式。
- 如果 worker 异常，可临时设 `COSYVOICE3_WORKER_ENABLED=false` 回到旧的单次桥接脚本，便于排查环境问题。
