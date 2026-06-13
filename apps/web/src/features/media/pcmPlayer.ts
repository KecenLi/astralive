import { AssistantAudioPayload } from "../../lib/events";

export interface LipSyncEnvelopePoint {
  offsetMs: number;
  level: number;
}

export type LipSyncSink = (level: number) => void;

export function base64ToArrayBuffer(dataBase64: string) {
  const binary = atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

export function decodePcm16ToFloat32(buffer: ArrayBuffer) {
  const view = new DataView(buffer);
  const output = new Float32Array(Math.floor(buffer.byteLength / 2));
  for (let index = 0; index < output.length; index += 1) {
    output[index] = view.getInt16(index * 2, true) / 0x8000;
  }
  return output;
}

export function calculateLipSyncEnvelope(
  samples: Float32Array,
  sampleRate = 24000,
  channels = 1,
  windowMs = 50,
): LipSyncEnvelopePoint[] {
  const safeChannels = Math.max(1, channels);
  const frameCount = Math.floor(samples.length / safeChannels);
  const windowFrames = Math.max(1, Math.round((sampleRate * windowMs) / 1000));
  const envelope: LipSyncEnvelopePoint[] = [];
  let smoothed = 0;

  for (let startFrame = 0; startFrame < frameCount; startFrame += windowFrames) {
    const endFrame = Math.min(frameCount, startFrame + windowFrames);
    let sumSquares = 0;
    let count = 0;
    for (let frame = startFrame; frame < endFrame; frame += 1) {
      for (let channel = 0; channel < safeChannels; channel += 1) {
        const sample = samples[frame * safeChannels + channel] ?? 0;
        sumSquares += sample * sample;
        count += 1;
      }
    }
    const rms = count > 0 ? Math.sqrt(sumSquares / count) : 0;
    const normalized = Math.min(1, Math.max(0, (rms - 0.012) / 0.22));
    const level = Math.pow(normalized, 0.55);
    smoothed = smoothed * 0.55 + level * 0.45;
    envelope.push({
      offsetMs: Math.round((startFrame / sampleRate) * 1000),
      level: Number(smoothed.toFixed(3)),
    });
  }

  if (envelope.length === 0) {
    envelope.push({ offsetMs: 0, level: 0 });
  }
  return envelope;
}

export class AssistantAudioPlayer {
  private audioContext: AudioContext | null = null;
  private nextStartTime = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private encodedAudio = new Set<HTMLAudioElement>();
  private pendingPlays = 0;
  private lipSyncSink: LipSyncSink | null = null;
  private idleCallback: (() => void) | null = null;
  private lipSyncTimers = new Set<number>();
  private encodedLipSyncTimers = new Map<HTMLAudioElement, number>();

  setLipSyncSink(sink: LipSyncSink | null) {
    this.lipSyncSink = sink;
    this.reportLipSync(0);
  }

  setIdleCallback(callback: (() => void) | null) {
    this.idleCallback = callback;
  }

  isActive() {
    return this.hasActiveAudio();
  }

  async play(payload: AssistantAudioPayload) {
    if (!payload.data_base64) return;
    this.pendingPlays += 1;
    try {
      if (
        payload.encoding === "pcm_s16le" ||
        payload.mime.startsWith("audio/pcm") ||
        payload.mime.startsWith("audio/l16")
      ) {
        await this.playPcm(payload);
        return;
      }
      await this.playEncoded(payload);
    } finally {
      this.pendingPlays = Math.max(0, this.pendingPlays - 1);
      if (!this.hasActiveAudio()) {
        this.reportLipSync(0);
        this.idleCallback?.();
      }
    }
  }

  reset() {
    this.sources.forEach((source) => {
      try {
        source.stop();
      } catch {
        // Already stopped.
      }
    });
    this.sources.clear();
    this.pendingPlays = 0;
    this.clearLipSyncTimers();
    this.encodedAudio.forEach((audio) => {
      audio.pause();
      audio.currentTime = 0;
    });
    this.encodedAudio.clear();
    if (this.audioContext) {
      this.nextStartTime = this.audioContext.currentTime;
    }
    this.reportLipSync(0);
  }

  private async playPcm(payload: AssistantAudioPayload) {
    const audioContext = await this.getAudioContext();
    const samples = decodePcm16ToFloat32(base64ToArrayBuffer(payload.data_base64));
    const channels = Math.max(1, payload.channels || 1);
    const frameCount = Math.floor(samples.length / channels);
    if (frameCount <= 0) return;

    const audioBuffer = audioContext.createBuffer(channels, frameCount, payload.sample_rate || 24000);
    for (let channel = 0; channel < channels; channel += 1) {
      const channelData = audioBuffer.getChannelData(channel);
      for (let frame = 0; frame < frameCount; frame += 1) {
        channelData[frame] = samples[frame * channels + channel] ?? 0;
      }
    }

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    source.onended = () => {
      this.sources.delete(source);
      if (!this.hasActiveAudio()) {
        this.reportLipSync(0);
        this.idleCallback?.();
      }
    };
    this.sources.add(source);
    const startAt = Math.max(audioContext.currentTime, this.nextStartTime);
    this.scheduleLipSyncEnvelope(
      calculateLipSyncEnvelope(samples, payload.sample_rate || 24000, channels),
      startAt,
      audioContext.currentTime,
    );
    source.start(startAt);
    this.nextStartTime = startAt + audioBuffer.duration;
  }

  private async playEncoded(payload: AssistantAudioPayload) {
    try {
      await this.playDecodedEncodedAudio(payload);
      return;
    } catch {
      await this.playHtmlAudio(payload);
    }
  }

  private async playDecodedEncodedAudio(payload: AssistantAudioPayload) {
    const audioContext = await this.getAudioContext();
    const encodedBytes = base64ToArrayBuffer(payload.data_base64);
    const decoded = await audioContext.decodeAudioData(encodedBytes.slice(0));
    const source = audioContext.createBufferSource();
    source.buffer = decoded;
    source.connect(audioContext.destination);
    source.onended = () => {
      this.sources.delete(source);
      if (!this.hasActiveAudio()) {
        this.reportLipSync(0);
        this.idleCallback?.();
      }
    };
    this.sources.add(source);
    const startAt = Math.max(audioContext.currentTime, this.nextStartTime);
    this.scheduleLipSyncEnvelope(
      calculateLipSyncEnvelope(
        interleaveAudioBuffer(decoded),
        decoded.sampleRate,
        Math.max(1, decoded.numberOfChannels),
      ),
      startAt,
      audioContext.currentTime,
    );
    source.start(startAt);
    this.nextStartTime = startAt + decoded.duration;
  }

  private async playHtmlAudio(payload: AssistantAudioPayload) {
    const audio = new Audio(`data:${payload.mime};base64,${payload.data_base64}`);
    audio.onended = () => {
      this.encodedAudio.delete(audio);
      this.stopEncodedLipSync(audio);
      if (!this.hasActiveAudio()) {
        this.reportLipSync(0);
        this.idleCallback?.();
      }
    };
    this.encodedAudio.add(audio);
    try {
      await audio.play();
      this.startEncodedLipSync(audio);
    } catch (error) {
      this.encodedAudio.delete(audio);
      this.stopEncodedLipSync(audio);
      throw error;
    }
  }

  private async getAudioContext() {
    if (!this.audioContext) {
      const AudioContextCtor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) {
        throw new Error("Web Audio API is not available.");
      }
      this.audioContext = new AudioContextCtor();
      this.nextStartTime = this.audioContext.currentTime;
    }
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }
    return this.audioContext;
  }

  private scheduleLipSyncEnvelope(
    envelope: LipSyncEnvelopePoint[],
    startAtSeconds: number,
    currentTimeSeconds: number,
  ) {
    const baseDelayMs = Math.max(0, Math.round((startAtSeconds - currentTimeSeconds) * 1000));
    for (const point of envelope) {
      const timer = window.setTimeout(() => {
        this.lipSyncTimers.delete(timer);
        this.reportLipSync(point.level);
      }, baseDelayMs + point.offsetMs);
      this.lipSyncTimers.add(timer);
    }
  }

  private startEncodedLipSync(audio: HTMLAudioElement) {
    this.stopEncodedLipSync(audio);
    const startedAt = performance.now();
    const timer = window.setInterval(() => {
      if (audio.paused || audio.ended) return;
      const phase = (performance.now() - startedAt) / 145;
      const level = 0.18 + Math.abs(Math.sin(phase)) * 0.42;
      this.reportLipSync(Number(level.toFixed(3)));
    }, 80);
    this.encodedLipSyncTimers.set(audio, timer);
  }

  private stopEncodedLipSync(audio: HTMLAudioElement) {
    const timer = this.encodedLipSyncTimers.get(audio);
    if (timer) {
      window.clearInterval(timer);
      this.encodedLipSyncTimers.delete(audio);
    }
  }

  private clearLipSyncTimers() {
    this.lipSyncTimers.forEach((timer) => window.clearTimeout(timer));
    this.lipSyncTimers.clear();
    this.encodedLipSyncTimers.forEach((timer) => window.clearInterval(timer));
    this.encodedLipSyncTimers.clear();
  }

  private hasActiveAudio() {
    return this.pendingPlays > 0 || this.sources.size > 0 || this.encodedAudio.size > 0;
  }

  private reportLipSync(level: number) {
    this.lipSyncSink?.(Math.min(1, Math.max(0, level)));
  }
}

function interleaveAudioBuffer(buffer: AudioBuffer) {
  const channels = Math.max(1, buffer.numberOfChannels);
  const samples = new Float32Array(buffer.length * channels);
  for (let channel = 0; channel < channels; channel += 1) {
    const channelData = buffer.getChannelData(channel);
    for (let frame = 0; frame < buffer.length; frame += 1) {
      samples[frame * channels + channel] = channelData[frame] ?? 0;
    }
  }
  return samples;
}

export const assistantAudioPlayer = new AssistantAudioPlayer();
