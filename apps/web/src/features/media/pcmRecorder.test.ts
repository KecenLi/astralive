import { describe, expect, it } from "vitest";

import { arrayBufferToBase64, downsampleBuffer, encodePcm16 } from "./pcmRecorder";
import { base64ToArrayBuffer, decodePcm16ToFloat32 } from "./pcmPlayer";

describe("pcmRecorder helpers", () => {
  it("downsamples by averaging source samples", () => {
    const input = new Float32Array([0, 0.3, 0.6, 1, 1, 1, -1, -0.5, 0]);
    const output = downsampleBuffer(input, 48000, 16000);
    expect(output[0]).toBeCloseTo(0.3, 5);
    expect(output[1]).toBe(1);
    expect(output[2]).toBeCloseTo(-0.5, 5);
  });

  it("encodes little-endian signed pcm16", () => {
    const encoded = encodePcm16(new Float32Array([-1, 0, 1]));
    const view = new DataView(encoded);
    expect(view.getInt16(0, true)).toBe(-32768);
    expect(view.getInt16(2, true)).toBe(0);
    expect(view.getInt16(4, true)).toBe(32767);
  });

  it("round trips through base64 and pcm decode", () => {
    const encoded = encodePcm16(new Float32Array([0, 0.5]));
    const decoded = decodePcm16ToFloat32(base64ToArrayBuffer(arrayBufferToBase64(encoded)));
    expect(decoded[0]).toBe(0);
    expect(decoded[1]).toBeCloseTo(0.5, 4);
  });
});
