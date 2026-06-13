export interface LiveAudioGateOptions {
  sampleRate?: number;
  startThreshold?: number;
  continueThreshold?: number;
  minContinueThreshold?: number;
  noiseMargin?: number;
  peakDropRatio?: number;
  preRollMs?: number;
  initialSilenceMs?: number;
  silenceAfterSpeechMs?: number;
  maxTurnMs?: number;
}

export interface LiveAudioGateDecision {
  chunks: ArrayBuffer[];
  rms: number;
  state: "waiting" | "speaking" | "silence" | "initial_timeout" | "max_turn";
  shouldStop: boolean;
  sendFinal: boolean;
}

const DEFAULT_OPTIONS = {
  sampleRate: 16000,
  startThreshold: 0.01,
  continueThreshold: 0.006,
  minContinueThreshold: 0.002,
  noiseMargin: 0.003,
  peakDropRatio: 0.22,
  preRollMs: 300,
  initialSilenceMs: 6000,
  silenceAfterSpeechMs: 1200,
  maxTurnMs: 20000,
};

type ResolvedLiveAudioGateOptions = typeof DEFAULT_OPTIONS;

export function pcm16Rms(buffer: ArrayBuffer) {
  const view = new DataView(buffer);
  const sampleCount = Math.floor(buffer.byteLength / 2);
  if (sampleCount === 0) return 0;

  let sumSquares = 0;
  for (let index = 0; index < sampleCount; index += 1) {
    const sample = view.getInt16(index * 2, true) / 0x8000;
    sumSquares += sample * sample;
  }
  return Math.sqrt(sumSquares / sampleCount);
}

export function pcm16DurationMs(buffer: ArrayBuffer, sampleRate = DEFAULT_OPTIONS.sampleRate) {
  if (sampleRate <= 0) return 0;
  return (Math.floor(buffer.byteLength / 2) / sampleRate) * 1000;
}

export class LiveAudioGate {
  private readonly options: ResolvedLiveAudioGateOptions;
  private startedAtMs: number | null = null;
  private lastVoiceAtMs: number | null = null;
  private speechStarted = false;
  private preRoll: ArrayBuffer[] = [];
  private preRollDurationMs = 0;
  private noiseFloor = 0.001;
  private speechPeakRms = 0;

  constructor(options: LiveAudioGateOptions = {}) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
  }

  accept(chunk: ArrayBuffer, nowMs = performance.now()): LiveAudioGateDecision {
    if (this.startedAtMs === null) {
      this.startedAtMs = nowMs;
    }

    const rms = pcm16Rms(chunk);
    const elapsedMs = nowMs - this.startedAtMs;
    const startThreshold = Math.max(
      this.options.minContinueThreshold,
      Math.min(this.options.startThreshold, this.noiseFloor + this.options.noiseMargin * 2),
    );
    const isStartVoice = rms >= startThreshold;

    if (!this.speechStarted) {
      if (!isStartVoice) {
        this.updateNoiseFloor(rms);
      }
      this.pushPreRoll(chunk);
      if (isStartVoice) {
        this.speechStarted = true;
        this.lastVoiceAtMs = nowMs;
        this.speechPeakRms = Math.max(this.speechPeakRms, rms);
        const chunks = this.preRoll;
        this.preRoll = [];
        this.preRollDurationMs = 0;
        return { chunks, rms, state: "speaking", shouldStop: false, sendFinal: false };
      }

      if (elapsedMs >= this.options.initialSilenceMs) {
        this.reset();
        return { chunks: [], rms, state: "initial_timeout", shouldStop: true, sendFinal: false };
      }

      return { chunks: [], rms, state: "waiting", shouldStop: false, sendFinal: false };
    }

    this.speechPeakRms = Math.max(this.speechPeakRms, rms);
    const continueThreshold = Math.max(
      this.options.minContinueThreshold,
      this.noiseFloor + this.options.noiseMargin,
      this.speechPeakRms * this.options.peakDropRatio,
      Math.min(this.options.continueThreshold, this.options.startThreshold),
    );
    const isContinuingVoice = rms >= continueThreshold;

    if (isContinuingVoice) {
      this.lastVoiceAtMs = nowMs;
    } else {
      this.updateNoiseFloor(rms);
    }

    if (elapsedMs >= this.options.maxTurnMs) {
      this.reset();
      return { chunks: [chunk], rms, state: "max_turn", shouldStop: true, sendFinal: true };
    }

    const silenceMs = this.lastVoiceAtMs === null ? 0 : nowMs - this.lastVoiceAtMs;
    if (silenceMs >= this.options.silenceAfterSpeechMs) {
      this.reset();
      return { chunks: [chunk], rms, state: "silence", shouldStop: true, sendFinal: true };
    }

    return {
      chunks: [chunk],
      rms,
      state: isContinuingVoice ? "speaking" : "silence",
      shouldStop: false,
      sendFinal: false,
    };
  }

  reset() {
    this.startedAtMs = null;
    this.lastVoiceAtMs = null;
    this.speechStarted = false;
    this.preRoll = [];
    this.preRollDurationMs = 0;
    this.noiseFloor = 0.001;
    this.speechPeakRms = 0;
  }

  get hasSpeechStarted() {
    return this.speechStarted;
  }

  private pushPreRoll(chunk: ArrayBuffer) {
    this.preRoll.push(chunk);
    this.preRollDurationMs += pcm16DurationMs(chunk, this.options.sampleRate);

    while (this.preRollDurationMs > this.options.preRollMs && this.preRoll.length > 1) {
      const removed = this.preRoll.shift();
      if (removed) {
        this.preRollDurationMs -= pcm16DurationMs(removed, this.options.sampleRate);
      }
    }
  }

  private updateNoiseFloor(rms: number) {
    const bounded = Math.max(0, Math.min(0.1, rms));
    this.noiseFloor = Math.min(
      Math.max(this.noiseFloor * 0.95 + bounded * 0.05, 0.0005),
      Math.max(bounded, 0.0005),
    );
  }
}
