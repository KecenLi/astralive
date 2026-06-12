import { AssistantAudioPayload } from "../../lib/events";

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

export class AssistantAudioPlayer {
  private audioContext: AudioContext | null = null;
  private nextStartTime = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private encodedAudio = new Set<HTMLAudioElement>();

  async play(payload: AssistantAudioPayload) {
    if (!payload.data_base64) return;
    if (
      payload.encoding === "pcm_s16le" ||
      payload.mime.startsWith("audio/pcm") ||
      payload.mime.startsWith("audio/l16")
    ) {
      await this.playPcm(payload);
      return;
    }
    await this.playEncoded(payload);
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
    this.encodedAudio.forEach((audio) => {
      audio.pause();
      audio.currentTime = 0;
    });
    this.encodedAudio.clear();
    if (this.audioContext) {
      this.nextStartTime = this.audioContext.currentTime;
    }
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
    source.onended = () => this.sources.delete(source);
    this.sources.add(source);
    const startAt = Math.max(audioContext.currentTime, this.nextStartTime);
    source.start(startAt);
    this.nextStartTime = startAt + audioBuffer.duration;
  }

  private async playEncoded(payload: AssistantAudioPayload) {
    const audio = new Audio(`data:${payload.mime};base64,${payload.data_base64}`);
    audio.onended = () => this.encodedAudio.delete(audio);
    this.encodedAudio.add(audio);
    try {
      await audio.play();
    } catch (error) {
      this.encodedAudio.delete(audio);
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
}

export const assistantAudioPlayer = new AssistantAudioPlayer();
