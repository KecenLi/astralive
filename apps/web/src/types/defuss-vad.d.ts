declare module "defuss-vad/types" {
  export interface VoiceDetectorResult {
    probability: number;
    isVoice: boolean;
    rms: number;
    isVoiceStable: boolean;
    onVoiceStart: boolean;
    onVoiceEnd: boolean;
  }

  export interface VoiceDetector {
    process(samples: Int16Array): Promise<VoiceDetectorResult>;
    getVersion(): Promise<string>;
    reset(): Promise<void>;
    destroy(): Promise<void>;
  }

  export interface VoiceDetectorOptions {
    hopSize?: number;
    threshold?: number;
    rmsFloor?: number;
    debounceOn?: number;
    debounceOff?: number;
    wasmBinary?: ArrayBuffer | Uint8Array;
    locateFile?: (path: string, prefix: string) => string;
  }
}

declare module "defuss-vad/tenvad-web" {
  import type { VoiceDetector, VoiceDetectorOptions } from "defuss-vad/types";

  export function createVoiceDetector(options?: VoiceDetectorOptions): Promise<VoiceDetector>;
}
