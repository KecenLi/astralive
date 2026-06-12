import { FramePayload } from "../../lib/events";
import { computeAverageHash } from "./sceneHash";

export async function captureVideoFrame(
  video: HTMLVideoElement,
  reason: FramePayload["capture_reason"],
  prompt: string,
  options: { quality: number; maxWidth: number; maxHeight: number },
): Promise<FramePayload> {
  const ratio = Math.min(
    1,
    options.maxWidth / video.videoWidth,
    options.maxHeight / video.videoHeight,
  );
  const width = Math.max(1, Math.round(video.videoWidth * ratio));
  const height = Math.max(1, Math.round(video.videoHeight * ratio));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is not available.");
  ctx.drawImage(video, 0, 0, width, height);
  const dataUrl = canvas.toDataURL("image/jpeg", options.quality);
  return {
    frame_id: `frame_${Date.now()}`,
    mime: "image/jpeg",
    width,
    height,
    quality: options.quality,
    capture_reason: reason,
    scene_hash: computeAverageHash(canvas),
    data_base64: dataUrl.split(",")[1] ?? "",
    prompt,
  };
}

