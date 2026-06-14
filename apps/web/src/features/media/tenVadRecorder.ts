import { createVoiceDetector } from "defuss-vad/tenvad-web";
import type { VoiceDetector, VoiceDetectorResult } from "defuss-vad/types";

import { applyFloatGain, downsampleBuffer, LIVE_INPUT_SAMPLE_RATE } from "./pcmRecorder";

const FRAME_SAMPLES = 256;
const DEFAULT_PRE_ROLL_MS = 320;
const DEFAULT_INITIAL_SILENCE_MS = 10_000;
const DEFAULT_MAX_TURN_MS = 24_000;
const DEFAULT_MIN_SPEECH_MS = 260;

interface TenVadRecorderOptions {
  onSpeechStart?: () => void;
  onSpeechChunk?: (audio: ArrayBuffer) => void;
  onSpeechEnd: (audio: ArrayBuffer, stats: TenVadTurnStats) => void;
  onVADMisfire?: (stats: TenVadTurnStats) => void;
  onNoSpeechTimeout?: () => void;
  onError?: (error: Error) => void;
  onDebug?: (message: string, detail?: unknown) => void;
  threshold?: number;
  rmsFloor?: number;
  debounceOn?: number;
  debounceOff?: number;
  preRollMs?: number;
  initialSilenceMs?: number;
  maxTurnMs?: number;
  minSpeechMs?: number;
  inputGain?: number;
  streamChunks?: boolean;
}

export interface TenVadTurnStats {
  reason: "ten_vad_end" | "max_turn";
  durationMs: number;
  frames: number;
  speechFrames: number;
  peakProbability: number;
  peakRms: number;
  averageRms: number;
}

function floatToInt16Frame(frame: Float32Array) {
  const samples = new Int16Array(frame.length);
  for (let index = 0; index < frame.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, frame[index] ?? 0));
    samples[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return samples;
}

function concatInt16Frames(frames: Int16Array[]) {
  const totalSamples = frames.reduce((sum, frame) => sum + frame.length, 0);
  const output = new Int16Array(totalSamples);
  let offset = 0;
  for (const frame of frames) {
    output.set(frame, offset);
    offset += frame.length;
  }
  return output.buffer.slice(output.byteOffset, output.byteOffset + output.byteLength);
}

function concatFloat32(left: Float32Array, right: Float32Array) {
  if (left.length === 0) return new Float32Array(right);
  const output = new Float32Array(left.length + right.length);
  output.set(left);
  output.set(right, left.length);
  return output;
}

export class TenVadRecorder {
  private audioContext: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private mute: GainNode | null = null;
  private detector: VoiceDetector | null = null;
  private processing = Promise.resolve();
  private residual = new Float32Array(0);
  private active = false;
  private speechStarted = false;
  private turnStartedAt = 0;
  private lastVoiceAt = 0;
  private preRoll: Int16Array[] = [];
  private segment: Int16Array[] = [];
  private streamedAudio = false;
  private speechSampleCount = 0;
  private frames = 0;
  private speechFrames = 0;
  private peakProbability = 0;
  private peakRms = 0;
  private rmsSum = 0;
  private readonly preRollFrames: number;
  private readonly initialSilenceMs: number;
  private readonly maxTurnMs: number;
  private readonly minSpeechMs: number;

  constructor(private readonly options: TenVadRecorderOptions) {
    this.preRollFrames = Math.max(
      1,
      Math.ceil(((options.preRollMs ?? DEFAULT_PRE_ROLL_MS) / 1000) * LIVE_INPUT_SAMPLE_RATE / FRAME_SAMPLES),
    );
    this.initialSilenceMs = options.initialSilenceMs ?? DEFAULT_INITIAL_SILENCE_MS;
    this.maxTurnMs = options.maxTurnMs ?? DEFAULT_MAX_TURN_MS;
    this.minSpeechMs = options.minSpeechMs ?? DEFAULT_MIN_SPEECH_MS;
  }

  async start(stream: MediaStream) {
    this.stopAudioNodes();
    this.detector = await createVoiceDetector({
      threshold: this.options.threshold ?? 0.72,
      rmsFloor: this.options.rmsFloor ?? 0.012,
      debounceOn: this.options.debounceOn ?? 4,
      debounceOff: this.options.debounceOff ?? 42,
      hopSize: FRAME_SAMPLES,
    });
    const version = await this.detector.getVersion().catch(() => "unknown");
    this.options.onDebug?.("MODVII mic TEN VAD loaded", { version });

    const AudioContextCtor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) {
      throw new Error("Web Audio API is not available.");
    }

    const audioContext = new AudioContextCtor();
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const mute = audioContext.createGain();
    mute.gain.value = 0;

    this.active = true;
    this.turnStartedAt = performance.now();
    processor.onaudioprocess = (event) => {
      if (!this.active) return;
      const input = event.inputBuffer.getChannelData(0);
      const downsampled = downsampleBuffer(input, audioContext.sampleRate, LIVE_INPUT_SAMPLE_RATE);
      this.processing = this.processing
        .then(() => this.processDownsampled(downsampled))
        .catch((error) => {
          this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
        });
    };

