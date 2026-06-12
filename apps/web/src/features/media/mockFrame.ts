import { FramePayload } from "../../lib/events";

export function createMockFrame(reason: FramePayload["capture_reason"], prompt: string): FramePayload {
  return {
    frame_id: `frame_mock_${Date.now()}`,
    mime: "image/jpeg",
    width: 640,
    height: 360,
    quality: 0.72,
    capture_reason: reason,
    scene_hash: "mock-scene",
    data_base64: "mock-image-data",
    prompt,
  };
}

