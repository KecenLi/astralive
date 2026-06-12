export const LIVE_INPUT_SAMPLE_RATE = 16000;

export function downsampleBuffer(
  input: Float32Array,
  inputSampleRate: number,
  outputSampleRate = LIVE_INPUT_SAMPLE_RATE,
) {
  if (outputSampleRate <= 0 || inputSampleRate <= 0) {
    throw new Error("Sample rates must be positive.");
  }
  if (inputSampleRate === outputSampleRate) {
    return new Float32Array(input);
  }
  if (outputSampleRate > inputSampleRate) {
    throw new Error("Output sample rate cannot exceed input sample rate.");
  }

  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);

  for (let index = 0; index < outputLength; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) {
      sum += input[inputIndex];
      count += 1;
    }
    output[index] = count > 0 ? sum / count : input[Math.min(start, input.length - 1)] ?? 0;
  }

  return output;
}

export function encodePcm16(input: Float32Array) {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index] ?? 0));
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

export function arrayBufferToBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

interface PcmRecorderOptions {
  onChunk: (chunk: ArrayBuffer) => void;
  onError?: (error: Error) => void;
  outputSampleRate?: number;
}

export class PcmRecorder {
  private audioContext: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private mute: GainNode | null = null;
  private active = false;

  constructor(private readonly options: PcmRecorderOptions) {}

  async start(stream: MediaStream) {
    this.stop();
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

    processor.onaudioprocess = (event) => {
      if (!this.active) return;
      try {
        const input = event.inputBuffer.getChannelData(0);
        const downsampled = downsampleBuffer(
          input,
          audioContext.sampleRate,
          this.options.outputSampleRate ?? LIVE_INPUT_SAMPLE_RATE,
        );
        this.options.onChunk(encodePcm16(downsampled));
      } catch (error) {
        this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
      }
    };

    source.connect(processor);
    processor.connect(mute);
    mute.connect(audioContext.destination);

    this.audioContext = audioContext;
    this.source = source;
    this.processor = processor;
    this.mute = mute;
    this.active = true;
  }

  stop() {
    this.active = false;
    this.source?.disconnect();
    this.processor?.disconnect();
    this.mute?.disconnect();
    void this.audioContext?.close();
    this.audioContext = null;
    this.source = null;
    this.processor = null;
    this.mute = null;
  }

  get isActive() {
    return this.active;
  }
}