    source.connect(processor);
    processor.connect(mute);
    mute.connect(audioContext.destination);

    this.audioContext = audioContext;
    this.source = source;
    this.processor = processor;
    this.mute = mute;
  }

  stop() {
    this.active = false;
    this.stopAudioNodes();
    const detector = this.detector;
    this.detector = null;
    void detector?.destroy().catch((error) => {
      this.options.onDebug?.("MODVII mic TEN VAD destroy failed", error);
    });
    this.resetTurn();
  }

  private async processDownsampled(input: Float32Array) {
    const detector = this.detector;
    if (!detector || !this.active) return;

    const combined = concatFloat32(this.residual, input);
    let offset = 0;
    while (offset + FRAME_SAMPLES <= combined.length && this.active) {
      const floatFrame = combined.slice(offset, offset + FRAME_SAMPLES);
      offset += FRAME_SAMPLES;
      await this.processFrame(detector, floatToInt16Frame(applyFloatGain(floatFrame, this.options.inputGain ?? 1)));
    }
    this.residual = combined.slice(offset);
  }

  private async processFrame(detector: VoiceDetector, frame: Int16Array) {
    const result = await detector.process(frame);
    const now = performance.now();
    this.updateStats(result);

    if (!this.speechStarted) {
      this.pushPreRoll(frame);
      if (result.onVoiceStart) {
        this.speechStarted = true;
        this.lastVoiceAt = now;
        const initialFrames = [...this.preRoll, frame];
        this.speechSampleCount = initialFrames.reduce((sum, item) => sum + item.length, 0);
        this.options.onSpeechStart?.();
        if (this.options.streamChunks && this.options.onSpeechChunk) {
          this.options.onSpeechChunk(concatInt16Frames(initialFrames));
          this.segment = [];
          this.streamedAudio = true;
        } else {
          this.segment = initialFrames;
        }
        this.preRoll = [];
        return;
      }
      if (now - this.turnStartedAt >= this.initialSilenceMs) {
        this.active = false;
        this.options.onNoSpeechTimeout?.();
      }
      return;
    }

    this.speechSampleCount += frame.length;
    if (this.options.streamChunks && this.options.onSpeechChunk) {
      this.options.onSpeechChunk(concatInt16Frames([frame]));
      this.streamedAudio = true;
    } else {
      this.segment.push(frame);
    }
    if (result.isVoiceStable || result.isVoice) {
      this.lastVoiceAt = now;
    }

    const durationMs = (this.speechSampleCount / LIVE_INPUT_SAMPLE_RATE) * 1000;
    if (result.onVoiceEnd) {
      this.finishTurn("ten_vad_end", durationMs);
      return;
    }
    if (now - this.turnStartedAt >= this.maxTurnMs) {
      this.finishTurn("max_turn", durationMs);
    }
  }

  private finishTurn(reason: TenVadTurnStats["reason"], durationMs: number) {
    const stats = this.stats(reason, durationMs);
    const audio = this.streamedAudio ? new ArrayBuffer(0) : concatInt16Frames(this.segment);
    this.resetTurn();
    if (durationMs < this.minSpeechMs) {
      this.options.onVADMisfire?.(stats);
      return;
    }
    this.options.onSpeechEnd(audio, stats);
  }

  private stats(reason: TenVadTurnStats["reason"], durationMs: number): TenVadTurnStats {
    return {
      reason,
      durationMs: Math.round(durationMs),
      frames: this.frames,
      speechFrames: this.speechFrames,
      peakProbability: Number(this.peakProbability.toFixed(4)),
      peakRms: Number(this.peakRms.toFixed(4)),
      averageRms: Number((this.frames > 0 ? this.rmsSum / this.frames : 0).toFixed(4)),
    };
  }

  private updateStats(result: VoiceDetectorResult) {
    this.frames += 1;
    if (result.isVoiceStable || result.isVoice) this.speechFrames += 1;
    this.peakProbability = Math.max(this.peakProbability, result.probability);
    this.peakRms = Math.max(this.peakRms, result.rms);
    this.rmsSum += result.rms;
  }

  private pushPreRoll(frame: Int16Array) {
    this.preRoll.push(frame);
    while (this.preRoll.length > this.preRollFrames) {
      this.preRoll.shift();
    }
  }

  private resetTurn() {
    this.residual = new Float32Array(0);
    this.speechStarted = false;
    this.turnStartedAt = performance.now();
    this.lastVoiceAt = 0;
    this.preRoll = [];
    this.segment = [];
    this.streamedAudio = false;
    this.speechSampleCount = 0;
    this.frames = 0;
    this.speechFrames = 0;
    this.peakProbability = 0;
    this.peakRms = 0;
    this.rmsSum = 0;
    void this.detector?.reset().catch(() => undefined);
  }

  private stopAudioNodes() {
    this.source?.disconnect();
    this.processor?.disconnect();
    this.mute?.disconnect();
    void this.audioContext?.close();
    this.audioContext = null;
    this.source = null;
    this.processor = null;
    this.mute = null;
  }
}
